"""Kişisel veri maskeleme: TC kimlik no ve IBAN varsayılan olarak maskeli kopyalanır."""

from __future__ import annotations

import re

from .dogrulayicilar import iban_temizle, tc_kimlik_gecerli

_TC = re.compile(r"\b[1-9]\d{10}\b")
_IBAN = re.compile(r"\bTR\d{2}(?:[ ]?[A-Z0-9]){22}\b", re.IGNORECASE)


def tc_maskele(no: str) -> str:
    """12345678950 -> 123******50"""
    no = re.sub(r"\s", "", no)
    return no[:3] + "*" * 6 + no[-2:] if len(no) == 11 else no


def iban_maskele(iban: str) -> str:
    """TR330006100519786457841326 -> TR33 **** **** **** **** **26"""
    t = iban_temizle(iban)
    if len(t) < 8:
        return iban
    ic = t[:4] + "*" * (len(t) - 6) + t[-2:]
    return " ".join(ic[i:i + 4] for i in range(0, len(ic), 4))


def metni_maskele(metin: str, sadece_gecerli: bool = False) -> str:
    """Metindeki TC kimlik no ve IBAN'ları maskeler.

    sadece_gecerli=True ise yalnızca sağlaması tutan numaralar maskelenir.
    Varsayılan False: OCR hatalı okusa bile kişisel veri sızmasın.
    """
    def tc_degistir(m: re.Match) -> str:
        if sadece_gecerli and not tc_kimlik_gecerli(m.group(0)):
            return m.group(0)
        return tc_maskele(m.group(0))

    metin = _IBAN.sub(lambda m: iban_maskele(m.group(0)), metin)
    return _TC.sub(tc_degistir, metin)
