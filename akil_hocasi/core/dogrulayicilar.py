"""Biçim doğrulayıcıları: TC kimlik no, IBAN, ekonomik kod, E-sayı, tarih, tutar.

Sağlama hanesi kontrolleri OCR'ın yanlış okuduğu rakamları da ortaya çıkarır.
"""

from __future__ import annotations

import re
from datetime import date

# --- TC kimlik numarası -------------------------------------------------------

def tc_kimlik_gecerli(no: str) -> bool:
    """TC kimlik numarasının sağlama hanelerini kontrol eder.

    Kural: 11 hane, ilk hane 0 olamaz;
    10. hane = ((1+3+5+7+9. haneler) * 7 - (2+4+6+8. haneler)) mod 10;
    11. hane = (ilk 10 hanenin toplamı) mod 10.
    """
    no = re.sub(r"\s", "", no or "")
    if not re.fullmatch(r"[1-9]\d{10}", no):
        return False
    d = [int(c) for c in no]
    tek = d[0] + d[2] + d[4] + d[6] + d[8]
    cift = d[1] + d[3] + d[5] + d[7]
    if (tek * 7 - cift) % 10 != d[9]:
        return False
    return sum(d[:10]) % 10 == d[10]


# --- IBAN ---------------------------------------------------------------------

IBAN_UZUNLUK = {"TR": 26}


def iban_temizle(iban: str) -> str:
    return re.sub(r"[\s-]", "", iban or "").upper()


def iban_gecerli(iban: str) -> bool:
    """IBAN'ı ISO 13616 mod-97 yöntemiyle doğrular (TR için uzunluk 26)."""
    iban = iban_temizle(iban)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return False
    ulke = iban[:2]
    if ulke in IBAN_UZUNLUK and len(iban) != IBAN_UZUNLUK[ulke]:
        return False
    duzen = iban[4:] + iban[:4]
    sayi = "".join(str(int(c, 36)) for c in duzen)
    return int(sayi) % 97 == 1


def iban_kontrol_haneleri(ulke: str, bban: str) -> str:
    """Verilen ülke kodu ve BBAN için doğru kontrol hanelerini hesaplar."""
    duzen = bban + ulke.upper() + "00"
    sayi = "".join(str(int(c, 36)) for c in duzen)
    return f"{98 - int(sayi) % 97:02d}"


# --- Ekonomik kod (analitik bütçe sınıflandırması) ----------------------------

EKONOMIK_KOD = re.compile(r"^\d{2}\.\d\.\d\.\d{2}$")
_EKONOMIK_GEVSEK = re.compile(r"^(\d{1,2})\.(\d)\.(\d)\.(\d{1,2})$")


def ekonomik_kod_gecerli(kod: str) -> bool:
    """Dört düzeyli ekonomik kod biçimi: 03.3.1.01 (2+1+1+2 = 6 hane)."""
    return bool(EKONOMIK_KOD.match((kod or "").strip()))


def ekonomik_kod_duzelt(kod: str) -> str | None:
    """'03.3.1.1' gibi eksik yazılmış kodu '03.3.1.01' biçimine getirir; olmuyorsa None."""
    m = _EKONOMIK_GEVSEK.match((kod or "").strip())
    if not m:
        return None
    a, b, c, d = m.groups()
    return f"{int(a):02d}.{b}.{c}.{int(d):02d}"


# --- EBYS evrak sayısı --------------------------------------------------------

E_SAYI = re.compile(r"\bE-\d{6,10}-\d{3}(?:\.\d{2})*(?:-\d+)?\b")


def e_sayi_gecerli(sayi: str) -> bool:
    """EBYS sayı biçimi, örnek: E-63599082-105.01.01.01"""
    return bool(E_SAYI.fullmatch((sayi or "").strip()))


# --- Tarih ve tutar -----------------------------------------------------------

TARIH = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
TUTAR = re.compile(r"\b\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?\s?(?:TL|₺)|₺\s?\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?")


def tarih_gecerli(metin: str) -> bool:
    m = TARIH.fullmatch((metin or "").strip())
    if not m:
        return False
    g, a, y = (int(x) for x in m.groups())
    try:
        date(y, a, g)
    except ValueError:
        return False
    return 1900 <= y <= 2100
