"""Cevap hattı: yedi basamaklı derin araştırma + kural tabanlı doğrulama.

Basamaklar:
 1 İşlem kartları ve doğrulanmış soru-cevap bankası
 2 Yerel kütüphane (terim genişletmeli tam metin arama)
 3 Atıf zinciri
 4 Canlı resmî arama (sağlayıcılar)
 5 Yargı ve denetim kararları (sağlayıcılar)
 6 Emsal ve benzer sorular
 7 Sentez ve doğrulama

Çıplak "bilmiyorum" yoktur: doğrudan hüküm bulunamazsa kesin olanlar, en yakın hüküm,
somut yol ve takip birlikte verilir.
"""

from __future__ import annotations

import json
import re
import time
from typing import Callable, Protocol

from ..core.turkce import katla
from ..library.db import Kutuphane, Pasaj, _terim_kok
from ..library.sozluk import birim_oner, genislet
from .dogrulama import DogrulamaMotoru
from .llm import ANLAMA_ISTEMI, TASLAK_ISTEMI, BosModel, DilModeli, json_cikar
from .modeller import BelgeRef, Cevap, Cumle, Durum, Kaynak

IlerlemeFn = Callable[[int, int, str], None]
TOPLAM_ADIM = 7
_FORM_KODU = re.compile(r"\b(?:TOGÜ\.)?(FRM|YÖN|USE|PRS)\.(\d{3})\b")


class Saglayici(Protocol):
    ad: str

    def ara(self, soru: str, terimler: list[str]) -> int:
        """Kaynaktan ilgili belgeleri getirip kütüphaneye ekler; eklenen belge sayısını döndürür."""
        ...


def _cumlelere_bol(metin: str) -> list[str]:
    parcalar = re.split(r"(?<=[.;:])\s+(?=[(A-ZÇĞİÖŞÜ0-9])", metin.strip())
    return [p.strip() for p in parcalar if len(p.strip()) > 15]


def _anlamli_terimler(soru: str) -> list[str]:
    durak = {"nasil", "nedir", "midir", "hangi", "icin", "olan", "olarak", "kadar", "zaman",
             "gerekir", "gerekiyor", "yapilir", "nelerdir", "var", "yok", "ile", "veya", "bir"}
    return [t for t in re.findall(r"[a-z0-9]+", katla(soru)) if len(t) >= 3 and t not in durak]


def _kapsama(soru: str, metin: str) -> float:
    terimler = _anlamli_terimler(soru)
    if not terimler:
        return 0.0
    hedef = katla(metin)
    return sum(1 for t in terimler if _terim_kok(t) in hedef) / len(terimler)


def taslak_girdisi(soru: str, kaynaklar: list[Kaynak]) -> str:
    """Modele verilen girdi (eğitim verisinde de aynı biçim kullanılır)."""
    bloklar = []
    for k in kaynaklar:
        metin = k.pasaj.metin if len(k.pasaj.metin) <= 1500 else k.pasaj.metin[:1500] + " …"
        bloklar.append(f"[{k.kid}] {k.etiket}\n{metin}")
    return f"SORU: {soru}\n\nKAYNAK PARÇALARI:\n\n" + "\n\n".join(bloklar)


def dogrulanmis_cikti(cevap: Cevap) -> str:
    """Doğrulama motorundan geçen cevabın model çıktısı biçimi (eğitim hedefi)."""
    def liste(cumleler):
        return [{"metin": c.metin, "kaynaklar": c.kaynaklar} for c in cumleler if c.tur != "yonlendirme"]
    return json.dumps({
        "dogrudan_cevap": cevap.durum != Durum.HUKUM_YOK,
        "kisa_cevap": liste(cevap.kisa_cevap), "adimlar": liste(cevap.adimlar),
        "dikkat": liste(cevap.dikkat), "acik_nokta": cevap.acik_nokta,
    }, ensure_ascii=False)


class CevapHatti:
    def __init__(self, kutuphane: Kutuphane, dogrulama: DogrulamaMotoru,
                 model: DilModeli | None = None,
                 cevrimici: list[Saglayici] | None = None,
                 yargi: list[Saglayici] | None = None,
                 depo=None, cevrimici_mi: Callable[[], bool] = lambda: True,
                 ogrenme=None, siralayici=None):
        self.kutuphane = kutuphane
        self.dogrulama = dogrulama
        self.model = model or BosModel()
        self.cevrimici = cevrimici or []
        self.yargi = yargi or []
        self.depo = depo
        self.cevrimici_mi = cevrimici_mi
        self.ogrenme = ogrenme          # öğrenilmiş terimler, kaynak puanları, örnek hafıza
        self.siralayici = siralayici    # her gece kendini eğiten sıralayıcı

    # ------------------------------------------------------------------ ana giriş
    def cevapla(self, soru: str, mod: str = "derin", ilerleme: IlerlemeFn | None = None,
                kayit: bool = True) -> Cevap:
        """kayit=False: öz değerlendirme gibi iç kullanımlarda olay ve takip kaydı yapılmaz."""
        bas = time.time()
        cevap = Cevap(soru=soru, mod=mod, model_kullanildi=self.model.hazir)
        bildir = ilerleme or (lambda a, t, m: None)

        def adim(no: int, mesaj: str) -> None:
            cevap.ilerleme.append(f"{no}/{TOPLAM_ADIM} · {mesaj}")
            bildir(no, TOPLAM_ADIM, mesaj)

        havuz: dict[int, Pasaj] = {}
        adimlar_karttan: list[Cumle] = []
        kart_dayanak: list[str] = []

        # 1) İşlem kartları ve soru-cevap bankası
        adim(1, "İşlem kartları ve soru-cevap bankası taranıyor")
        for kart in self.kutuphane.kart_ara(soru):
            icerik = json.loads(kart["icerik"])
            kart_dayanak.extend(json.loads(kart["dayanak"]))
            for a in icerik.get("adimlar", []):
                adimlar_karttan.append(Cumle(a.get("metin", ""), a.get("kaynaklar", []), "adim"))
            for f in icerik.get("formlar", []):
                cevap.belgeler.append(BelgeRef(f.get("kod", ""), f.get("ad", ""), f.get("url", "")))
        for sc in self.kutuphane.soru_cevap_ara(soru):
            if sc and sc["durum"] == "dogrulandi":
                kart_dayanak.extend(json.loads(sc["dayanak"]))
        for ref in kart_dayanak:
            if "/" in ref:
                kimlik, no = ref.rsplit("/", 1)
                p = self.kutuphane.madde_getir(kimlik, no)
                if p:
                    p.skor = max(p.skor, 50.0)
                    havuz[p.madde_id] = p

        # 2) Yerel kütüphane
        adim(2, "Yerel kütüphanede aranıyor")
        terimler = self._soruyu_anla(soru)
        ek = genislet(soru) + terimler
        if self.ogrenme is not None:
            ek += self.ogrenme.ogrenilmis_terimler(soru)
        for p in self.kutuphane.ara(soru, limit=8, ek_terimler=ek):
            havuz.setdefault(p.madde_id, p)

        yeterli = self._dogrudan_mi(soru, havuz)
        if mod == "hizli" and not yeterli:
            mod = cevap.mod = "derin"   # kendiliğinden derin araştırmaya geç

        if mod == "derin" or not yeterli:
            # 3) Atıf zinciri
            adim(3, "Atıf zinciri izleniyor")
            for p in sorted(havuz.values(), key=lambda x: -x.skor)[:3]:
                for q in self.kutuphane.atif_zinciri(p):
                    q.skor = p.skor * 0.6
                    havuz.setdefault(q.madde_id, q)

            # 4) Canlı resmî arama
            if self.cevrimici and self.cevrimici_mi():
                adim(4, "Resmî kaynaklarda canlı arama yapılıyor")
                if self._saglayicilari_calistir(self.cevrimici, soru, terimler):
                    for p in self.kutuphane.ara(soru, limit=8, ek_terimler=ek):
                        havuz.setdefault(p.madde_id, p)
            else:
                cevap.cevrimdisi = not self.cevrimici_mi()
                adim(4, "Canlı arama atlandı" + (" (çevrimdışı)" if cevap.cevrimdisi else ""))

            # 5) Yargı ve denetim kararları
            if self.yargi and self.cevrimici_mi():
                adim(5, "Yargı ve denetim kararları taranıyor")
                if self._saglayicilari_calistir(self.yargi, soru, terimler):
                    for p in self.kutuphane.ara(soru, limit=6, ek_terimler=ek):
                        havuz.setdefault(p.madde_id, p)
            else:
                adim(5, "Yargı kararları sağlayıcısı tanımlı değil")

            # 6) Emsal ve benzer sorular
            adim(6, "Emsal ve benzer sorular değerlendiriliyor")
        else:
            for n, m in ((3, "Atıf zinciri gerekmedi"), (4, "Canlı arama gerekmedi"),
                         (5, "Yargı taraması gerekmedi"), (6, "Emsal taraması gerekmedi")):
                adim(n, m)

        # 7) Sentez ve doğrulama
        adim(7, "Sentez ve doğrulama")
        if self.siralayici is not None and self.siralayici.aktif:
            self.siralayici.uygula(soru, list(havuz.values()))
        elif self.ogrenme is not None:
            self.ogrenme.siralamayi_ayarla(list(havuz.values()))
        pasajlar = sorted(havuz.values(), key=lambda x: (x.belge_turu in ("emsal", "ipucu"), -x.skor))[:6]
        cevap.kaynaklar = [Kaynak(f"K{i}", p) for i, p in enumerate(pasajlar, 1)]
        dogrudan = self._dogrudan_mi(soru, havuz)

        if pasajlar and self.model.hazir:
            self._model_ile_taslak(cevap, dogrudan)
        elif pasajlar and dogrudan:
            self._alintiya_dayali_taslak(cevap)
        cevap.adimlar = cevap.adimlar or adimlar_karttan
        self._belgeleri_bul(cevap)
        self.dogrulama.dogrula(cevap)

        if cevap.durum == Durum.HUKUM_YOK:
            self._hukum_yok(cevap, takip=kayit)
        cevap.sure_sn = round(time.time() - bas, 2)
        if kayit and self.ogrenme is not None:
            try:
                cevap.olay_id = self.ogrenme.olay_kaydet(
                    cevap, taslak_girdisi(cevap.soru, cevap.kaynaklar), dogrulanmis_cikti(cevap))
            except Exception:
                pass
        return cevap

    # ------------------------------------------------------------------ yardımcılar
    def _soruyu_anla(self, soru: str) -> list[str]:
        if not self.model.hazir:
            return []
        try:
            cikti = self.model.sohbet(
                [{"role": "system", "content": ANLAMA_ISTEMI}, {"role": "user", "content": soru}],
                max_tokens=250, json_mod=True)
            veri = json_cikar(cikti) or {}
            return [str(t) for t in veri.get("terimler", [])][:8]
        except Exception:
            return []

    def _dogrudan_mi(self, soru: str, havuz: dict[int, Pasaj]) -> bool:
        if not havuz:
            return False
        en_iyi = max(havuz.values(), key=lambda p: p.skor)
        if en_iyi.skor >= 50:   # onaylı kart / soru-cevap dayanağı
            return True
        kapsama = max(_kapsama(soru, p.baslik + " " + p.metin) for p in havuz.values())
        return kapsama >= 0.6

    def _saglayicilari_calistir(self, saglayicilar: list[Saglayici], soru: str, terimler: list[str]) -> int:
        toplam = 0
        for s in saglayicilar:
            try:
                toplam += s.ara(soru, terimler)
            except Exception:
                continue
        return toplam

    def _alintiya_dayali_taslak(self, cevap: Cevap) -> None:
        """Model yokken: en ilgili maddeden soruyla örtüşen cümleleri alıntılar."""
        k1 = cevap.kaynaklar[0]
        cevap.kisa_cevap.append(Cumle(f"Sorunuzla en ilgili hüküm: {k1.etiket}.", [k1.kid], "bilgi"))
        cumleler = _cumlelere_bol(k1.pasaj.metin)
        puanli = sorted(cumleler, key=lambda c: -_kapsama(cevap.soru, c))[:2]
        for c in sorted(puanli, key=cumleler.index):
            alinti = c if len(c) <= 420 else c[:417].rsplit(" ", 1)[0] + "…"
            if alinti.endswith("…"):
                cevap.kisa_cevap.append(Cumle(alinti, [k1.kid], "alinti"))
            else:
                cevap.kisa_cevap.append(Cumle(f"“{alinti}”", [k1.kid], "alinti"))
        for k in cevap.kaynaklar[1:3]:
            if _kapsama(cevap.soru, k.pasaj.metin) >= 0.5:
                cevap.dikkat.append(Cumle(f"İlgili diğer hüküm: {k.etiket}.", [k.kid], "bilgi"))

    def _model_ile_taslak(self, cevap: Cevap, dogrudan: bool) -> None:
        mesaj = taslak_girdisi(cevap.soru, cevap.kaynaklar)
        sistem = TASLAK_ISTEMI
        if self.ogrenme is not None:
            # Örnek hafıza: doğrulanmış önceki cevaplar modele biçim gösterir (bilgi değil)
            for o in self.ogrenme.benzer_ornekler(cevap.soru, 2):
                sistem += f"\n\nÖRNEK (doğrulanmış önceki cevap; yalnızca biçim için):\nSORU: {o['soru']}\nCEVAP: {o['cikti']}"
        try:
            cikti = self.model.sohbet(
                [{"role": "system", "content": sistem}, {"role": "user", "content": mesaj}],
                max_tokens=900, json_mod=True)
        except Exception:
            cikti = ""
        veri = json_cikar(cikti)
        if not veri:
            if dogrudan:
                self._alintiya_dayali_taslak(cevap)
            return

        def oku(liste, tur: str) -> list[Cumle]:
            sonuc = []
            for o in liste or []:
                if isinstance(o, dict) and o.get("metin"):
                    sonuc.append(Cumle(str(o["metin"]).strip(), [str(x) for x in o.get("kaynaklar", [])], tur))
            return sonuc

        if veri.get("dogrudan_cevap") is False:
            cevap.acik_nokta = str(veri.get("acik_nokta") or "")
            cevap.dikkat = oku(veri.get("kisa_cevap"), "bilgi") + oku(veri.get("dikkat"), "bilgi")
            return
        cevap.kisa_cevap = oku(veri.get("kisa_cevap"), "bilgi")
        cevap.adimlar = oku(veri.get("adimlar"), "adim")
        cevap.dikkat = oku(veri.get("dikkat"), "bilgi")

    def _belgeleri_bul(self, cevap: Cevap) -> None:
        mevcut = {b.kod for b in cevap.belgeler}
        for k in cevap.kaynaklar:
            for m in _FORM_KODU.finditer(k.pasaj.metin):
                kod = f"TOGÜ.{m.group(1)}.{m.group(2)}"
                if kod in mevcut:
                    continue
                mevcut.add(kod)
                ref = BelgeRef(kod, kod)
                if self.depo is not None:
                    kayit = self.depo.bul(kod)
                    if kayit:
                        ref = BelgeRef(kod, kayit.get("ad") or kod, kayit.get("url", ""), kayit.get("dosya_yolu", ""))
                cevap.belgeler.append(ref)

    def _hukum_yok(self, cevap: Cevap, takip: bool = True) -> None:
        """Doğrudan hüküm yoksa: kesin olanlar + açık nokta + en yakın hüküm + somut yol + takip."""
        if not cevap.acik_nokta:
            cevap.acik_nokta = ("Sorunuzdaki durumu doğrudan düzenleyen bir hüküm, kütüphanede ve "
                                "taranan resmî kaynaklarda bulunamadı.")
        if cevap.kaynaklar and not cevap.dikkat:
            for k in cevap.kaynaklar[:3]:
                cevap.dikkat.append(Cumle(f"En yakın ilgili hüküm: {k.etiket}.", [k.kid], "bilgi"))
        birim = birim_oner(cevap.soru)
        cevap.somut_yol = [
            Cumle(f"Konu {birim} görev alanındadır; yazılı görüş istenmesi önerilir.", [], "yonlendirme"),
            Cumle("Yazı Hazırlama bölümünde bu soru için görüş talebi yazısı taslağı hazırlanabilir.", [], "yonlendirme"),
            Cumle("Soru takibe alındı; her saat başı güncellemede yeniden aranacak ve bulununca bildirilecek.",
                  [], "yonlendirme"),
        ]
        if takip:
            cevap.takip_id = self.kutuphane.takibe_al(cevap.soru)
