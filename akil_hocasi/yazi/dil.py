"""Resmî yazı dil araçları: Türkçe büyük harf, konu biçimi, yönelme (-e) ve ilgi (-in) hâl ekleri, sayı biçimi."""

from __future__ import annotations

import re

from ..core.turkce import nfc, tr_lower, tr_upper

_UNLULER = "aeıioöuüAEIİOÖUÜâîûÂÎÛ"
_KALIN = set("aıouAIOUâûÂÛ")
_YUVARLAK = set("oöuüOÖUÜûÛ")
# Konu satırında olduğu gibi korunan kısaltmalar (yalnızca büyük harf ve rakamdan oluşan sözcükler de korunur)
_KORUNAN = re.compile(r"^(?:[A-ZÇĞİÖŞÜ0-9]{2,}[./-]?)+$|^\d")


def son_unlu(sozcuk: str) -> str:
    for c in reversed(sozcuk):
        if c in _UNLULER:
            return c
    return "e"


def _uyum2(sozcuk: str, kalin: str, ince: str) -> str:
    return kalin if son_unlu(sozcuk) in _KALIN else ince


def _uyum4(sozcuk: str) -> str:
    u = son_unlu(sozcuk)
    if u in _KALIN:
        return "u" if u in _YUVARLAK else "ı"
    return "ü" if u in _YUVARLAK else "i"


def _son_sozcuk(ad: str) -> tuple[str, str]:
    ad = ad.rstrip()
    i = max(ad.rfind(" "), ad.rfind("("))
    return ad[:i + 1], ad[i + 1:]


def _hal_eki(sozcuk: str, yonelme: bool) -> str:
    """Kurum adının son sözcüğüne yönelme (-e) ya da ilgi (-in) eki (küçük harfle; büyütme çağırana kalır)."""
    kucuk = tr_lower(sozcuk)
    if not kucuk:
        return ""
    son = kucuk[-1]
    if son in "ıiuü":                    # iyelik ekli ad: Başkanlığı → Başkanlığına / Başkanlığının
        return "n" + (_uyum2(kucuk, "a", "e") if yonelme else _uyum4(kucuk) + "n")
    if son in "aeoöâ":                    # ünlüyle biten yalın ad: Sayıştay değil, ör. "Ajansı" dışı durumlar
        return ("y" + _uyum2(kucuk, "a", "e")) if yonelme else ("n" + _uyum4(kucuk) + "n")
    return _uyum2(kucuk, "a", "e") if yonelme else (_uyum4(kucuk) + "n")


def _yumusat(sozcuk: str) -> str:
    """Çok heceli sözcüklerde sondaki k → ğ (Müdürlük → Müdürlüğe)."""
    hece = sum(1 for c in sozcuk if c in _UNLULER)
    if hece >= 2 and sozcuk[-1:] in ("k", "K"):
        return sozcuk[:-1] + ("Ğ" if sozcuk[-1] == "K" else "ğ")
    return sozcuk


_YONELME_SONU = re.compile(r"(?:[ıiuü]n[ae]|y[ae]|[^aeıioöuü][ae])$")


def yonelme_eki_var_mi(ad: str) -> bool:
    """Muhatap adı zaten yönelme hâlinde mi (… BAŞKANLIĞINA, … MÜDÜRLÜĞÜNE, … REKTÖRLÜĞÜNE)?"""
    _, son = _son_sozcuk(ad)
    k = tr_lower(son).rstrip(")")
    return len(k) > 4 and bool(re.search(r"(?:[ıiuü]n[ae]|ğ[ae]|[ıiuü]y[ae])$", k))


def yonelme(ad: str) -> str:
    """Kurum adını yönelme hâline getirir: 'Personel Daire Başkanlığı' → 'Personel Daire Başkanlığına'."""
    ad = nfc(ad).strip()
    if not ad or yonelme_eki_var_mi(ad):
        return ad
    bas, son = _son_sozcuk(ad)
    buyuk = son.isupper()
    kok = son
    if not tr_lower(son)[-1:] in "aeıioöuüâ":
        kok = _yumusat(son)
    ek = _hal_eki(son, True)
    return bas + kok + (tr_upper(ek) if buyuk else ek)


def yalin(ad: str) -> str:
    """Yönelme hâlindeki kurum adını yalın hâle döndürür: 'BAŞKANLIĞINA' → 'BAŞKANLIĞI', 'Müdürlüğe' → 'Müdürlük'."""
    ad = nfc(ad).strip()
    if not yonelme_eki_var_mi(ad):
        return ad
    bas, son = _son_sozcuk(ad)
    k = tr_lower(son)
    if re.search(r"[ıiuü]n[ae]$", k) or re.search(r"[ıiuü]y[ae]$", k):
        son = son[:-2]
    elif re.search(r"ğ[ae]$", k):
        son = son[:-2] + ("K" if son.isupper() else "k")
    return bas + son


def ilgi_hali(ad: str) -> str:
    """Kurum adını ilgi (tamlayan) hâline getirir: 'Personel Daire Başkanlığı' → 'Personel Daire Başkanlığının'."""
    ad = yalin(ad)
    if not ad:
        return ad
    bas, son = _son_sozcuk(ad)
    k = tr_lower(son)
    if re.search(r"n[ıiuü]n$", k) and len(k) > 5:      # zaten ilgi hâlinde
        return ad
    buyuk = son.isupper()
    kok = son if k[-1:] in "aeıioöuüâ" else _yumusat(son)
    ek = _hal_eki(son, False)
    return bas + kok + (tr_upper(ek) if buyuk else ek)


def muhatap_bicimi(ad: str) -> str:
    """İdare muhatabı: büyük harf ve yönelme hâli (Md. 14)."""
    return tr_upper(yonelme(ad))


KISALTMALAR = {"T.C.", "TC", "TOGÜ", "YÖK", "SGK", "KBS", "MYS", "HYS", "EBYS", "KEP", "KVKK", "ÖSYM", "TÜBİTAK",
               "BAP", "DETSİS", "TL", "ABD", "AB", "TBMM", "MEB", "YÖKSİS", "HİTAP", "ÖYP", "KPSS", "ALES", "YDS",
               "e-Devlet", "SKS", "BİDB", "İMİD", "PDB", "SGDB", "KİK", "EKAP", "DMO", "TMO", "KDV", "ÖTV", "AR-GE"}
_BAGLAC = {"ve", "ile", "veya", "ya", "da", "de", "ki", "ya da"}


def konu_bicimi(konu: str) -> str:
    """Konu: sözcüklerin ilk harfleri büyük, sonda noktalama yok (Md. 13). Kısaltma ve kodlar korunur; bağlaçlar
    (ve, ile, veya, da/de, ki) Türkçe yazım kuralındaki gibi küçük kalır; sondaki "hk." açık yazılır."""
    konu = re.sub(r"\s+", " ", nfc(konu)).strip()
    konu = re.sub(r"\s+hk\.?$", " Hakkında", konu, flags=re.I).rstrip(".,;:!?…")
    tumu_buyuk = konu == tr_upper(konu)          # tamamı büyük yazılmışsa yalnız bilinen kısaltmalar korunur
    sozcukler = []
    for i, s in enumerate(konu.split(" ")):
        korunur = (s.strip("().,") in KISALTMALAR or bool(re.match(r"^\d", s))) if tumu_buyuk else bool(_KORUNAN.match(s))
        if not s or korunur:
            sozcukler.append(s)
            continue
        if i and tr_lower(s) in _BAGLAC:
            sozcukler.append(tr_lower(s))
            continue
        parcalar = s.split("-")
        sozcukler.append("-".join((tr_upper(p[:1]) + tr_lower(p[1:])) if p else p for p in parcalar))
    return " ".join(sozcukler)


def baslik_birimi(ad: str) -> str:
    """Başlığın birim satırı: ilk harfler büyük, diğerleri küçük (Md. 10). Kısaltmalar korunur."""
    return konu_bicimi(ad)


def kisi_adi(ad: str, soyad: str = "") -> str:
    """Ad ilk harfi büyük, SOYAD büyük harf (Md. 14, 17). Tek alanda verilirse son sözcük soyad sayılır."""
    if not soyad:
        parcalar = nfc(ad).split()
        if len(parcalar) < 2:
            return nfc(ad).strip()
        ad, soyad = " ".join(parcalar[:-1]), parcalar[-1]
    adlar = " ".join(tr_upper(p[:1]) + tr_lower(p[1:]) for p in nfc(ad).split())
    return f"{adlar} {tr_upper(soyad.strip())}".strip()


_PARA = re.compile(r"(?<![\d.,])(\d{4,})(?:,(\d+))?(?=\s*(?:TL|₺|Türk [Ll]irası|lira|avro|Avro|euro|Euro|dolar|ABD Doları))")


def sayilari_grupla(metin: str) -> str:
    """Parasal tutarlarda dört ve daha fazla haneli sayıları üçlü gruplara ayırır (Md. 16): 12500 TL → 12.500 TL.
    Yıl, sayı, madde ve kodlar değiştirilmez (yalnız para birimiyle biten tutarlar)."""
    def grupla(m: re.Match) -> str:
        tam = f"{int(m.group(1)):,}".replace(",", ".")
        return tam + (f",{m.group(2)}" if m.group(2) else "")
    return _PARA.sub(grupla, metin)


def tarih_bicimi(metin: str) -> str:
    """Gün ve ay iki hane, yıl dört hane, ayırıcı nokta (Md. 12): 1/2/2026 → 01.02.2026."""
    def duzelt(m: re.Match) -> str:
        g, a, y = m.group(1), m.group(2), m.group(3)
        if len(y) == 2:
            return m.group(0)
        return f"{int(g):02d}.{int(a):02d}.{y}"
    return re.sub(r"(?<![\d.])(\d{1,2})[./](\d{1,2})[./](\d{4})(?![\d])", duzelt, metin)
