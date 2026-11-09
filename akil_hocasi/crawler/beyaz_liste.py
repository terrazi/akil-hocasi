"""Beyaz liste: program yalnızca bu alanlardan okuma yapar.

BIRINCIL: tam metin alınır, dosyalar indirilir.
IKINCIL: yalnızca başlık ve bağlantı (ipucu) tutulur; içerik kopyalanmaz.
"""

from __future__ import annotations

from urllib.parse import urlparse

BIRINCIL = [
    "resmigazete.gov.tr",
    "mevzuat.gov.tr",
    "gop.edu.tr",            # tüm TOGÜ alt alanları (kalite, personel, strateji, imid, ebysyardim ...)
    "yok.gov.tr",
    "hmb.gov.tr",            # muhasebat.hmb.gov.tr, bumko.hmb.gov.tr dahil
    "kbs.gov.tr",
    "sgk.gov.tr",
    "sayistay.gov.tr",
    "danistay.gov.tr",
    "kik.gov.tr",
    "kaysis.gov.tr",
    "kvkk.gov.tr",
    "csgb.gov.tr",
    "tccb.gov.tr",
]

IKINCIL = [
    "memurlar.net",
]

ONERI_LISTESI: set[str] = set()   # taramada görülen, beyaz listede olmayan alanlar


def alan(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _eslesir(host: str, liste: list[str]) -> bool:
    return any(host == b or host.endswith("." + b) for b in liste)


def birincil_mi(url: str) -> bool:
    return _eslesir(alan(url), BIRINCIL)


def ikincil_mi(url: str) -> bool:
    return _eslesir(alan(url), IKINCIL)


def izinli_mi(url: str) -> bool:
    u = urlparse(url)
    if u.scheme not in ("https", "http"):
        return False
    return birincil_mi(url) or ikincil_mi(url)


def oneri_ekle(url: str) -> None:
    h = alan(url)
    if h and not izinli_mi(url):
        ONERI_LISTESI.add(h)
