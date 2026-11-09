"""Kaynak adaptörleri: her resmî kaynağın adres düzeni ve sayfa ayrıştırması.

NOT: Adres düzenleri bu sürümde yayımlanmış sayfa yapılarına göre yazılmıştır.
Faz 0'da gerçek TOGÜ bilgisayarında her adaptör tek tek denenecek; site yapısı değişirse
yalnızca bu dosya güncellenir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..core.turkce import bosluk_normalle, katla

DOSYA_UZANTILARI = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".odt", ".ods")


@dataclass
class Baglanti:
    url: str
    baslik: str
    kod: str = ""
    rv: str = ""
    sayfa_url: str = ""


def baglantilari_cikar(html: bytes | str, sayfa_url: str, sadece_dosya: bool = False) -> list[Baglanti]:
    corba = BeautifulSoup(html, "lxml")
    sonuc, goruldu = [], set()
    for a in corba.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        url = urljoin(sayfa_url, href)
        if url in goruldu:
            continue
        yol = urlparse(url).path.lower()
        if sadece_dosya and not yol.endswith(DOSYA_UZANTILARI):
            continue
        goruldu.add(url)
        # Bağlantı metni boşsa satırdaki metni kullan
        metin = bosluk_normalle(a.get_text(" "))
        satir = a.find_parent("tr")
        satir_metni = bosluk_normalle(satir.get_text(" ")) if satir else metin
        sonuc.append(Baglanti(url, metin or satir_metni, kod_bul(satir_metni or metin),
                              rv_bul(satir_metni), sayfa_url))
    return sonuc


_KOD = re.compile(r"TOG[ÜU]\s*\.\s*([A-ZÇĞİÖŞÜ]{2,4})\s*\.\s*(\d{3})")
_RV = re.compile(r"\bRV\s*[:.\-]?\s*(\d{1,3})\b|\bRev(?:izyon)?\s*(?:No)?\s*[:.\-]?\s*(\d{1,3})\b", re.IGNORECASE)


def kod_bul(metin: str) -> str:
    m = _KOD.search(metin or "")
    return f"TOGÜ.{m.group(1)}.{m.group(2)}" if m else ""


def rv_bul(metin: str) -> str:
    m = _RV.search(metin or "")
    return (m.group(1) or m.group(2)) if m else ""


# --------------------------------------------------------------------- Resmî Gazete

class ResmiGazete:
    TABAN = "https://www.resmigazete.gov.tr/eskiler"
    ILGILI = [
        "memur", "kamu görevli", "personel", "yükseköğretim", "üniversite", "öğretim", "harcırah",
        "bütçe", "harcama", "ihale", "sosyal güvenlik", "emekli", "aylık", "ücret", "ödeme", "taşınır",
        "yazışma", "devlet memurları", "toplu sözleşme", "sendika", "izin", "disiplin", "kişisel veri",
        "657", "2547", "2914", "5018", "4734", "6245", "5510",
    ]
    TURLER = ["KANUN", "CUMHURBAŞKANLIĞI KARARNAMESİ", "YÖNETMELİK", "TEBLİĞ", "GENELGE", "KARAR"]

    def gunluk_url(self, g: date, mukerrer: int = 0) -> str:
        ek = f"M{mukerrer}" if mukerrer else ""
        return f"{self.TABAN}/{g.year}/{g.month:02d}/{g.year}{g.month:02d}{g.day:02d}{ek}.htm"

    def maddeleri(self, html: bytes | str, sayfa_url: str) -> list[Baglanti]:
        """Günlük fihristten düzenleme bağlantılarını çıkarır."""
        sonuc = []
        for b in baglantilari_cikar(html, sayfa_url):
            if "/eskiler/" not in b.url or not b.url.lower().endswith((".htm", ".pdf")):
                continue
            if b.url.rstrip("/") == sayfa_url.rstrip("/"):
                continue
            sonuc.append(b)
        return sonuc

    def ilgili_mi(self, baslik: str) -> bool:
        k = katla(baslik)
        return any(katla(a) in k for a in self.ILGILI)


# --------------------------------------------------------------------- mevzuat.gov.tr

CEKIRDEK_KANUNLAR: list[tuple[str, str]] = [
    ("657", "Devlet Memurları Kanunu"),
    ("2547", "Yükseköğretim Kanunu"),
    ("2914", "Yükseköğretim Personel Kanunu"),
    ("5018", "Kamu Mali Yönetimi ve Kontrol Kanunu"),
    ("4734", "Kamu İhale Kanunu"),
    ("4735", "Kamu İhale Sözleşmeleri Kanunu"),
    ("6245", "Harcırah Kanunu"),
    ("5510", "Sosyal Sigortalar ve Genel Sağlık Sigortası Kanunu"),
    ("5434", "T.C. Emekli Sandığı Kanunu"),
    ("4688", "Kamu Görevlileri Sendikaları ve Toplu Sözleşme Kanunu"),
    ("3071", "Dilekçe Hakkının Kullanılmasına Dair Kanun"),
    ("4982", "Bilgi Edinme Hakkı Kanunu"),
    ("6698", "Kişisel Verilerin Korunması Kanunu"),
]


class Mevzuat:
    TABAN = "https://www.mevzuat.gov.tr"

    def kanun_adaylari(self, no: str, tertip: int = 5) -> list[str]:
        """Kanun metni için denenecek adresler (ilk başarılı olan kullanılır)."""
        return [
            f"{self.TABAN}/MevzuatMetin/1.{tertip}.{no}.pdf",
            f"{self.TABAN}/MevzuatMetin/1.{tertip}.{no}.doc",
            f"{self.TABAN}/mevzuat?MevzuatNo={no}&MevzuatTur=1&MevzuatTertip={tertip}",
        ]


# --------------------------------------------------------------------- TOGÜ

class Togu:
    KALITE = "https://kalite.gop.edu.tr/DinamikFormlar.aspx?d=tr-TR&mk=43543&m=kalite_belgeleri"
    BIRIMLER = ["gensek", "personel", "strateji", "imid", "bidb", "kutup", "ogr", "yapi",
                "saglikkultur", "hukukmus", "dsim", "cevre", "ebysyardim"]
    LISTE_ANAHTARLARI = ["form", "mevzuat", "yönerge", "yonerge", "iç kontrol", "ic kontrol",
                         "usul", "esas", "prosedür", "iş akış", "görev tanım"]

    def birim_ana_sayfasi(self, birim: str) -> str:
        return f"https://{birim}.gop.edu.tr/"

    def kalite_belgeleri(self, html: bytes | str) -> list[Baglanti]:
        return [b for b in baglantilari_cikar(html, self.KALITE, sadece_dosya=True)]

    def liste_sayfalari(self, html: bytes | str, sayfa_url: str) -> list[str]:
        """Birim ana sayfasından form/mevzuat liste sayfalarını bulur (aynı alan içinde)."""
        host = urlparse(sayfa_url).hostname
        sonuc = []
        for b in baglantilari_cikar(html, sayfa_url):
            if urlparse(b.url).hostname != host or b.url.lower().endswith(DOSYA_UZANTILARI):
                continue
            if any(a in katla(b.baslik) for a in (katla(x) for x in self.LISTE_ANAHTARLARI)):
                sonuc.append(b.url)
        return list(dict.fromkeys(sonuc))[:12]


# --------------------------------------------------------------------- ikincil

class Ikincil:
    """İkincil siteler: yalnızca başlık + bağlantı (ipucu). Kullanım şartları incelenene kadar kapalı."""
    ACIK = False
