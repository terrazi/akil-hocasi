"""Resmî yazı hazırlayıcı: çekirdeğin "yazi" iş akışı.

ANLA (gelen yazı, talimat, yazı türü, muhatap ve makam) → NETLEŞTİR (eksik bilgi: yer tutucu ve soru) →
ARAŞTIR (danışma hattı: doğrulanmış dayanak) → YAZ (dil modeli; yoksa şablon) → SINA (her tarih, sayı ve atıf
kaynakta olmalı; olmayan cümle çıkarılır) → ELEŞTİR/DÜZELT (bir tur yeniden yazım, kötüleşirse geri alınır) →
BİÇİM (Yönetmelik kuralları kendiliğinden) → SUN (taslak, EBYS metni, kontrol listesi, Nasıl düşündüm).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from ..cekirdek.ilkeler import sistem_cekirdegi
from ..cekirdek.muhakeme import DusunceKaydi
from ..core.maskeleme import metni_maskele
from ..core.turkce import tr_lower
from .dil import _uyum2, konu_bicimi, son_unlu, yalin
from .gelen import GelenYazi, cevap_muhatabi, cumleler
from .kontrol import KontrolSonucu, duzelt, kontrol_et, sinama
from .kurallar import bitis_ifadesi, makam_tahmini
from .model import YAZI_TURLERI, Ilgi, Iletisim, Imza, Paragraf, Yazi

YAZI_GOREVI = (
    "Resmî yazının METİN bölümünü yazıyorsun (başlık, sayı, konu, muhatap, ilgi, imza program tarafından eklenir).\n"
    "KURALLAR:\n"
    "1) Yalnızca GELEN YAZI, TALİMAT ve DOĞRULANMIŞ DAYANAK'taki bilgileri kullan. Bunlarda olmayan tarih, sayı, "
    "tutar, süre, kanun ya da madde numarası, kişi adı YAZMA.\n"
    "2) Birimin bilmesi gereken ama sana verilmeyen bilgi için köşeli parantezli yer tutucu yaz: [personel sayısı], "
    "[ödeme tarihi]. Yer tutucuları eksik_bilgiler listesine de yaz.\n"
    "3) Resmî yazı dili: kısa, açık, nesnel; kurum kendinden '{kendi}' diye söz eder (ör. '{kendi}ca', "
    "'{kendi}a'); edilgen ve geniş zaman; sohbet dili, abartı, duygu ve gereksiz yabancı sözcük yok.\n"
    "4) İlk paragraf ilgi yazıya ya da konuya atıfla başlar ('İlgi yazı ile …', birden çok ilgi varsa "
    "'İlgi (a) yazı ile …').\n"
    "5) Mevzuat hükmü aktarırken o cümlenin kaynaklar alanına dayanağın kimliğini (K1, K2…) yaz; hükmü değiştirme, "
    "kaynakta olmayan sonuç çıkarma.\n"
    "6) Bitiş cümlesini (arz ederim / rica ederim / Saygılarımla) YAZMA; program muhatabın makamına göre ekler.\n"
    "7) Kısaltmayı ilk geçtiği yerde açık yaz, kısaltmayı parantez içinde ver.\n"
    "8) 2–5 paragraf; her paragraf 1–4 cümle; paragraflar arasında boş satır yok.\n"
    "9) Sayı, tarih, e-imza, doğrulama kodu ÜRETME; bunları EBYS verir.")

YAZI_SEMASI = {
    "type": "object",
    "properties": {
        "konu": {"type": "string"},
        "paragraflar": {"type": "array", "items": {"type": "object", "properties": {
            "metin": {"type": "string"}, "kaynaklar": {"type": "array", "items": {"type": "string"}}},
            "required": ["metin", "kaynaklar"]}},
        "eksik_bilgiler": {"type": "array", "items": {"type": "string"}},
        "ekler": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["konu", "paragraflar", "eksik_bilgiler", "ekler"],
}

DUZELTME_GOREVI = (
    "Aşağıdaki resmî yazı metninden sınamada bazı cümleler çıkarıldı; çünkü içerdikleri tarih, sayı ya da atıf "
    "kaynaklarda yok. Metni bu bilgileri UYDURMADAN yeniden yaz: gerekiyorsa köşeli parantezli yer tutucu kullan. "
    "Diğer kurallar aynıdır.\n\n" + YAZI_GOREVI)


@dataclass
class YaziIstegi:
    tur: str = "cevap"
    talimat: str = ""                        # "ne yazılsın": birimin cevabı, istenen husus, görüş
    gelen: GelenYazi | None = None
    muhatap: str = ""
    muhatap_birim: str = ""
    makam: str = ""                          # boşsa tahmin edilir
    kisiye: bool = False
    dagitimli: bool = False
    gereği: list[str] = field(default_factory=list)
    bilgi: list[str] = field(default_factory=list)
    ekler: list[str] = field(default_factory=list)
    ilgiler: list[Ilgi] = field(default_factory=list)
    ivedilik: str = ""
    cevap_suresi: str = ""
    olur: Imza | None = None
    profil: dict = field(default_factory=dict)
    dayanak_cevabi: object | None = None     # danışmadan gelen doğrulanmış Cevap ("Yazıya dönüştür")
    arastir: bool = True


@dataclass
class YaziSonucu:
    yazi: Yazi
    kontrol: list[KontrolSonucu] = field(default_factory=list)
    dusunce: list[str] = field(default_factory=list)
    duzeltmeler: list[str] = field(default_factory=list)
    cikarilanlar: list[dict] = field(default_factory=list)
    kaynak_metinler: list[str] = field(default_factory=list)
    dayanak_cevabi: object | None = None
    model_kullanildi: bool = False
    sure_sn: float = 0.0

    @property
    def hata_sayisi(self) -> int:
        return sum(1 for k in self.kontrol if k.durum == "hata")


def kendi_adi(birim: str) -> str:
    """Kurumun kendinden söz edişi: 'Personel Daire Başkanlığı' → 'Başkanlığımız', 'Ziraat Fakültesi' → 'Fakültemiz'."""
    son = (yalin(birim).split() or ["Birimimiz"])[-1]
    k = tr_lower(son)
    if k.endswith(("sı", "si", "su", "sü")) and len(k) > 4:
        kok = son[:-2]
    elif k[-1:] in "ıiuü" and len(k) > 3:
        kok = son[:-1]
    else:
        kok = son
    kk = tr_lower(kok)
    u = son_unlu(kk)
    v = "ı" if u in "aı" else "i" if u in "ei" else "u" if u in "ou" else "ü"
    ek = ("m" + v + "z") if kk[-1:] in "aeıioöuü" else (v + "m" + v + "z")
    if kk.endswith("k") and sum(1 for c in kk if c in "aeıioöuü") >= 2:
        kok = kok[:-1] + "ğ"                       # Sekreterlik → Sekreterliğimiz
    return kok[:1].upper() + kok[1:] + ek


def profil_uygula(y: Yazi, profil: dict) -> None:
    idare = profil.get("idare", "").strip()
    birim = profil.get("birim", "").strip()
    y.baslik = ["T.C."] + ([idare] if idare else []) + ([birim] if birim else [])
    y.imza = Imza(profil.get("imza_ad", ""), profil.get("imza_soyad", ""), profil.get("imza_unvan", ""),
                  profil.get("imza_on_unvan", ""), profil.get("yetki", ""))
    y.iletisim = Iletisim(**{k: profil.get(k, "") for k in Iletisim.__dataclass_fields__})
    y.yazi_tipi = profil.get("yazi_tipi", "Times New Roman") or "Times New Roman"
    y.dosya_kodu = profil.get("dosya_kodu", "")
    y.logo = bool(profil.get("logo", False))


class YaziHazirlayici:
    def __init__(self, hat, dersler=None):
        self.hat = hat
        self.dersler = dersler

    @property
    def model(self):
        return self.hat.model

    # ------------------------------------------------------------------ ana akış
    def hazirla(self, ist: YaziIstegi, ilerleme=None) -> YaziSonucu:
        bas = time.time()
        dk = DusunceKaydi()

        def adim(n: int, mesaj: str) -> None:
            if ilerleme:
                ilerleme(n, 6, mesaj)

        # 1) ANLA
        adim(1, "Gelen yazı ve talimat çözümleniyor")
        y = Yazi(tur=ist.tur if ist.tur in YAZI_TURLERI else "cevap")
        profil_uygula(y, ist.profil)
        g = ist.gelen
        kendi_idare = ist.profil.get("idare", "")
        if ist.muhatap.strip():
            y.muhatap, y.muhatap_birim = ist.muhatap.strip(), ist.muhatap_birim.strip()
        elif g and (g.idare or g.birim):
            y.muhatap, y.muhatap_birim = cevap_muhatabi(g, kendi_idare)
        y.kisiye, y.dagitimli = ist.kisiye, ist.dagitimli
        if ist.dagitimli and not ist.muhatap.strip():
            y.muhatap = ""
        y.makam, emin = (ist.makam, True) if ist.makam else makam_tahmini(y.muhatap, y.kisiye, y.dagitimli)
        y.konu = konu_bicimi(g.konu) if g and g.konu else ""
        if g and (g.tarih or g.sayi):
            ayni = bool(g.idare and kendi_idare and tr_lower(g.idare) == tr_lower(kendi_idare))
            gonderen = (g.birim if ayni else g.idare) or g.birim
            y.ilgiler.append(Ilgi(tarih=g.tarih, sayi=g.sayi,
                                  idare="" if y.muhatap and gonderen and tr_lower(yalin(gonderen)) == tr_lower(yalin(y.muhatap))
                                  else gonderen))
        y.ilgiler += ist.ilgiler
        y.istenenler = list(g.istenenler) if g else []
        y.ekler = list(ist.ekler)
        y.gereği, y.bilgi = list(ist.gereği), list(ist.bilgi)
        y.ivedilik, y.cevap_suresi, y.olur = ist.ivedilik, ist.cevap_suresi, ist.olur
        talimat = metni_maskele(ist.talimat.strip())
        dk.ekle("anla", f"Yazı türü: {YAZI_TURLERI[y.tur]['ad']}",
                f"muhatap: {y.muhatap or ('DAĞITIM YERLERİNE' if y.dagitimli else '—')}; makam: {y.makam}"
                + ("" if emin else " (tahmin; doğrulayın)"))
        if g:
            dk.ekle("anla", "Gelen yazı çözümlendi", g.ozet().replace("\n", "; ")[:300])

        # 2) NETLEŞTİR
        adim(2, "Eksik bilgiler belirleniyor")
        if not y.muhatap and not y.dagitimli:
            y.eksikler.append("Muhatap (yazının gideceği makam)")
        if not (y.imza.ad and y.imza.soyad and y.imza.unvan):
            y.eksikler.append("İmza sahibi (Ayarlar > Birim profili)")
        if not emin:
            y.eksikler.append("Muhatabın makamı (üst / aynı düzey / alt): bitiş ifadesini belirler")
        if g and g.istenenler and not talimat:
            y.eksikler.append("İstenen hususlara birimin cevabı (talimat alanı boş; metinde yer tutucu bırakıldı)")
        if g and g.sure:
            dk.ekle("netlestir", "Cevap süresi", g.sure)

        # 3) ARAŞTIR: dayanak (danışma hattı, doğrulanmış)
        adim(3, "Dayanak araştırılıyor")
        cevap = ist.dayanak_cevabi
        sorgu = " ".join(x for x in (talimat, g.konu if g else "", (g.istenenler[0] if g and g.istenenler else "")) if x)
        if cevap is None and ist.arastir and sorgu and y.tur in ("cevap", "gorus", "talep", "olur", "bilgi_isteme"):
            try:
                cevap = self.hat.cevapla(sorgu[:600], "derin", kayit=False)
            except Exception as e:  # noqa: BLE001 - dayanaksız da yazı hazırlanabilir (şablon + yer tutucu)
                dk.ekle("arastir", "Dayanak araştırması yapılamadı", str(e)[:120])
                cevap = None
        dayanak = self._dayanak(cevap)
        y.dayanaklar = dayanak["kaynaklar"]
        kaynak_metinler = [x for x in ((g.metin if g else ""), talimat, ist.cevap_suresi) if x]
        kaynak_metinler += dayanak["metinler"]
        dk.ekle("arastir", f"{len(dayanak['kaynaklar'])} doğrulanmış dayanak",
                ", ".join(k["etiket"] for k in dayanak["kaynaklar"][:4]) or "dayanak bulunamadı")

        # 4) YAZ
        adim(4, "Metin yazılıyor")
        ders_listesi = self._dersler(sorgu or y.konu)
        sonuc = YaziSonucu(yazi=y, kaynak_metinler=kaynak_metinler, dayanak_cevabi=cevap)
        veri = self._model_ile_yaz(y, g, talimat, dayanak, ders_listesi) if self.model.hazir else None
        if veri:
            sonuc.model_kullanildi = True
            self._veriyi_uygula(y, veri)
            dk.ekle("uygula", "Dil modeli metni yazdı", f"{len(y.paragraflar)} paragraf")
        else:
            self._sablonla_yaz(y, g, talimat, dayanak)
            dk.ekle("uygula", "Şablonla yazıldı" + ("" if self.model.hazir else " (dil modeli yok)"),
                    f"{len(y.paragraflar)} paragraf; birimin dolduracağı yerler köşeli parantezle işaretli")

        # 5) SINA → DÜZELT
        adim(5, "Sınanıyor ve düzeltiliyor")
        cikarilan = self._sina_ve_ayikla(y, kaynak_metinler)
        if cikarilan and sonuc.model_kullanildi:
            onceki = [Paragraf(p.metin, list(p.kaynaklar), p.tur) for p in y.paragraflar]
            veri2 = self._model_ile_yaz(y, g, talimat, dayanak, ders_listesi, cikarilan)
            if veri2:
                yedek_konu = y.konu
                self._veriyi_uygula(y, veri2)
                cikarilan2 = self._sina_ve_ayikla(y, kaynak_metinler)
                if len(cikarilan2) > len(cikarilan) or not y.paragraflar:
                    y.paragraflar, y.konu = onceki, yedek_konu          # düzeltme daha kötü: geri al
                    dk.ekle("denetle", "Düzeltme turu geri alındı", "yeni metin sınamada daha kötü sonuç verdi")
                else:
                    dk.ekle("denetle", "Düzeltme turu", f"{len(cikarilan2)} cümle yine çıkarıldı")
                    cikarilan = cikarilan + cikarilan2
        sonuc.cikarilanlar = cikarilan
        if cikarilan:
            dk.ekle("denetle", f"Sınama: {len(cikarilan)} cümle çıkarıldı", "; ".join(c["neden"] for c in cikarilan[:3]))
            if self.dersler is not None:
                try:
                    self.dersler.hata_kaydet(f"[yazı] {y.konu or sorgu}"[:300],
                                             [f"[Sınama] {c['metin'][:160]} — {c['neden'][:120]}" for c in cikarilan[:6]])
                except Exception:  # noqa: BLE001
                    pass
        else:
            dk.ekle("denetle", "Sınama: tüm cümleler geçti")

        # 6) BİÇİM ve SUN
        adim(6, "Biçim kuralları uygulanıyor")
        if not y.paragraflar or y.paragraflar[-1].tur != "bitis":
            y.paragraflar.append(Paragraf(bitis_ifadesi(y.makam, YAZI_TURLERI[y.tur]["amac"]), tur="bitis"))
        sonuc.duzeltmeler = duzelt(y)
        sonuc.kontrol = kontrol_et(y, kaynak_metinler)
        dk.ekle("sun", f"Kontrol listesi: {sum(1 for k in sonuc.kontrol if k.durum == 'tamam')} tamam, "
                       f"{sum(1 for k in sonuc.kontrol if k.durum == 'uyari')} uyarı, {sonuc.hata_sayisi} hata")
        sonuc.dusunce = dk.satirlar()
        sonuc.sure_sn = round(time.time() - bas, 1)
        return sonuc

    # ------------------------------------------------------------------ yardımcılar
    def _dersler(self, istek: str) -> list[str]:
        if self.dersler is None:
            return []
        try:
            return self.dersler.ilgili(istek, ("sentez", "yordama", "elestirme", "sunum"), 3)
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _dayanak(cevap) -> dict:
        """Doğrulanmış cevaptan yalnız sınamayı geçmiş cümleler ve kaynak metinleri alınır."""
        if cevap is None:
            return {"kaynaklar": [], "metinler": [], "cumleler": []}
        kaynaklar, metinler = [], []
        for k in getattr(cevap, "kaynaklar", []) or []:
            kaynaklar.append({"kid": k.kid, "etiket": k.etiket, "url": k.pasaj.kaynak_url or "",
                              "alinti": k.pasaj.metin[:600]})
            metinler.append(f"{k.etiket}: {k.pasaj.metin}")
        cumle_listesi = []
        for bolum in ("kisa_cevap", "uygulama", "adimlar", "dikkat"):
            for c in getattr(cevap, bolum, []) or []:
                cumle_listesi.append({"metin": c.metin, "kaynaklar": list(c.kaynaklar)})
                metinler.append(c.metin)
        if getattr(cevap, "durum", None) is not None and getattr(cevap.durum, "value", "") == "Doğrudan hüküm yok":
            cumle_listesi = []                      # hüküm yoksa yazıya hukuki sonuç taşınmaz
        return {"kaynaklar": kaynaklar, "metinler": metinler, "cumleler": cumle_listesi}

    def _model_ile_yaz(self, y: Yazi, g: GelenYazi | None, talimat: str, dayanak: dict, dersler: list[str],
                       cikarilan: list[dict] | None = None) -> dict | None:
        kendi = kendi_adi(y.baslik[-1] if len(y.baslik) > 2 else "Birim")
        gorev = (DUZELTME_GOREVI if cikarilan else YAZI_GOREVI).replace("{kendi}", kendi)
        sistem = sistem_cekirdegi(gorev)
        if dersler:
            sistem += "\n\nGEÇMİŞ DERSLER (yöntem):\n" + "\n".join(f"- {d}" for d in dersler)
        tur = YAZI_TURLERI[y.tur]
        parcalar = [f"YAZI TÜRÜ: {tur['ad']} — {tur['yonerge']}",
                    f"GÖNDEREN: {' / '.join(y.baslik[1:]) or '—'} (kendinden '{kendi}' diye söz eder)",
                    f"MUHATAP: {y.muhatap or 'DAĞITIM YERLERİNE'} ({y.makam})"]
        if y.ilgiler:
            from .kurallar import ilgi_satirlari
            parcalar.append("İLGİ:\n" + "\n".join(ilgi_satirlari(y)))
        if g:
            parcalar.append("GELEN YAZI:\n" + metni_maskele(g.metin)[:3500])
            if g.istenenler:
                parcalar.append("GELEN YAZIDA İSTENENLER:\n" + "\n".join(f"- {x}" for x in g.istenenler[:6]))
        parcalar.append("TALİMAT (birimin cevabı / yazılacak husus):\n" + (talimat or "(verilmedi: yer tutucu kullan)"))
        if dayanak["cumleler"] or dayanak["kaynaklar"]:
            satirlar = [f"- {c['metin']} [{', '.join(c['kaynaklar'])}]" for c in dayanak["cumleler"][:10]]
            satirlar += [f"[{k['kid']}] {k['etiket']}: {k['alinti'][:500]}" for k in dayanak["kaynaklar"][:5]]
            parcalar.append("DOĞRULANMIŞ DAYANAK:\n" + "\n".join(satirlar))
        if y.ekler:
            parcalar.append("EKLER: " + "; ".join(y.ekler))
        if y.ivedilik == "GÜNLÜDÜR" and y.cevap_suresi:
            parcalar.append(f"CEVAP SÜRESİ (metinde belirt): {y.cevap_suresi}")
        if cikarilan:
            parcalar.append("ÖNCEKİ METİN:\n" + "\n".join(p.metin for p in y.paragraflar if p.tur != "bitis"))
            parcalar.append("ÇIKARILAN CÜMLELER:\n" + "\n".join(f"- {c['metin']} ({c['neden']})" for c in cikarilan[:6]))
        mesajlar = [{"role": "system", "content": sistem}, {"role": "user", "content": "\n\n".join(parcalar)}]
        try:
            try:
                ham = self.model.sohbet(mesajlar, max_tokens=1400, sicaklik=0.2, json_sema=YAZI_SEMASI)
            except TypeError:
                ham = self.model.sohbet(mesajlar, max_tokens=1400, sicaklik=0.2, json_mod=True)
            from ..answer.llm import json_cikar
            veri = json_cikar(ham)
        except Exception:  # noqa: BLE001 - model hatasında şablona düşülür
            return None
        if not isinstance(veri, dict) or not isinstance(veri.get("paragraflar"), list):
            return None
        return veri

    @staticmethod
    def _veriyi_uygula(y: Yazi, veri: dict) -> None:
        if veri.get("konu") and not y.konu:
            y.konu = konu_bicimi(str(veri["konu"]))
        paragraflar = []
        for p in veri.get("paragraflar", []):
            if isinstance(p, dict) and str(p.get("metin", "")).strip():
                metin = str(p["metin"]).strip()
                if re.fullmatch(r"[^.]{0,60}(?:arz|rica) ederim\.?|Saygılarımla\.?|Bilgilerinize sunulur\.?", metin):
                    continue                        # bitiş cümlesini program ekler
                paragraflar.append(Paragraf(metin, [str(x) for x in p.get("kaynaklar", []) if x],
                                            "yer_tutucu" if "[" in metin else "metin"))
        y.paragraflar = paragraflar
        for e in veri.get("eksik_bilgiler", []) or []:
            if str(e).strip() and str(e) not in y.eksikler:
                y.eksikler.append(str(e).strip())
        for e in veri.get("ekler", []) or []:
            if str(e).strip() and str(e).strip() not in y.ekler:
                y.ekler.append(str(e).strip())

    def _sablonla_yaz(self, y: Yazi, g: GelenYazi | None, talimat: str, dayanak: dict) -> None:
        """Dil modeli yokken: türüne göre iskelet; birimin bilgisi ve doğrulanmış dayanak cümleleriyle doldurulur."""
        kendi = kendi_adi(y.baslik[-1] if len(y.baslik) > 2 else "Birim")
        ilgi_atfi = "İlgi (a) yazı ile" if len(y.ilgiler) > 1 else "İlgi yazı ile"
        konu = tr_lower(y.konu) if y.konu else "[konu]"
        p: list[Paragraf] = []
        if y.tur == "cevap" and y.ilgiler:
            p.append(Paragraf(f"{ilgi_atfi} {konu} konusunda {kendi}{_uyum2(kendi, 'dan', 'den')} bilgi istenmiştir."))
        elif y.tur == "bilgi_isteme":
            p.append(Paragraf(f"{y.konu or '[Konu]'} kapsamında yürütülen çalışmalarda kullanılmak üzere "
                              "[istenen bilgi/belge] ihtiyaç duyulmaktadır."))
        elif y.tur == "ek_gonderme":
            p.append(Paragraf(("İlgi yazı gereğince hazırlanan " if y.ilgiler else "") + "[belgeler] ekte gönderilmiştir."))
        elif y.tur == "olur":
            p.append(Paragraf(f"{y.konu or '[Konu]'} ile ilgili olarak [işlemin gerekçesi]."))
        elif y.tur == "duyuru":
            p.append(Paragraf(f"{y.konu or '[Konu]'} hakkında [duyurulacak husus]."))
        elif y.ilgiler:
            p.append(Paragraf(f"{ilgi_atfi} {konu} konusu {kendi}{_uyum2(kendi, 'a', 'e')} iletilmiştir."))
        for c in dayanak["cumleler"][:3]:                      # doğrulanmış hüküm cümleleri (olduğu gibi)
            p.append(Paragraf(c["metin"], c["kaynaklar"], "dayanak"))
        if talimat:
            for parca in [x.strip() for x in re.split(r"\n\s*\n", talimat) if x.strip()][:3]:
                p.append(Paragraf(parca if parca.endswith(".") else parca + "."))
        else:
            p.append(Paragraf("[Birimin cevabı / görüşü: istenen hususlara ilişkin bilgi buraya yazılır.]",
                              tur="yer_tutucu"))
        if y.ivedilik == "GÜNLÜDÜR" and y.cevap_suresi:
            p.append(Paragraf(f"Cevabın {y.cevap_suresi} gönderilmesi gerekmektedir."))
        if y.ekler and not any("ek" in tr_lower(x.metin) for x in p):
            p.append(Paragraf("Söz konusu belgeler ekte sunulmuştur." if y.makam in ("ust", "ayni")
                              else "Söz konusu belgeler ekte gönderilmiştir."))
        y.paragraflar = p
        if y.tur == "olur" and y.olur is None:
            y.eksikler.append("Oluru verecek makam (ad, soyad, unvan)")

    @staticmethod
    def _sina_ve_ayikla(y: Yazi, kaynak_metinler: list[str]) -> list[dict]:
        """Kaynakta karşılığı olmayan tarih/sayı/atıf içeren CÜMLELER çıkarılır; paragraf boşalırsa düşer."""
        cikarilan: list[dict] = []
        while True:
            sorunlar = sinama(y, kaynak_metinler)
            if not sorunlar:
                return cikarilan
            n, neden = sorunlar[0]
            p = y.paragraflar[n]
            parcalar = cumleler(p.metin) or [p.metin]
            ipucu = re.search(r"“(.+?)”", neden)
            hedef = ipucu.group(1) if ipucu else ""
            kalan = [c for c in parcalar if not (hedef and hedef in c)]
            if len(kalan) == len(parcalar):          # hedef bulunamadıysa paragrafın tamamı
                kalan = []
            for c in parcalar:
                if c not in kalan:
                    cikarilan.append({"metin": c, "neden": neden})
            if kalan:
                p.metin = " ".join(kalan)
            else:
                y.paragraflar.pop(n)


def yazi_json(y: Yazi) -> str:
    return json.dumps(y.sozluk(), ensure_ascii=False, indent=1)
