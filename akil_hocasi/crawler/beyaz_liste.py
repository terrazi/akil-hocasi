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

# Yalnız kılavuz toplayıcı için ek resmî alanlar (sistem kullanım kılavuzlarının yayımlandığı kurum siteleri).
# Gözlem eklentisinin listesine girmez; bu alanlarda yalnız herkese açık sayfa ve belge okunur.
KILAVUZ_EK = [
    "muhasebat.gov.tr",      # Muhasebat GM eski alan adı (KBS/MYS kılavuzları)
    "osym.gov.tr",           # KPSS kılavuzları
    "cbiko.gov.tr",          # Kariyer Kapısı kılavuzları
    "kamusm.bilgem.tubitak.gov.tr",   # e-imza yardım belgeleri
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


KAMU_UZANTILARI = (".gov.tr", ".edu.tr")
BELGE_UZANTILARI = (".pdf", ".docx", ".doc")


def kamu_kopyasi_mi(url: str) -> bool:
    """Beyaz liste dışındaki bir kamu kurumu/üniversite sitesinde duran belge dosyası mı (ör. Muhasebat kılavuzunun
    bir üniversite strateji sitesindeki kopyası)? Yalnız kılavuz için ve yayımlayan kurum belgede doğrulanarak kullanılır."""
    u = urlparse(url)
    return (u.scheme in ("https", "http") and alan(url).endswith(KAMU_UZANTILARI)
            and u.path.lower().endswith(BELGE_UZANTILARI) and not izinli_mi(url))


def kilavuz_izinli_mi(url: str) -> bool:
    u = urlparse(url)
    if u.scheme not in ("https", "http"):
        return False
    return izinli_mi(url) or _eslesir(alan(url), KILAVUZ_EK) or kamu_kopyasi_mi(url)


def oneri_ekle(url: str) -> None:
    h = alan(url)
    if h and not izinli_mi(url):
        ONERI_LISTESI.add(h)
