"""Türkçeye duyarlı metin araçları.

Python'un varsayılan büyük/küçük harf dönüşümü Türkçede yanlıştır:
"i".upper() -> "I" (doğrusu "İ"), "İ".lower() -> "i̇" (noktalı birleşik karakter).
Bu modül bu hataları giderir ve arama için katlama (folding) sağlar.
"""

from __future__ import annotations

import re
import unicodedata

PANGRAM = "Pijamalı hasta yağız şoföre çabucak güvendi."

_KATLAMA = str.maketrans({
    "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
    "â": "a", "î": "i", "û": "u", "ê": "e", "ô": "o",
})

_KELIME = re.compile(r"[0-9A-Za-zÇĞİÖŞÜçğıöşüÂÎÛâîû]+(?:[./-][0-9A-Za-zÇĞİÖŞÜçğıöşüÂÎÛâîû]+)*")


def nfc(metin: str) -> str:
    """Metni Unicode NFC biçimine getirir (birleşik karakterleri tek karaktere indirir)."""
    return unicodedata.normalize("NFC", metin or "")


def tr_upper(metin: str) -> str:
    """Türkçe kurallarına göre büyük harfe çevirir: i -> İ, ı -> I."""
    metin = nfc(metin)
    return metin.replace("i", "İ").replace("ı", "I").upper()


def tr_lower(metin: str) -> str:
    """Türkçe kurallarına göre küçük harfe çevirir: I -> ı, İ -> i."""
    metin = nfc(metin)
    return metin.replace("I", "ı").replace("İ", "i").lower()


def tr_title(metin: str) -> str:
    """Her kelimenin ilk harfini Türkçe kurallarla büyütür."""
    return " ".join(
        (tr_upper(k[0]) + tr_lower(k[1:])) if k else k for k in nfc(metin).split(" ")
    )


def katla(metin: str) -> str:
    """Arama için katlama: küçük harf + Türkçe karakterleri ASCII karşılığına indirme.

    'AYLIKSIZ İzin' ve 'ayliksiz izin' aynı biçime iner: 'ayliksiz izin'.
    """
    return tr_lower(metin).translate(_KATLAMA)


def kelimeler(metin: str) -> list[str]:
    """Metindeki kelimeleri (sayı, kod ve noktalı kısaltmalar dahil) döndürür."""
    return _KELIME.findall(nfc(metin))


def bosluk_normalle(metin: str) -> str:
    """Satır sonu, sekme ve çoklu boşlukları tek boşluğa indirir."""
    return re.sub(r"\s+", " ", nfc(metin)).strip()


def alinti_normalle(metin: str) -> str:
    """Alıntı karşılaştırması için normalleştirme: NFC, boşluk, tırnak ve tire birliği."""
    metin = bosluk_normalle(metin)
    metin = (metin.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
             .replace("–", "-").replace("—", "-").replace("­", ""))
    return tr_lower(metin)
