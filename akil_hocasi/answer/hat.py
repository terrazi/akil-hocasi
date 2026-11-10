"""Cevap hattı — çekirdeğin Danışma iş akışı (Yordam Kitabı: kabul → anlama → netleştirme → planlama → tarama →
bulma → seçme → analiz → yordama → çatışma → sentez → sınama → eleştirme → düzeltme → yeniden işleme → sunum →
kayıt). Arayüze yedi ilerleme adımı olarak yansır:

 1 Anla ve netleştir (işlem kartları ve doğrulanmış soru-cevap bankası dahil)
 2 Yerel kütüphanede tara (kelime + anlam araması, alt soru başına)
 3 Atıf zincirini izle
 4 Resmî kaynaklarda bul (canlı arama, yargı ve denetim kararları)
 5 Kanıtları seç ve analiz et
 6 Kuralı duruma uygula ve sentezle
 7 Sına, eleştir, düzelt (gerekirse yeniden işle)

Çıplak "bilmiyorum" yoktur: doğrudan hüküm bulunamazsa kesin olanlar, en yakın hüküm, somut yol ve takip verilir.
Tüm ayarlar strateji deposundan (izinli aralıkta) okunur; dersler yalnızca yöntem olarak kullanılır.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from typing import Protocol

from ..cekirdek.ilkeler import sistem_cekirdegi
from ..cekirdek.muhakeme import DusunceKaydi, SohbetBaglami, durumu_coz
from ..cekirdek.yordamlar import yordam as _yordam_tanimi
from ..core.maskeleme import metni_maskele
from ..core.turkce import katla
from ..library.db import Kutuphane, Pasaj, _terim_kok
from ..library.sozluk import birim_oner, genislet
from .dogrulama import DogrulamaMotoru
from .llm import BosModel, DilModeli, json_cikar
from .modeller import BelgeRef, Cevap, Cumle, Durum, Kaynak

IlerlemeFn = Callable[[int, int, str], None]
TOPLAM_ADIM = 7
_FORM_KODU = re.compile(r"\b(?:TOGÜ\.)?(FRM|YÖN|USE|PRS)\.(\d{3})\b")
_ZORLUK = {"kolay": 0, "orta": 1, "zor": 2}


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


def taslak_girdisi(soru: str, kaynaklar: list[Kaynak], cozumleme: dict | None = None) -> str:
    """Modele verilen girdi (eğitim verisinde de aynı biçim kullanılır)."""
    bloklar = []
    for k in kaynaklar:
        metin = k.pasaj.metin if len(k.pasaj.metin) <= 1500 else k.pasaj.metin[:1500] + " …"
        durum = "" if k.pasaj.yururlukte else " (ESKİ SÜRÜM)"
        bloklar.append(f"[{k.kid}] {k.etiket}{durum}\n{metin}")
    durum_metni = ""
    if cozumleme:
        olgular = "; ".join(cozumleme.get("olgular") or []) or "—"
        durum_metni = (f"DURUM: personel türü: {cozumleme.get('personel_turu', 'belirsiz')}; olay tarihi: "
                       f"{cozumleme.get('olay_tarihi') or 'belirtilmedi'}; olgular: {olgular}\n")
    return f"SORU: {soru}\n{durum_metni}\nKAYNAK PARÇALARI:\n\n" + "\n\n".join(bloklar)


def dogrulanmis_cikti(cevap: Cevap) -> str:
    """Doğrulama motorundan geçen cevabın model çıktısı biçimi (eğitim hedefi)."""
    def liste(cumleler):
        return [{"metin": c.metin, "kaynaklar": c.kaynaklar} for c in cumleler if c.tur != "yonlendirme"]
    return json.dumps({
        "dogrudan_cevap": cevap.durum != Durum.HUKUM_YOK, "kisa_cevap": liste(cevap.kisa_cevap),
        "uygulama": liste(cevap.uygulama), "adimlar": liste(cevap.adimlar), "dikkat": liste(cevap.dikkat),
        "degerlendirme": liste(cevap.degerlendirme), "guven": cevap.guven, "acik_nokta": cevap.acik_nokta,
    }, ensure_ascii=False)


# ============================================================================ şemalar ve görevler
def _cumle_listesi(en_cok: int) -> dict:
    return {"type": "array", "maxItems": en_cok, "items": {"type": "object", "properties": {
        "metin": {"type": "string"}, "kaynaklar": {"type": "array", "items": {"type": "string"}}},
        "required": ["metin", "kaynaklar"]}}


SENTEZ_SEMASI = {
    "type": "object",
    "properties": {
        "dogrudan_cevap": {"type": "boolean"},
        "kisa_cevap": _cumle_listesi(3), "uygulama": _cumle_listesi(6), "adimlar": _cumle_listesi(8),
        "dikkat": _cumle_listesi(5), "degerlendirme": _cumle_listesi(3),
        "guven": {"type": "string", "enum": ["kesin", "yoruma_acik", "hukum_yok"]},
        "acik_nokta": {"type": "string"},
    },
    "required": ["dogrudan_cevap", "kisa_cevap", "uygulama", "adimlar", "dikkat", "degerlendirme", "guven",
                 "acik_nokta"],
}

SENTEZ_GOREVI = (
    "Verilen durum ve kaynak parçalarıyla danışman cevabı hazırla. Bölümler: kisa_cevap (sonuç, en fazla 3 cümle); "
    "uygulama (kuralı duruma uygula: her cümlede bir şartı ya da istisnayı bu durumla karşılaştır, örn. 'Şart: … "
    "— Bu durumda: …'); adimlar (kim, neyi, hangi belge/formla yapacak; sıralı); dikkat (süre, istisna, risk); "
    "degerlendirme (kaynakta açıkça yazmayan çıkarım ve yorumların; yeni sayı, süre, madde yazma); guven; "
    "acik_nokta (cevaplanamayan kısım). Her bilgi cümlesinin kaynaklar alanına dayandığı kaynak kimliklerini yaz "
    "(K1, K2…). Alıntıyı harfi harfine ve çift tırnakla yap. dogrudan_cevap=false yalnızca kaynaklarda sorunun "
    "konusunu düzenleyen hiçbir hüküm yoksa yapılır: o zaman en yakın hükümleri dikkat bölümünde an ve acik_nokta'yı "
    "doldur. Eksik bilgi (personel türü, tarih, statü) hükmü ortadan kaldırmaz: dogrudan_cevap=true kalır, kisa_cevap'ı "
    "türe ya da duruma göre koşullu yaz ('657/4-A memuru ise …; 4/B ise …') ve eksik bilgiyi acik_nokta'ya yaz. "
    "dogrudan_cevap=true iken kisa_cevap boş bırakılmaz. Yalnızca istenen JSON'u döndür.")

ELESTIRI_SEMASI = {
    "type": "object",
    "properties": {
        "sorunlar": {"type": "array", "maxItems": 5, "items": {"type": "object", "properties": {
            "tur": {"type": "string", "enum": ["eksik_alt_soru", "atlanan_sart", "yanlis_varsayim", "asiri_kesinlik",
                                               "eksik_adim", "kaynak_eksik", "diger"]},
            "aciklama": {"type": "string"}, "arama_terimleri": {"type": "array", "items": {"type": "string"},
                                                                "maxItems": 5}},
            "required": ["tur", "aciklama"]}},
        "karar": {"type": "string", "enum": ["iyi", "duzeltilmeli"]},
    },
    "required": ["sorunlar", "karar"],
}

ELESTIRI_GOREVI = (
    "Bağımsız bir denetçi olarak aşağıdaki taslak cevabı, durum ve kaynaklarla karşılaştır. Şunları ara: "
    "cevaplanmayan alt soru, atlanan şart ya da istisna, yanlış varsayılan statü/tarih, kaynağın desteklemediği "
    "kesinlik, eksik ya da uygulanamaz adım, cevap için gerekli olup kaynaklarda bulunmayan hüküm (kaynak_eksik; "
    "arama terimlerini yaz). Yeni bilgi ekleme; yalnızca sorunları yaz. Sorun yoksa karar='iyi'.")

DUZELTME_GOREVI = (
    "Aşağıdaki taslağı, denetçinin bulduğu sorunlara ve sınamada çıkarılan cümlelere göre düzelt. Yalnızca sorunlu "
    "kısımları değiştir; kaynaklarda olmayan bilgi ekleme; çıkarılan cümlenin yerine kaynakta karşılığı olan bir "
    "cümle koy ya da onu hiç yazma. " + SENTEZ_GOREVI)


class CevapHatti:
    @property
    def sinanan_ders(self) -> int | None:
        """Gelişim döngüsünde geçici olarak etkin sayılan aday ders; yalnız sınavı yürüten iş parçacığında geçerli."""
        return getattr(self._yerel, "ders", None)

    @sinanan_ders.setter
    def sinanan_ders(self, deger: int | None) -> None:
        self._yerel.ders = deger

    def __init__(self, kutuphane: Kutuphane, dogrulama: DogrulamaMotoru,
                 model: DilModeli | None = None,
                 cevrimici: list[Saglayici] | None = None,
                 yargi: list[Saglayici] | None = None,
                 depo=None, cevrimici_mi: Callable[[], bool] = lambda: True,
                 ogrenme=None, siralayici=None, strateji=None, dersler=None, anlam=None):
        self.kutuphane = kutuphane
        self.dogrulama = dogrulama
        self.model = model or BosModel()
        self.cevrimici = cevrimici or []
        self.yargi = yargi or []
        self.depo = depo
        self.cevrimici_mi = cevrimici_mi
        self.ogrenme = ogrenme          # öğrenilmiş terimler, kaynak puanları, örnek hafıza
        self.siralayici = siralayici    # her gece kendini eğiten sıralayıcı
        self.strateji = strateji        # yordam ayarları (çekirdek strateji deposu)
        self.dersler = dersler          # ders hafızası
        self.anlam = anlam              # anlam dizini (vektör araması)
        self._yerel = threading.local()          # gelişim sınavına özel durum (kullanıcı soruları etkilenmez)

    # ------------------------------------------------------------------ ayar ve ders erişimi
    def ayar(self, yordam: str, ad: str):
        if self.strateji is not None:
            return self.strateji.deger(yordam, ad)
        return next(a.varsayilan for a in _yordam_tanimi(yordam).ayarlar if a.ad == ad)

    def _dersler(self, istek: str, yordamlar: tuple[str, ...]) -> list[str]:
        if self.dersler is None:
            return []
        try:
            return self.dersler.ilgili(istek, yordamlar, n=int(self.ayar("ders", "ders_siniri")),
                                       ek_kimlik=self.sinanan_ders)
        except Exception:  # noqa: BLE001 - ders hafızası okunamazsa ders kullanılmaz
            return []

    def _model_cagir(self, sistem: str, kullanici: str, sema: dict, max_tokens: int, sicaklik: float,
                     dusunme: bool = False) -> dict | None:
        mesajlar = [{"role": "system", "content": sistem}, {"role": "user", "content": kullanici}]
        try:
            try:
                cikti = self.model.sohbet(mesajlar, max_tokens=max_tokens, sicaklik=sicaklik, json_mod=True,
                                          json_sema=sema, dusunme=dusunme)
            except TypeError:                     # sade arayüzlü modeller
                cikti = self.model.sohbet(mesajlar, max_tokens=max_tokens, sicaklik=sicaklik, json_mod=True)
        except Exception:  # noqa: BLE001 - model hatasında kural tabanlı yola düşülür
            return None
        return json_cikar(cikti)

    # ------------------------------------------------------------------ ana giriş
    def cevapla(self, soru: str, mod: str = "derin", ilerleme: IlerlemeFn | None = None,
                kayit: bool = True, baglam: SohbetBaglami | None = None) -> Cevap:
        """kayit=False: öz değerlendirme gibi iç kullanımlarda olay ve takip kaydı yapılmaz."""
        bas = time.time()
        istek = metni_maskele(soru)                                  # KABUL: kişisel veri maskelenir
        cevap = Cevap(soru=istek, mod=mod, model_kullanildi=self.model.hazir)
        dk = DusunceKaydi()
        bildir = ilerleme or (lambda a, t, m: None)

        def adim(no: int, mesaj: str) -> None:
            cevap.ilerleme.append(f"{no}/{TOPLAM_ADIM} · {mesaj}")
            bildir(no, TOPLAM_ADIM, mesaj)

        # 1) ANLAMA + NETLEŞTİRME (+ kart ve banka)
        adim(1, "Soru çözümleniyor (durum, statü, alt sorular)")
        dersler = self._dersler(istek, ("anlama", "netlestirme", "sentez", "yordama", "elestirme"))
        cevap.kullanilan_dersler = dersler
        coz = durumu_coz(istek, self.model, baglam, [d for d in dersler][:3])
        cevap.cozumleme = coz.sozluk()
        dk.ekle("anla", f"Konu: {coz.konu[:80]}", f"statü: {coz.personel_turu}; zorluk: {coz.zorluk}"
                + (f"; tarih: {coz.olay_tarihi}" if coz.olay_tarihi else ""))
        sinir = int(self.ayar("netlestirme", "soru_siniri"))
        cevap.netlestirme = [e.soru for e in coz.eksik][:sinir]
        if cevap.netlestirme:
            dk.ekle("netlestir", "Cevabı değiştiren eksik bilgi var", "; ".join(e.bilgi for e in coz.eksik[:sinir]))
        alt_sorular = [s for s in coz.alt_sorular if s][: int(self.ayar("anlama", "alt_soru_siniri"))] or [istek]
        dk.ekle("planla", f"{len(alt_sorular)} alt soru", " | ".join(a[:60] for a in alt_sorular))

        havuz: dict[int, Pasaj] = {}
        adimlar_karttan: list[Cumle] = []
        self._kart_ve_banka(istek, havuz, adimlar_karttan, cevap)

        # 2) TARAMA
        adim(2, "Yerel kütüphanede taranıyor (kelime ve anlam)")
        ek = genislet(istek) + list(coz.terimler)
        if self.ogrenme is not None:
            ek += self.ogrenme.ogrenilmis_terimler(istek)
        n_aday = int(self.ayar("tarama", "aday_sayisi"))
        for alt in [istek] + [a for a in alt_sorular if a != istek]:
            self._tara(alt, ek, havuz, n_aday)
        dk.ekle("arastir", f"Taramada {len(havuz)} aday hüküm")

        yeterli = self._dogrudan_mi(istek, havuz)
        if mod == "hizli" and not yeterli:
            mod = cevap.mod = "derin"   # kendiliğinden derin araştırmaya geç
        derin = mod == "derin" or not yeterli

        # 3) ATIF ZİNCİRİ
        derinlik = int(self.ayar("tarama", "atif_derinligi"))
        if derin and derinlik > 0:
            adim(3, "Atıf zinciri izleniyor")
            for p in sorted(havuz.values(), key=lambda x: -x.skor)[:3]:
                for q in self.kutuphane.atif_zinciri(p):
                    q.skor = p.skor * 0.6
                    havuz.setdefault(q.madde_id, q)
        else:
            adim(3, "Atıf zinciri gerekmedi")

        # 4) BULMA
        if derin and bool(self.ayar("bulma", "canli_arama")) and (self.cevrimici or self.yargi) and self.cevrimici_mi():
            adim(4, "Resmî kaynaklarda canlı arama yapılıyor")
            terimler = list(coz.terimler)
            eklenen = self._saglayicilari_calistir(self.cevrimici + self.yargi, istek, terimler)
            if eklenen:
                for alt in [istek] + alt_sorular[1:]:
                    self._tara(alt, ek, havuz, n_aday)
            dk.ekle("arastir", f"Canlı arama: {eklenen} yeni belge")
        else:
            cevap.cevrimdisi = derin and not self.cevrimici_mi()
            adim(4, "Canlı arama atlandı" + (" (çevrimdışı)" if cevap.cevrimdisi else " (gerekmedi)"))

        # 5) SEÇME + ANALİZ
        adim(5, "Kanıtlar seçiliyor ve çözümleniyor")
        self._sec(istek, havuz, cevap)
        dk.ekle("arastir", f"{len(cevap.kaynaklar)} kaynak seçildi",
                ", ".join(k.etiket for k in cevap.kaynaklar[:4]))
        dogrudan = self._dogrudan_mi(istek, havuz)

        # 6) YORDAMA + SENTEZ
        adim(6, "Kural duruma uygulanıyor ve cevap yazılıyor")
        if cevap.kaynaklar and self.model.hazir:
            self._model_ile_sentez(cevap, dogrudan, coz.zorluk, dersler)
            dk.ekle("uygula", "Model taslağı hazırladı",
                    f"{len(cevap.kisa_cevap)} sonuç, {len(cevap.uygulama)} gerekçe cümlesi")
        elif cevap.kaynaklar and dogrudan:
            self._alintiya_dayali_taslak(cevap)
            dk.ekle("uygula", "Alıntıya dayalı taslak (dil modeli yok)")
        cevap.adimlar = cevap.adimlar or adimlar_karttan
        self._belgeleri_bul(cevap)

        # 7) SINAMA → ELEŞTİRME → DÜZELTME → YENİDEN İŞLEME
        adim(7, "Sınanıyor, eleştiriliyor ve düzeltiliyor")
        secilen = list(cevap.kaynaklar)                 # sınama kullanılmayanları ayıklar; düzeltme hepsini görmeli
        self.dogrulama.dogrula(cevap)
        cikan = cevap.denetim.get("cikarilanlar", [])
        dk.ekle("denetle", f"Sınama: {cevap.durum.value}",
                f"{len(cikan)} cümle çıkarıldı" if cikan else "tüm cümleler geçti")
        if self.model.hazir and cevap.kaynaklar and mod == "derin":
            self._elestir_duzelt(cevap, coz, dersler, dk, ek, havuz, n_aday, secilen)
        if cevap.durum == Durum.HUKUM_YOK and dogrudan and self.model.hazir and secilen:
            # Model doğrudan hükmü kaçırdı ya da cümleleri sınamadan geçemedi: soruyu doğrudan karşılayan
            # madde varken "hüküm yok" denmez; alıntıya dayalı cevaba dönülür ve yeniden sınanır.
            cevap.kaynaklar = list(secilen)
            cevap.kisa_cevap, cevap.uygulama, cevap.adimlar, cevap.dikkat = [], [], [], []
            cevap.degerlendirme, cevap.guven, cevap.acik_nokta = [], "", ""
            self._alintiya_dayali_taslak(cevap)
            cevap.adimlar = adimlar_karttan
            self.dogrulama.dogrula(cevap)
            cevap.denetim["alintiya_donus"] = True       # model sınavlarında modelin kendi başarısı sayılmaz
            dk.ekle("denetle", "Model doğrudan hükmü karşılayamadı", "alıntıya dayalı cevaba dönüldü ve yeniden sınandı")

        if cevap.durum == Durum.HUKUM_YOK:
            self._hukum_yok(cevap, takip=kayit)
            dk.ekle("sun", "Doğrudan hüküm yok", "kesin olanlar, en yakın hüküm, somut yol ve takip verildi")
        else:
            dk.ekle("sun", f"Sonuç: {cevap.durum.value}", f"güven: {cevap.guven}")
        cevap.dusunce = dk.satirlar()
        cevap.sure_sn = round(time.time() - bas, 2)
        if kayit and self.dersler is not None and cevap.denetim.get("cikarilanlar"):
            try:                                               # ders çıkarma yordamının girdisi (gece işlenir)
                self.dersler.hata_kaydet(istek, [f"[{c['test']}] {c['metin'][:160]} — {c['neden'][:120]}"
                                                 for c in cevap.denetim["cikarilanlar"]])
            except Exception:  # noqa: BLE001
                pass
        if kayit and self.ogrenme is not None:
            try:
                cevap.olay_id = self.ogrenme.olay_kaydet(
                    cevap, taslak_girdisi(cevap.soru, cevap.kaynaklar, cevap.cozumleme), dogrulanmis_cikti(cevap))
            except Exception:  # noqa: BLE001 - kayıt hatası cevabı engellemez
                pass
        return cevap

    # ------------------------------------------------------------------ yordam yardımcıları
    def _kart_ve_banka(self, istek: str, havuz: dict[int, Pasaj], adimlar_karttan: list[Cumle], cevap: Cevap) -> None:
        kart_dayanak: list[str] = []
        for kart in self.kutuphane.kart_ara(istek):
            icerik = json.loads(kart["icerik"])
            kart_dayanak.extend(json.loads(kart["dayanak"]))
            for a in icerik.get("adimlar", []):
                adimlar_karttan.append(Cumle(a.get("metin", ""), a.get("kaynaklar", []), "adim"))
            for f in icerik.get("formlar", []):
                cevap.belgeler.append(BelgeRef(f.get("kod", ""), f.get("ad", ""), f.get("url", "")))
        for sc in self.kutuphane.soru_cevap_ara(istek):
            if sc and sc["durum"] == "dogrulandi":
                kart_dayanak.extend(json.loads(sc["dayanak"]))
        for ref in kart_dayanak:
            if "/" in ref:
                kimlik, no = ref.rsplit("/", 1)
                p = self.kutuphane.madde_getir(kimlik, no)
                if p:
                    p.skor = max(p.skor, 50.0)
                    havuz[p.madde_id] = p

    def _tara(self, sorgu: str, ek: list[str], havuz: dict[int, Pasaj], n_aday: int) -> None:
        kelime = self.kutuphane.ara(sorgu, limit=max(4, n_aday // 2 + 2), ek_terimler=ek)
        for p in kelime:
            havuz.setdefault(p.madde_id, p)
        if self.anlam is None:
            return
        try:
            agirlik = float(self.ayar("tarama", "anlam_agirligi"))
            k = max(0, round(n_aday * agirlik))
            if not k:
                return
            taban = max((p.skor for p in kelime), default=5.0)
            for madde_id, benzerlik in self.anlam.ara(sorgu, k):
                if madde_id in havuz:
                    havuz[madde_id].anlam = max(havuz[madde_id].anlam, benzerlik)
                    continue
                p = self.kutuphane.pasaj_getir(madde_id, taban * benzerlik)
                if p and p.yururlukte:
                    p.anlam = benzerlik
                    havuz[madde_id] = p
        except Exception:  # noqa: BLE001 - anlam araması yoksa kelime araması yeter
            return

    def _sec(self, istek: str, havuz: dict[int, Pasaj], cevap: Cevap) -> None:
        if self.siralayici is not None and self.siralayici.aktif:
            self.siralayici.uygula(istek, list(havuz.values()))
        elif self.ogrenme is not None:
            self.ogrenme.siralamayi_ayarla(list(havuz.values()))
        for p in havuz.values():                                # anlam yakınlığı küçük bir katkı verir
            if p.anlam:
                p.skor += p.anlam * 2.0
        n = int(self.ayar("secme", "sunulacak_kaynak"))
        pasajlar = sorted(havuz.values(), key=lambda x: (x.belge_turu in ("emsal", "ipucu"), -x.skor))[:n]
        cevap.kaynaklar = [Kaynak(f"K{i}", p) for i, p in enumerate(pasajlar, 1)]

    def _dogrudan_mi(self, soru: str, havuz: dict[int, Pasaj]) -> bool:
        if not havuz:
            return False
        en_iyi = max(havuz.values(), key=lambda p: p.skor)
        if en_iyi.skor >= 50:   # onaylı kart / soru-cevap dayanağı
            return True
        kapsama = max(_kapsama(soru, p.baslik + " " + p.metin) for p in havuz.values())
        return kapsama >= 0.6 or max((p.anlam for p in havuz.values()), default=0.0) >= 0.75

    def _saglayicilari_calistir(self, saglayicilar: list[Saglayici], soru: str, terimler: list[str]) -> int:
        toplam = 0
        for s in saglayicilar:
            try:
                toplam += s.ara(soru, terimler)
            except Exception:  # noqa: BLE001 - bir sağlayıcının hatası diğerlerini durdurmaz
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

    def _sentez_sistemi(self, gorev: str, dersler: list[str]) -> str:
        sistem = sistem_cekirdegi(gorev)
        if dersler:
            sistem += "\n\nGEÇMİŞ DERSLER (yöntem; kaynakların yerine geçmez):\n" + "\n".join(f"- {d}" for d in dersler)
        return sistem

    def _taslagi_uygula(self, cevap: Cevap, veri: dict) -> None:
        def oku(liste, tur: str) -> list[Cumle]:
            sonuc = []
            for o in liste or []:
                if isinstance(o, dict) and o.get("metin"):
                    sonuc.append(Cumle(str(o["metin"]).strip(), [str(x) for x in o.get("kaynaklar", [])], tur))
            return sonuc

        cevap.guven = str(veri.get("guven") or "")
        cevap.degerlendirme = oku(veri.get("degerlendirme"), "degerlendirme")
        if veri.get("dogrudan_cevap") is False:
            cevap.acik_nokta = str(veri.get("acik_nokta") or "")
            cevap.kisa_cevap, cevap.uygulama, cevap.adimlar = [], [], []
            cevap.dikkat = oku(veri.get("kisa_cevap"), "bilgi") + oku(veri.get("dikkat"), "bilgi")
            return
        cevap.kisa_cevap = oku(veri.get("kisa_cevap"), "bilgi")
        cevap.uygulama = oku(veri.get("uygulama"), "bilgi")
        cevap.adimlar = oku(veri.get("adimlar"), "adim")
        cevap.dikkat = oku(veri.get("dikkat"), "bilgi")
        cevap.acik_nokta = str(veri.get("acik_nokta") or "")

    def _model_ile_sentez(self, cevap: Cevap, dogrudan: bool, zorluk: str, dersler: list[str]) -> None:
        sistem = self._sentez_sistemi(SENTEZ_GOREVI, dersler)
        n_ornek = int(self.ayar("sentez", "ornek_sayisi"))
        if self.ogrenme is not None and n_ornek:
            for o in self.ogrenme.benzer_ornekler(cevap.soru, n_ornek):
                sistem += f"\n\nÖRNEK (doğrulanmış önceki cevap; yalnızca biçim için):\nSORU: {o['soru']}\nCEVAP: {o['cikti']}"
        dusun = bool(self.ayar("yordama", "dusunme_kipi")) and zorluk == "zor"
        veri = self._model_cagir(sistem, taslak_girdisi(cevap.soru, cevap.kaynaklar, cevap.cozumleme),
                                 SENTEZ_SEMASI, 1400, float(self.ayar("sentez", "sicaklik")), dusunme=dusun)
        if not veri:
            if dogrudan:
                self._alintiya_dayali_taslak(cevap)
            return
        self._taslagi_uygula(cevap, veri)

    def _elestir_duzelt(self, cevap: Cevap, coz, dersler: list[str], dk: DusunceKaydi, ek: list[str],
                        havuz: dict[int, Pasaj], n_aday: int, secilen: list[Kaynak]) -> None:
        esik = _ZORLUK.get(str(self.ayar("elestirme", "elestiri_esigi")), 1)
        cikan = cevap.denetim.get("cikarilanlar", [])
        if _ZORLUK.get(coz.zorluk, 1) < esik and not cikan:
            return
        taslak = dogrulanmis_cikti(cevap)
        sinanmis = list(cevap.kaynaklar)
        cevap.kaynaklar = list(secilen)
        elestiri = self._model_cagir(
            sistem_cekirdegi(ELESTIRI_GOREVI),
            taslak_girdisi(cevap.soru, cevap.kaynaklar, cevap.cozumleme) + f"\n\nTASLAK:\n{taslak}"
            + ("\n\nSINAMADA ÇIKARILANLAR:\n" + "\n".join(f"- {c['metin'][:160]} ({c['neden'][:100]})" for c in cikan)
               if cikan else ""),
            ELESTIRI_SEMASI, 600, 0.1) or {}
        sorunlar = [s for s in elestiri.get("sorunlar", []) if isinstance(s, dict) and s.get("aciklama")]
        dk.ekle("denetle", "Öz eleştiri", f"{len(sorunlar)} sorun" if sorunlar else "sorun bulunmadı")
        if not sorunlar and not cikan:
            cevap.kaynaklar = sinanmis
            return

        # YENİDEN İŞLEME: kaynak eksikse eksik noktaya odaklı ek tarama (bir kez)
        eksik_terimler = [t for s in sorunlar if s.get("tur") == "kaynak_eksik" for t in s.get("arama_terimleri", [])]
        if eksik_terimler and bool(self.ayar("yeniden_isleme", "acik")):
            once = len(havuz)
            for t in eksik_terimler[:4]:
                self._tara(t, ek + eksik_terimler, havuz, n_aday)
            if len(havuz) > once:
                eski_kaynaklar = list(cevap.kaynaklar)
                self._sec(cevap.soru, havuz, cevap)
                secilen = list(cevap.kaynaklar)
                dk.ekle("arastir", "Yeniden işleme", f"{len(havuz) - once} yeni aday; kaynaklar güncellendi")
                if [k.pasaj.madde_id for k in cevap.kaynaklar] != [k.pasaj.madde_id for k in eski_kaynaklar]:
                    taslak = "{}"                    # kaynak kimlikleri değişti: taslak yeniden kurulur

        # DÜZELTME: en fazla tur_siniri tur; daha kötüyse önceki korunur
        cevap.kaynaklar = sinanmis
        for _ in range(int(self.ayar("duzeltme", "tur_siniri"))):
            onceki = (list(cevap.kisa_cevap), list(cevap.uygulama), list(cevap.adimlar), list(cevap.dikkat),
                      list(cevap.degerlendirme), cevap.guven, cevap.acik_nokta, cevap.durum, list(cevap.uyarilar),
                      dict(cevap.denetim), list(sinanmis))
            cevap.kaynaklar = list(secilen)
            puan_once = self._taslak_puani(cevap)
            veri = self._model_cagir(
                self._sentez_sistemi(DUZELTME_GOREVI, dersler),
                taslak_girdisi(cevap.soru, cevap.kaynaklar, cevap.cozumleme) + f"\n\nÖNCEKİ TASLAK:\n{taslak}"
                + "\n\nDENETÇİ SORUNLARI:\n" + "\n".join(f"- [{s.get('tur')}] {s['aciklama'][:220]}" for s in sorunlar)
                + ("\n\nSINAMADA ÇIKARILANLAR:\n" + "\n".join(f"- {c['metin'][:160]} → {c['neden'][:100]}"
                                                             for c in cikan) if cikan else ""),
                SENTEZ_SEMASI, 1400, float(self.ayar("sentez", "sicaklik")))
            if not veri:
                break
            cevap.uyarilar = [u for u in cevap.uyarilar if u.test in ("Hiyerarşi",)]
            self._taslagi_uygula(cevap, veri)
            self._belgeleri_bul(cevap)
            self.dogrulama.dogrula(cevap)
            if self._taslak_puani(cevap) < puan_once:
                (cevap.kisa_cevap, cevap.uygulama, cevap.adimlar, cevap.dikkat, cevap.degerlendirme, cevap.guven,
                 cevap.acik_nokta, cevap.durum, cevap.uyarilar, cevap.denetim, cevap.kaynaklar) = onceki
                dk.ekle("denetle", "Düzeltme önceki taslaktan kötü; önceki korundu")
                break
            dk.ekle("denetle", "Düzeltildi", f"durum: {cevap.durum.value}")
            sinanmis = list(cevap.kaynaklar)
            cikan = cevap.denetim.get("cikarilanlar", [])
            if not cikan:
                break
            taslak = dogrulanmis_cikti(cevap)

    @staticmethod
    def _taslak_puani(cevap: Cevap) -> float:
        sira = {Durum.DOGRULANDI: 3, Durum.CELISKILI: 2, Durum.HUKUM_YOK: 1}
        cikan = len(cevap.denetim.get("cikarilanlar", []))
        return sira.get(cevap.durum, 0) * 10 + len(cevap.kisa_cevap) + len(cevap.uygulama) * 0.5 - cikan

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
        cevap.guven = "hukum_yok"
        if takip:
            cevap.takip_id = self.kutuphane.takibe_al(cevap.soru)
