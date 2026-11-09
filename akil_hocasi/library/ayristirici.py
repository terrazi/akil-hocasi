"""Mevzuat metnini madde madde parçalar ve atıfları çıkarır.

Desteklenen başlıklar: "MADDE 108 –", "Madde 5-", "EK MADDE 3 –", "GEÇİCİ MADDE 12 –".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core.turkce import nfc

_MADDE_BASI = re.compile(
    r"^[ \t]*(?P<tur>EK\s+MADDE|GEÇİCİ\s+MADDE|Ek\s+Madde|Geçici\s+Madde|MADDE|Madde)"
    r"\s+(?P<no>\d+(?:/[A-Za-zÇĞİÖŞÜçğıöşü])?)\s*[-–—]\s*",
    re.MULTILINE,
)
_MULGA = re.compile(r"\(\s*M[üu]lga", re.IGNORECASE)

# "657 sayılı Kanunun 108 inci maddesi", "2547 sayılı Kanunun 39 uncu maddesi"
_ATIF_DIS = re.compile(
    r"(?P<kanun>\d{3,4})\s+sayılı\s+[^.;\n]{0,60}?(?P<madde>\d+)\s*(?:'?\s*(?:inci|ıncı|uncu|üncü|nci|ncı|ncu|ncü))?\s+madde",
    re.IGNORECASE,
)
# "bu Kanunun 64 üncü maddesi", "108 inci maddesinde"
_ATIF_IC = re.compile(
    r"(?<!sayılı )\b(?P<madde>\d{1,3})\s*(?:'?\s*(?:inci|ıncı|uncu|üncü|nci|ncı|ncu|ncü))\s+madde",
    re.IGNORECASE,
)


@dataclass
class MaddeParcasi:
    madde_no: str               # "108", "Ek 3", "Geçici 12"
    metin: str
    baslik: str = ""
    mulga: bool = False
    atiflar: list[str] = field(default_factory=list)   # "657/108" veya "./64" (aynı belge)


def _madde_etiketi(tur: str, no: str) -> str:
    tur = tur.upper().replace("İ", "I")
    if tur.startswith("EK"):
        return f"Ek {no}"
    if tur.startswith("GEÇ") or tur.startswith("GEC"):
        return f"Geçici {no}"
    return no


def atiflari_bul(metin: str) -> list[str]:
    atiflar: list[str] = []
    dis_araliklar = []
    for m in _ATIF_DIS.finditer(metin):
        atiflar.append(f"{m.group('kanun')}/{m.group('madde')}")
        dis_araliklar.append((m.start(), m.end()))
    for m in _ATIF_IC.finditer(metin):
        if any(a <= m.start() < b for a, b in dis_araliklar):
            continue
        atiflar.append(f"./{m.group('madde')}")
    goruldu, sonuc = set(), []
    for a in atiflar:
        if a not in goruldu:
            goruldu.add(a)
            sonuc.append(a)
    return sonuc


def maddelere_bol(metin: str) -> list[MaddeParcasi]:
    """Metni maddelere böler. Madde başlığından önceki metin 'Giriş' parçası olur.

    Madde başlığının hemen üstündeki tek satırlık kısa satır (ör. "Aylıksız izin")
    maddenin kenar başlığı kabul edilir.
    """
    metin = nfc(metin).replace("\r\n", "\n")
    eslesmeler = list(_MADDE_BASI.finditer(metin))
    parcalar: list[MaddeParcasi] = []
    if not eslesmeler:
        govde = metin.strip()
        return [MaddeParcasi("Giriş", govde, atiflar=atiflari_bul(govde))] if govde else []

    giris = metin[: eslesmeler[0].start()].strip()
    for i, m in enumerate(eslesmeler):
        bitis = eslesmeler[i + 1].start() if i + 1 < len(eslesmeler) else len(metin)
        govde = metin[m.start():bitis].strip()
        # Sonraki maddenin kenar başlığını bu maddeden ayır
        satirlar = govde.split("\n")
        kenar = ""
        if i + 1 < len(eslesmeler) and len(satirlar) > 1:
            son = satirlar[-1].strip()
            if 0 < len(son) <= 80 and not son.endswith(".") and not _MADDE_BASI.match(son):
                kenar = son
                govde = "\n".join(satirlar[:-1]).strip()
        etiket = _madde_etiketi(m.group("tur"), m.group("no"))
        parca = MaddeParcasi(etiket, govde, mulga=bool(_MULGA.search(govde[:200])),
                             atiflar=atiflari_bul(govde))
        parcalar.append(parca)
        if kenar and i + 1 < len(eslesmeler):
            parcalar.append(MaddeParcasi("__kenar__", kenar))

    # Kenar başlıklarını sonraki maddeye taşı
    sonuc: list[MaddeParcasi] = []
    bekleyen = ""
    ilk_kenar = ""
    if giris:
        giris_satirlar = giris.split("\n")
        son = giris_satirlar[-1].strip()
        if 0 < len(son) <= 80 and not son.endswith("."):
            ilk_kenar = son
            giris = "\n".join(giris_satirlar[:-1]).strip()
        if giris:
            sonuc.append(MaddeParcasi("Giriş", giris))
    bekleyen = ilk_kenar
    for p in parcalar:
        if p.madde_no == "__kenar__":
            bekleyen = p.metin
            continue
        if bekleyen:
            p.baslik = bekleyen
            bekleyen = ""
        sonuc.append(p)
    return sonuc
