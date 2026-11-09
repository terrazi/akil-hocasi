"""Biçim kuralları ve standart ifadeler (Yönetmelik madde numaralarıyla).

Bu dosyadaki her kural Yönetmelikteki bir maddeye dayanır; kontrol listesinde madde numarasıyla gösterilir.
Kütüphanede Yönetmeliğin metni varsa kontrol listesi doğrudan o maddeye bağlanır.
"""

from __future__ import annotations

import re

from ..core.turkce import tr_lower, tr_upper
from .dil import _uyum4, ilgi_hali, kisi_adi
from .model import Ilgi, Yazi

# ---------------------------------------------------------------- sayfa (md. 6–9, 24)
SAYFA = {"en_cm": 21.0, "boy_cm": 29.7, "ust_cm": 1.5, "ust_logo_cm": 0.5, "sol_cm": 1.5, "sag_cm": 1.5,
         "alt_cm": 1.0}
YAZI_TIPLERI = {"Times New Roman": 12, "Arial": 11}       # md. 7 (gerekli hâlde 9, iletişimde 8 puntoya kadar)
PARAGRAF_GIRINTISI_CM = 1.25                              # md. 16


# ---------------------------------------------------------------- bitiş ifadeleri (md. 16)
def bitis_ifadesi(makam: str, amac: str = "bilgi") -> str:
    """Metnin son cümlesi. makam: ust|ayni|alt|karisik|kisi; amac: bilgi|gereği|bilgi_ve_gereği|olur."""
    if makam == "kisi":
        return "Bilgilerinize sunulur."
    fiil = {"ust": "arz ederim", "ayni": "arz ederim", "alt": "rica ederim", "karisik": "arz ve rica ederim"}.get(
        makam, "arz ederim")
    if amac == "olur":
        return "Makamlarınızca da uygun görülmesi hâlinde olurlarınıza arz ederim."
    nesne = {"bilgi": "Bilgilerinizi", "gereği": "Gereğini", "bilgi_ve_gereği": "Bilgilerinizi ve gereğini"}.get(
        amac, "Bilgilerinizi")
    return f"{nesne} {fiil}."


_BITIS = re.compile(r"(arz ederim|rica ederim|arz ve rica ederim|arz/rica ederim|saygılarımla|iyi dileklerimle|"
                    r"bilgilerinize sunulur)\.?\s*$", re.I)


def bitis_uyumlu_mu(son_paragraf: str, makam: str) -> tuple[bool, str]:
    m = _BITIS.search(son_paragraf.strip())
    if not m:
        return False, "Metin md. 16'daki bitiş ifadelerinden biriyle bitmiyor"
    ifade = tr_lower(m.group(1))
    beklenen = {"ust": ("arz ederim",), "ayni": ("arz ederim",), "alt": ("rica ederim",),
                "karisik": ("arz ve rica ederim", "arz/rica ederim"),
                "kisi": ("saygılarımla", "iyi dileklerimle", "bilgilerinize sunulur")}.get(makam, ())
    if beklenen and ifade not in beklenen:
        return False, f"Muhatap {makam_adi(makam).lower()} olduğu için bitiş “… {beklenen[0]}” olmalı (şu an: “{ifade}”)"
    return True, ""


def makam_adi(makam: str) -> str:
    from .model import MAKAM_ILISKILERI
    return MAKAM_ILISKILERI.get(makam, makam)


# Gönderen bir üniversite birimi olduğunda muhatabın konumu için ilk tahmin (kullanıcı değiştirir)
_UST_MAKAM = re.compile(r"REKTÖRLÜ|CUMHURBAŞKANLIĞ|BAKANLIĞ|YÜKSEKÖĞRETİM KURULU|YÖK\b|VALİLİĞ|SAYIŞTAY|"
                        r"KAYMAKAMLIĞ|GENEL MÜDÜRLÜĞ|BAŞKANLIĞI\b.*\(.*Rektör", re.I)


def makam_tahmini(muhatap: str, kisiye: bool = False, dagitimli: bool = False) -> tuple[str, bool]:
    """(makam, emin_mi). Emin değilse kontrol listesi kullanıcıdan doğrulamasını ister."""
    if kisiye or muhatap.strip().lower().startswith("sayın"):
        return "kisi", True
    m = tr_upper(muhatap)
    if _UST_MAKAM.search(m):
        return "ust", True
    if dagitimli:
        return "karisik", False
    return "ayni", False


# ---------------------------------------------------------------- ilgi (md. 15)
def ilgi_satiri(i: Ilgi, muhatap_idare: str = "") -> str:
    """'… tarihli ve … sayılı yazı.' biçimi; muhatap idareden gelen belgede idare adı yazılmaz."""
    if i.metin.strip():
        m = i.metin.strip()
        return m if m.endswith(".") else m + "."
    tur = i.tur or "yazı"
    if i.kisi:                                            # gerçek kişi başvurusu
        ad = kisi_adi(i.kisi)
        sahip = f"{ad}'{kisi_ilgi_eki(ad)} "
        return f"{sahip}{i.tarih} tarihli {tur if tur in ('başvurusu', 'dilekçesi') else 'başvurusu'}.".replace("  ", " ")
    if not i.tarih and not i.sayi:
        return f"İsimsiz ve tarihsiz {tur}."
    idare = i.idare.strip()
    ayni = bool(idare and muhatap_idare and tr_lower(idare)[:20] in tr_lower(muhatap_idare))
    on = "" if (not idare or ayni) else f"{ilgi_hali(idare)} "
    if on:
        tur_ek = {"yazı": "yazısı", "e-posta": "e-postası", "olur": "oluru"}.get(tur, tur)
    else:
        tur_ek = tur
    parcalar = []
    if i.tarih:
        parcalar.append(f"{i.tarih} tarihli")
    if i.sayi:
        parcalar.append(f"{i.sayi} sayılı")
    return f"{on}{' ve '.join(parcalar)} {tur_ek}."


def kisi_ilgi_eki(ad: str) -> str:
    """Özel ada kesme işaretiyle ilgi eki: YILMAZ'ın, ÖZTÜRK'ün, ACAR'ın, KAYA'nın."""
    son = tr_lower(ad.split()[-1]) if ad.split() else ""
    ek = _uyum4(son) + "n"
    return ("n" + ek) if son[-1:] in "aeıioöuü" else ek


def ilgi_siralama_anahtari(i: Ilgi) -> tuple:
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", i.tarih or "")
    return (int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else (9999, 12, 31)


def harf(n: int) -> str:
    return "abcçdefgğhıijklmnoöprsştuüvyz"[n] if n < 29 else str(n + 1)


def ilgi_satirlari(y: Yazi) -> list[str]:
    """Tarih sırasına göre (eskiden yeniye) a), b) … (md. 15)."""
    sirali = sorted(y.ilgiler, key=ilgi_siralama_anahtari)
    satirlar = [ilgi_satiri(i, y.muhatap) for i in sirali]
    if len(satirlar) == 1:
        return satirlar
    return [f"{harf(n)}) {s}" for n, s in enumerate(satirlar)]
