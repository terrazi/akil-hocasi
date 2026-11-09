"""Türkçe OCR düzeltme önerileri.

OCR motorları en çok Türkçe karakterleri karıştırır (ı/i, ş/s, ğ/g, ü/u, ö/o, ç/c, İ/I).
Sözlükte olmayan kelime için bu karakterlerin olası varyantları üretilir; sözlükte bulunan
varyant öneri olarak sunulur. Öneri otomatik uygulanmaz, kullanıcı onaylar.
Sözlük kütüphanedeki mevzuat metinlerinden kurulur.
"""

from __future__ import annotations

import itertools
import re
from collections import Counter

from ..core.turkce import tr_lower

KARISANLAR = {
    "i": "iı", "ı": "ıi", "s": "sş", "ş": "şs", "g": "gğ", "ğ": "ğg",
    "u": "uü", "ü": "üu", "o": "oö", "ö": "öo", "c": "cç", "ç": "çc",
}
_KELIME = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşüÂÎÛâîû]+")


class TurkceDuzeltici:
    def __init__(self, sozluk: Counter | None = None, ogrenilmis: dict[str, str] | None = None):
        self.sozluk: Counter = sozluk or Counter()
        self.ogrenilmis: dict[str, str] = ogrenilmis or {}   # kullanıcının daha önce düzelttikleri

    def metinden_ogren(self, metin: str) -> None:
        self.sozluk.update(tr_lower(k) for k in _KELIME.findall(metin) if len(k) > 1)

    def oner(self, kelime: str, en_fazla_degisim: int = 3) -> str:
        """Kelime sözlükte yoksa en sık geçen Türkçe karakter varyantını döndürür; yoksa ''."""
        if kelime in self.ogrenilmis:
            return self.ogrenilmis[kelime]
        if not self.sozluk:
            return ""
        alt = tr_lower(kelime)
        temiz = "".join(ch for ch in alt if ch.isalpha())
        if not temiz or temiz in self.sozluk or len(temiz) < 3:
            return ""
        konumlar = [i for i, ch in enumerate(temiz) if ch in KARISANLAR]
        if not konumlar or len(konumlar) > 10:
            return ""
        en_iyi, en_iyi_sayi = "", 0
        for n in range(1, min(en_fazla_degisim, len(konumlar)) + 1):
            for secim in itertools.combinations(konumlar, n):
                harfler = list(temiz)
                for i in secim:
                    harfler[i] = KARISANLAR[harfler[i]][1]
                aday = "".join(harfler)
                sayi = self.sozluk.get(aday, 0)
                if sayi > en_iyi_sayi:
                    en_iyi, en_iyi_sayi = aday, sayi
            if en_iyi:
                break
        if not en_iyi:
            return ""
        # Orijinal büyük harf düzenini koru
        if kelime[:1].isupper():
            from ..core.turkce import tr_upper
            en_iyi = tr_upper(en_iyi[0]) + en_iyi[1:]
        return en_iyi
