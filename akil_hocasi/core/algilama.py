"""Akıllı algılama: metinde TC no, IBAN, tarih, E-sayı, tutar ve ekonomik kod bulur.

Her bulgu doğrulama sonucuyla döner; sağlaması tutmayan TC/IBAN muhtemel OCR hatasıdır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import dogrulayicilar as d
from .maskeleme import iban_maskele, tc_maskele


@dataclass
class Bulgu:
    tur: str            # "tc", "iban", "tarih", "e_sayi", "tutar", "ekonomik_kod"
    metin: str          # metinde göründüğü hali
    baslangic: int
    bitis: int
    gecerli: bool
    not_: str = ""

    @property
    def etiket(self) -> str:
        return {
            "tc": "TC kimlik no", "iban": "IBAN", "tarih": "Tarih", "e_sayi": "E-sayı",
            "tutar": "Tutar", "ekonomik_kod": "Ekonomik kod",
        }[self.tur]

    def maskeli(self) -> str:
        if self.tur == "tc":
            return tc_maskele(self.metin)
        if self.tur == "iban":
            return iban_maskele(self.metin)
        return self.metin

    def kopya_degeri(self, maskeli: bool = True) -> str:
        if self.tur in ("tc", "iban"):
            return self.maskeli() if maskeli else re.sub(r"\s", "", self.metin)
        return self.metin


_TC = re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)")
_IBAN = re.compile(r"\bTR\s?\d{2}(?:\s?[0-9A-Z]){22}\b")
_EKO = re.compile(r"(?<![\d.])\d{2}\.\d\.\d\.\d{1,2}(?![\d.])")


def algila(metin: str) -> list[Bulgu]:
    """Metindeki tüm tanınan varlıkları konum sırasıyla döndürür."""
    bulgular: list[Bulgu] = []
    for m in _IBAN.finditer(metin):
        ok = d.iban_gecerli(m.group(0))
        bulgular.append(Bulgu("iban", m.group(0), m.start(), m.end(), ok,
                              "" if ok else "Sağlama tutmuyor: rakamlardan biri yanlış okunmuş olabilir"))
    for m in _TC.finditer(metin):
        if any(b.baslangic <= m.start() < b.bitis for b in bulgular):
            continue
        ok = d.tc_kimlik_gecerli(m.group(0))
        bulgular.append(Bulgu("tc", m.group(0), m.start(), m.end(), ok,
                              "" if ok else "Sağlama tutmuyor: rakamlardan biri yanlış okunmuş olabilir"))
    for m in d.E_SAYI.finditer(metin):
        bulgular.append(Bulgu("e_sayi", m.group(0), m.start(), m.end(), True))
    for m in d.TARIH.finditer(metin):
        ok = d.tarih_gecerli(m.group(0))
        bulgular.append(Bulgu("tarih", m.group(0), m.start(), m.end(), ok,
                              "" if ok else "Geçersiz tarih"))
    for m in d.TUTAR.finditer(metin):
        bulgular.append(Bulgu("tutar", m.group(0).strip(), m.start(), m.end(), True))
    for m in _EKO.finditer(metin):
        if any(b.baslangic <= m.start() < b.bitis for b in bulgular):
            continue
        ok = d.ekonomik_kod_gecerli(m.group(0))
        duz = d.ekonomik_kod_duzelt(m.group(0))
        bulgular.append(Bulgu("ekonomik_kod", m.group(0), m.start(), m.end(), ok,
                              "" if ok else f"Biçim hatalı; doğrusu muhtemelen {duz}"))
    return sorted(bulgular, key=lambda b: b.baslangic)
