"""Kural tabanlı doğrulama motoru (yapay zekadan bağımsız).

Yedi test: Kaynak, Güncellik, Alıntı, Çapraz kontrol, Hiyerarşi, Biçim, Somutluk.
Geçemeyen cümle silinir veya etiketlenir; kaynaksız cümle kullanıcıya ulaşmaz.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..core import dogrulayicilar as d
from ..core.turkce import alinti_normalle, katla
from ..library.db import Kutuphane
from .modeller import Cevap, Cumle, Durum, Uyari

_ALINTI = re.compile(r"[\"“]([^\"”]{12,})[\"”]")
_SAYI = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)(?![\w])")
_EKO_GEVSEK = re.compile(r"(?<![\d.])\d{2}\.\d\.\d\.\d{1,2}(?![\d.])")

SOMUT_CAPA = re.compile(
    r"(\bmd\.\s*\d+|\bmadde(?:si|sinin|sine)?\s*\d+|\d+\s*(?:inci|ıncı|uncu|üncü|nci|ncı|ncu|ncü)\s+madde"
    r"|\bFRM\.\d+|\bYÖN\.\d+|\bUSE\.\d+|\bPRS\.\d+|\b\d{3,4}\s+sayılı)",
    re.IGNORECASE,
)

AFAKI_KALIPLAR = [
    "ilgili mevzuat çerçevesinde", "ilgili mevzuata göre", "mevzuat hükümleri çerçevesinde",
    "duruma göre değişir", "duruma göre değişebilir", "kurumunuza danışınız", "kurumunuza danışmanız",
    "gerekli işlemler yapılır", "genel olarak", "genellikle", "çeşitli faktörlere bağlı",
]


def _alan_beyaz_listede(url: str, beyaz_liste: list[str]) -> bool:
    if not url:
        return False
    alan = (urlparse(url).hostname or "").lower()
    return any(alan == b or alan.endswith("." + b) for b in beyaz_liste)


def _sayi_normal(s: str) -> str:
    return s.replace(".", "").replace(",", ".")


class DogrulamaMotoru:
    def __init__(self, kutuphane: Kutuphane | None, beyaz_liste: list[str]):
        self.kutuphane = kutuphane
        self.beyaz_liste = [b.lower() for b in beyaz_liste]

    # ------------------------------------------------------------------ ana giriş
    def dogrula(self, cevap: Cevap) -> Cevap:
        celiski = False
        for bolum in ("kisa_cevap", "adimlar", "dikkat"):
            kalan: list[Cumle] = []
            for c in getattr(cevap, bolum):
                ok, cel = self._cumle_dogrula(cevap, c)
                celiski = celiski or cel
                if ok:
                    kalan.append(c)
            setattr(cevap, bolum, kalan)

        self._somutluk(cevap)
        self._hiyerarsi(cevap)
        if any(u.test == "Hiyerarşi" and u.seviye == "hata" for u in cevap.uyarilar):
            celiski = True

        # Kullanılmayan kaynakları ayıkla (sıralamayı koru)
        kullanilan = {k for c in cevap.tum_cumleler() for k in c.kaynaklar}
        if kullanilan:
            cevap.kaynaklar = [k for k in cevap.kaynaklar if k.kid in kullanilan] or cevap.kaynaklar

        if not cevap.kisa_cevap:
            cevap.durum = Durum.HUKUM_YOK
        elif celiski:
            cevap.durum = Durum.CELISKILI
        else:
            cevap.durum = Durum.DOGRULANDI
        return cevap

    # ------------------------------------------------------------------ cümle testleri
    def _cumle_dogrula(self, cevap: Cevap, c: Cumle) -> tuple[bool, bool]:
        if c.tur == "yonlendirme":
            return True, False

        # Kaynaksız cümle yok
        kaynaklar = [cevap.kaynak(k) for k in c.kaynaklar]
        kaynaklar = [k for k in kaynaklar if k is not None]
        if not kaynaklar:
            cevap.uyarilar.append(Uyari("Kaynak", f"Kaynaksız cümle çıkarıldı: {c.metin[:80]}", "bilgi"))
            return False, False

        # 1) Kaynak testi
        gecerli = [k for k in kaynaklar if _alan_beyaz_listede(k.pasaj.kaynak_url, self.beyaz_liste)
                   or k.pasaj.belge_turu in ("togu_yerel", "kart")]
        if not gecerli:
            cevap.uyarilar.append(Uyari("Kaynak", f"Beyaz liste dışı kaynak: {kaynaklar[0].pasaj.kaynak_url}", "hata"))
            return False, False

        # 2) Güncellik testi
        for k in gecerli:
            if k.pasaj.mulga:
                cevap.uyarilar.append(Uyari("Güncellik", f"{k.etiket} mülga; bu maddeye dayanan cümle çıkarıldı", "hata"))
                return False, False
            if not k.pasaj.yururlukte:
                c.notlar.append(f"{k.etiket} yürürlükten kalkmış bir sürüme ait")
                cevap.uyarilar.append(Uyari("Güncellik", f"{k.etiket} eski sürüm; güncel metin kontrol edilmeli"))

        birlesik = " ".join(k.pasaj.metin for k in gecerli)
        birlesik_n = alinti_normalle(birlesik)

        # 3) Alıntı testi
        for m in _ALINTI.finditer(c.metin):
            if alinti_normalle(m.group(1)) not in birlesik_n:
                cevap.uyarilar.append(Uyari("Alıntı", f"Kaynakta birebir bulunmayan alıntı reddedildi: “{m.group(1)[:60]}…”", "hata"))
                return False, False

        # 6) Biçim testi (önce düzelt, sonra çapraz kontrol)
        for m in _EKO_GEVSEK.finditer(c.metin):
            if not d.ekonomik_kod_gecerli(m.group(0)):
                duz = d.ekonomik_kod_duzelt(m.group(0))
                if duz:
                    c.metin = c.metin.replace(m.group(0), duz)
                    cevap.uyarilar.append(Uyari("Biçim", f"Ekonomik kod düzeltildi: {m.group(0)} → {duz}", "bilgi"))

        # 4) Çapraz kontrol: cümledeki sayılar kaynakta geçmeli
        kaynak_sayilari = {_sayi_normal(s) for s in _SAYI.findall(birlesik)}
        kaynak_sayilari |= {_sayi_normal(s) for k in gecerli for s in re.findall(r"\d+", k.pasaj.belge_kimlik + " " + k.pasaj.madde_no)}
        metin_sayisiz_alinti = _ALINTI.sub("", c.metin)
        for s in _SAYI.findall(metin_sayisiz_alinti):
            sn = _sayi_normal(s)
            if sn in kaynak_sayilari:
                continue
            # ekonomik kod parçaları gibi noktalı ifadeler: birleşik metinde ham haliyle aranır
            if s in birlesik:
                continue
            cevap.uyarilar.append(Uyari("Çapraz kontrol", f"“{s}” değeri kaynakta doğrulanamadı; cümle çıkarıldı", "hata"))
            return False, False

        # 7) Somutluk (cümle düzeyi): afaki kalıp + çapa yoksa çıkar
        k_metin = katla(c.metin)
        for kalip in AFAKI_KALIPLAR:
            if katla(kalip) in k_metin and not SOMUT_CAPA.search(c.metin):
                cevap.uyarilar.append(Uyari("Somutluk", f"Genel kalıp içeren cümle çıkarıldı: “{kalip}”", "bilgi"))
                return False, False

        c.kaynaklar = [k.kid for k in gecerli]
        return True, False

    # ------------------------------------------------------------------ cevap testleri
    def _somutluk(self, cevap: Cevap) -> None:
        if not cevap.kisa_cevap:
            return
        metinler = " ".join(c.metin for c in cevap.tum_cumleler())
        etiketler = " ".join(k.etiket for k in cevap.kaynaklar)
        if not (SOMUT_CAPA.search(metinler) or SOMUT_CAPA.search(etiketler) or cevap.adimlar or cevap.belgeler):
            cevap.uyarilar.append(Uyari("Somutluk", "Cevapta madde, form veya adım yok; dayanak listesine bakınız"))

    def _hiyerarsi(self, cevap: Cevap) -> None:
        """TOGÜ düzenlemesinin dayandığı üst norm maddesi, düzenlemeden sonra değişmiş mi?"""
        if not self.kutuphane:
            return
        for k in cevap.kaynaklar:
            p = k.pasaj
            if not p.belge_kimlik.upper().startswith("TOGÜ"):
                continue
            bilgi = self.kutuphane.belge_bilgisi(p.belge_kimlik)
            if not bilgi:
                continue
            tarih = bilgi["yayin_tarihi"] or bilgi["gecerlilik_baslangic"] or ""
            for atif in p.atiflar:
                if "/" not in atif or atif.upper().startswith("TOGÜ"):
                    continue
                kimlik, no = atif.rsplit("/", 1)
                if tarih and self.kutuphane.madde_degisti_mi(kimlik, no, tarih):
                    cevap.uyarilar.append(Uyari(
                        "Hiyerarşi",
                        f"{p.belge_baslik} dayandığı {kimlik} sayılı mevzuatın {no}. maddesinin "
                        f"değişmesinden önce yayımlanmış; üst norm esas alınmalı", "hata"))
