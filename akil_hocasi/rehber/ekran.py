"""Ekran tanıma: kullanıcının takıldığı ekranın görüntüsünden (yerel OCR metni) sistemi, ekranı, hata iletisini ve
ilgili kılavuz bölümlerini bulur.

Görüntü bilgisayardan çıkmaz; OCR yereldir; metin önce maskelenir (TC kimlik no, IBAN, kart, cep telefonu).
Program ekrana dokunmaz, tıklamaz, sisteme bağlanmaz: yalnız kullanıcının verdiği görüntüyü okur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core.turkce import bosluk_normalle, katla
from .kilavuz import KILAVUZ_TURLERI
from .sistemler import Sistem, sistem_bul

_HATA = re.compile(
    r"(hata|uyar[ıi]|ba[şs]ar[ıi]s[ıi]z|ge[çc]ersiz|bulunamad|bulunmamaktad|yetki(?:niz|si)?\s*(?:yok|bulunm)|"
    r"zaman\s*a[şs][ıi]m|reddedildi|izin\s*verilmedi|kilitlen|s[üu]resi\s*dol|eri[şs]ilemi|yap[ıi]lamad|"
    r"al[ıi]namad|error|exception|failed|denied|cannot|unable|invalid|not\s*found|timeout|warning)", re.IGNORECASE)
_URL = re.compile(r"\b(?:https?://)?([a-z0-9-]+(?:\.[a-z0-9-]+)+\.(?:gov|edu|com|org|net)\.tr|[a-z0-9-]+\.kep\.tr)\b",
                  re.IGNORECASE)


def maskele(metin: str) -> str:
    from ..gozlem.degerlendirici import maskele as _maskele
    return _maskele(metin or "")


@dataclass
class EkranAnalizi:
    metin: str                                   # maskelenmiş OCR metni
    sistem: Sistem | None = None
    sistem_puani: float = 0.0
    eslesen: list[str] = field(default_factory=list)
    diger_sistemler: list[tuple[str, float]] = field(default_factory=list)
    adresler: list[str] = field(default_factory=list)
    hatalar: list[str] = field(default_factory=list)
    ekran_basligi: str = ""
    etiketler: list[str] = field(default_factory=list)   # ekranda görünen ve kılavuzda da geçen arayüz adları
    bolumler: list = field(default_factory=list)          # Pasaj listesi (en uygun kılavuz bölümleri)

    @property
    def tanindi(self) -> bool:
        return self.sistem is not None

    def soru_onerisi(self, kullanici_notu: str = "") -> str:
        not_ = bosluk_normalle(kullanici_notu)
        if self.sistem is None:                        # sistem tanınmadıysa ekran adı tahmini de güvenilmez
            ileti = f" “{self.hatalar[0][:140].strip(' .:')}” iletisi görünüyor." if self.hatalar else ""
            soru = f"Ekranda takıldım.{ileti} Sonraki adım nedir?"
            return f"{soru} {not_}".strip() if not_ else soru
        ad = self.sistem.ad_cumle
        if self.hatalar:
            ileti = self.hatalar[0][:140].strip(" .:")
            tur = "uyarısı" if re.search(r"uyar", katla(ileti)) else "hatası"
            soru = f"{ad} ekranında “{ileti}” {tur} alıyorum. Ne yapmalıyım?"
        elif self.ekran_basligi:
            soru = f"{ad} “{self.ekran_basligi}” ekranındayım. Bu ekranda işlemi nasıl tamamlarım?"
        else:
            soru = f"{ad} ekranında takıldım. Sonraki adım nedir?"
        return f"{soru} {not_}".strip() if not_ else soru

    def ozet(self) -> str:
        if not self.sistem:
            return "Ekrandaki sistem tanınamadı."
        parca = [f"{self.sistem.kisa} ekranı"]
        if self.ekran_basligi:
            parca.append(f"“{self.ekran_basligi}”")
        if self.hatalar:
            parca.append(f"ileti: “{self.hatalar[0][:80]}”")
        return " · ".join(parca)


def _satirlar(metin: str) -> list[str]:
    return [bosluk_normalle(s) for s in (metin or "").splitlines() if bosluk_normalle(s)]


_UYGULAMA_ADI = ("sistemi", "programi", "platformu", "kapisi", "system", "portal")


def _ekran_basligi(satirlar: list[str]) -> str:
    satirlar = [s for s in satirlar if not katla(s).rstrip(" .:").endswith(_UYGULAMA_ADI)]
    for s in satirlar[:25]:
        k = katla(s)
        if 4 <= len(s) <= 70 and ("ekran" in k or "islemleri" in k or k.endswith(("girisi", "listesi", "yaz",
                                                                                  "olusturma", "sorgulama"))):
            return s.strip(" :|-")
    for s in satirlar[:12]:
        kelimeler = s.split()
        if 2 <= len(kelimeler) <= 7 and 6 <= len(s) <= 60 and sum(k[:1].isupper() for k in kelimeler) >= len(kelimeler) - 1 \
                and not any(c.isdigit() for c in s):
            return s.strip(" :|-")
    return ""


def ekrani_coz(ocr_metni: str, kutuphane=None, soru: str = "", limit: int = 6) -> EkranAnalizi:
    """OCR metninden sistemi ve ilgili kılavuz bölümlerini bulur."""
    metin = maskele(ocr_metni)
    satirlar = _satirlar(metin)
    analiz = EkranAnalizi(metin=metin)
    analiz.adresler = list(dict.fromkeys(m.group(1).lower() for m in _URL.finditer(metin)))
    bulunan = sistem_bul(metin + "\n" + soru, en_az_puan=2.0)
    if bulunan:
        s, puan, eslesen = bulunan[0]
        analiz.sistem, analiz.sistem_puani, analiz.eslesen = s, puan, eslesen
        analiz.diger_sistemler = [(x.kimlik, p) for x, p, _ in bulunan[1:4]]
    analiz.hatalar = [s for s in satirlar if _HATA.search(s) and 6 <= len(s) <= 300][:5]
    analiz.ekran_basligi = _ekran_basligi(satirlar)
    if kutuphane is None:
        return analiz

    kisa = [s for s in satirlar if 3 <= len(s) <= 50 and not s.replace(" ", "").isdigit()]
    sorgu = " ".join(analiz.hatalar[:2] + ([analiz.ekran_basligi] if analiz.ekran_basligi else []) + kisa[:25]
                     + ([soru] if soru else []))
    ek = list(analiz.eslesen[:4])
    adaylar = kutuphane.ara(sorgu, limit=max(limit * 4, 16), ek_terimler=ek, turler=KILAVUZ_TURLERI)
    if analiz.sistem is not None:
        onek = f"KLV:{analiz.sistem.kimlik}:"
        sistemin = [p for p in adaylar if p.belge_kimlik.startswith(onek)]
        adaylar = sistemin or adaylar
    kisa_k = {katla(s) for s in kisa}
    hata_k = [katla(h) for h in analiz.hatalar if len(h) >= 12]
    for p in adaylar:
        govde = katla(p.baslik + "\n" + p.metin)
        ortak = sum(1 for s in kisa_k if len(s) >= 4 and s in govde)
        p.skor += 12.0 * ortak / max(4, len(kisa_k))
        if any(h[:60] in govde for h in hata_k):
            p.skor += 15.0                              # ekrandaki hata iletisi en ayırt edici işarettir
        if analiz.ekran_basligi and katla(analiz.ekran_basligi) in katla(p.baslik):
            p.skor += 4.0
    adaylar.sort(key=lambda p: -p.skor)
    analiz.bolumler = adaylar[:limit]
    birlesik = katla(" ".join(p.baslik + " " + p.metin for p in analiz.bolumler))
    analiz.etiketler = [s for s in kisa if len(s) >= 3 and katla(s) in birlesik][:20]
    return analiz
