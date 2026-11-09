"""Gelen yazının çözümlenmesi: başlık (gönderen idare), sayı, tarih, konu, muhatap, ilgi, istenenler, süre.

Metin OCR, Word ya da PDF'ten gelir. Alanlar yalnızca metinde gerçekten bulunuyorsa doldurulur; bulunamayan
alan boş kalır ve taslakta kullanıcıya sorulur (uydurulmaz).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ..core.turkce import katla, nfc, tr_upper
from .dil import konu_bicimi, tarih_bicimi, yalin

_SAYI = re.compile(r"Say[ıi]\s*:?\s*([EZO]-\d{3,}(?:-[\w.]+)*-\d+|[A-ZÇĞİÖŞÜ0-9][\w./-]*\d)", re.I)
_TARIH = re.compile(r"(?<![\d.])(\d{1,2})[./](\d{1,2})[./](\d{4})(?![\d])")
_KONU = re.compile(r"^\s*Konu\s*:\s*(.+)$", re.I | re.M)
_ILGI = re.compile(r"^\s*[İI]lgi\s*:\s*(.+?)(?=\n\s*\n|\n\s*[A-ZÇĞİÖŞÜ][a-zçğıöşü]+\s|\Z)", re.I | re.M | re.S)
_IVEDILIK = re.compile(r"\b(ACELE|GÜNLÜDÜR)\b")
_SURE = re.compile(r"(\d{1,2}[./]\d{1,2}[./]\d{4}\s+tarihine\s+kadar|\d+\s*\(\w+\)\s*(?:iş\s+)?gün\s+içinde|"
                   r"\d+\s*(?:iş\s+)?gün\s+içinde|en geç\s+[^.]{3,40})", re.I)
_ISTEK = re.compile(r"talep edilmektedir|istenmektedir|gerekmektedir|gönderilmesi|bildirilmesi|iletilmesi|"
                    r"hazırlanması|yapılması|sağlanması|incelenmesi|değerlendirilmesi|doldurulması|katılım|"
                    r"tamamlanması|görüşünüzün|görüşlerinizin", re.I)
_KALIP = re.compile(r"^(?:Bilgilerinizi|Gereğini|Bilgilerinize|Bilgi ve gereğini)[^.]*(?:arz|rica)[^.]*ederim\.?$|"
                    r"^(?:Saygılarımla|Bilgilerinize sunulur)\.?$", re.I)


def cumleler(metin: str) -> list[str]:
    """Cümlelere böler; tarih ve sayılardaki noktalar bölme yeri sayılmaz."""
    duz = re.sub(r"\s*\n\s*", " ", metin)
    return [c.strip() for c in re.split(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ(\"“])", duz) if c.strip()]
_IDARE_SONU = re.compile(r"(REKTÖRLÜĞÜ|ÜNİVERSİTESİ|BAKANLIĞI|BAŞKANLIĞI|MÜDÜRLÜĞÜ|DEKANLIĞI|VALİLİĞİ|KURUMU|"
                         r"KURULU|MÜŞAVİRLİĞİ|ENSTİTÜSÜ|FAKÜLTESİ|YÜKSEKOKULU|KOORDİNATÖRLÜĞÜ|SEKRETERLİĞİ)\b")


@dataclass
class GelenYazi:
    idare: str = ""                       # gönderen idare (başlığın büyük harfli satırı)
    birim: str = ""                       # gönderen birim (başlığın son satırı)
    sayi: str = ""
    tarih: str = ""
    konu: str = ""
    muhatap: str = ""
    ilgiler: list[str] = field(default_factory=list)
    istenenler: list[str] = field(default_factory=list)
    sure: str = ""
    ivedilik: str = ""
    metin: str = ""
    imzalayan: str = ""

    def sozluk(self) -> dict:
        return asdict(self)

    def ozet(self) -> str:
        satirlar = []
        if self.idare or self.birim:
            satirlar.append(f"Gönderen: {' / '.join(x for x in (self.idare, self.birim) if x)}")
        if self.tarih or self.sayi:
            satirlar.append(f"Tarih/sayı: {self.tarih or '—'} / {self.sayi or '—'}")
        if self.konu:
            satirlar.append(f"Konu: {self.konu}")
        if self.istenenler:
            satirlar.append("İstenen: " + " ".join(self.istenenler[:3]))
        if self.sure:
            satirlar.append(f"Süre: {self.sure}")
        if self.ivedilik:
            satirlar.append(f"İvedilik: {self.ivedilik}")
        return "\n".join(satirlar)


def _satirlar(metin: str) -> list[str]:
    return [s.strip() for s in nfc(metin).replace("\r", "").split("\n")]


def _baslik(satirlar: list[str]) -> tuple[str, str]:
    """(idare, birim): 'T.C.' satırından sonraki büyük harfli satır(lar) idare, ardından gelen satır birimdir."""
    for i, s in enumerate(satirlar[:12]):
        if re.fullmatch(r"T\.\s?C\.?", s.replace(" ", "")):
            parcalar = []
            for s2 in satirlar[i + 1:i + 5]:
                if not s2 or re.match(r"(Say[ıi]|Konu|Tarih)\s*:", s2, re.I):
                    break
                parcalar.append(s2)
            idare = " ".join(p for p in parcalar if p == tr_upper(p))
            birim = " ".join(p for p in parcalar if p != tr_upper(p))
            return idare, birim
    for s in satirlar[:8]:                      # T.C. satırı okunamadıysa: idare adıyla biten ilk büyük harfli satır
        if s and s == tr_upper(s) and _IDARE_SONU.search(s):
            return s, ""
    return "", ""


def _muhatap(satirlar: list[str]) -> str:
    """Konu satırından sonra gelen, büyük harfli ve yönelme ekiyle biten ilk satır (ve parantezli birim satırı)."""
    basla = next((i for i, s in enumerate(satirlar) if re.match(r"Konu\s*:", s, re.I)), 0)
    for i in range(basla + 1, min(len(satirlar), basla + 8)):
        s = satirlar[i]
        if s and s == tr_upper(s) and re.search(r"(N[AE]|Ğ[AE]|Y[AE]|LERİNE|LARINA)$", s.rstrip(")")):
            ek = satirlar[i + 1] if i + 1 < len(satirlar) and satirlar[i + 1].startswith("(") else ""
            return (s + (" " + ek if ek else "")).strip()
        if s.lower().startswith("sayın "):
            return s
    return ""


def _imzalayan(satirlar: list[str]) -> str:
    """Metnin sonundaki 'Ad SOYAD' + unvan satırları (Ek:/Dağıtım: öncesi)."""
    son = next((i for i, s in enumerate(satirlar) if re.match(r"(Ek|Ekler|Dağıtım)\s*:", s, re.I)), len(satirlar))
    for i in range(son - 1, max(0, son - 8), -1):
        s = satirlar[i]
        if re.fullmatch(r"(?:(?:Prof|Doç|Dr|Öğr|Arş)\.?\s*(?:Gör|Üyesi)?\.?\s*)*[A-ZÇĞİÖŞÜ][a-zçğıöşü]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]+)*"
                        r"\s+[A-ZÇĞİÖŞÜ]{2,}", s):
            unvan = satirlar[i + 1] if i + 1 < son else ""
            return f"{s} — {unvan}".strip(" —")
    return ""


def cozumle(metin: str) -> GelenYazi:
    metin = nfc(metin or "")
    satirlar = _satirlar(metin)
    g = GelenYazi(metin=metin.strip())
    g.idare, g.birim = _baslik(satirlar)
    m = _SAYI.search(metin)
    if m:
        g.sayi = re.sub(r"\s+", "", m.group(1))
    # Tarih: sayı satırında (sağda) ya da "Tarih:" alanında; yoksa ilk tarih
    tarih_satiri = next((s for s in satirlar if re.match(r"Say[ıi]\s*:", s, re.I) and _TARIH.search(s)), "")
    tm = _TARIH.search(tarih_satiri) or re.search(r"Tarih\s*:\s*(\d{1,2})[./](\d{1,2})[./](\d{4})", metin, re.I)
    if tm:
        g.tarih = tarih_bicimi(f"{tm.group(1)}.{tm.group(2)}.{tm.group(3)}")
    k = _KONU.search(metin)
    if k:
        g.konu = konu_bicimi(k.group(1))
    g.muhatap = _muhatap(satirlar)
    il = _ILGI.search(metin)
    if il:
        g.ilgiler = [re.sub(r"\s+", " ", x).strip() for x in re.split(r"\n\s*(?=[a-zçğıöşü]\)\s)", il.group(1)) if x.strip()]
    govde = metin
    km = re.search(r"^\s*[İI]lgi\s*:.*?(?:\n\s*\n)", metin, re.I | re.M | re.S) or _KONU.search(metin)
    if km:
        govde = metin[km.end():]
    for x in cumleler(govde):
        if (15 < len(x) < 400 and _ISTEK.search(x) and not _KALIP.match(x) and x not in g.istenenler
                and not re.match(r"(Say[ıi]|Konu|İlgi|Ek)\s*:", x, re.I)):
            g.istenenler.append(x)
    s = _SURE.search(metin)
    if s:
        g.sure = s.group(1).strip()
    iv = _IVEDILIK.search("\n".join(satirlar[:6]))
    if iv:
        g.ivedilik = iv.group(1)
    g.imzalayan = _imzalayan(satirlar)
    return g


def cevap_muhatabi(g: GelenYazi, kendi_idare: str) -> tuple[str, str]:
    """Cevap yazısının muhatabı (ad, parantezli birim). Aynı idare içinde birime, başka idareye idare adıyla
    (birim varsa parantez içinde alt satırda, md. 14) yazılır."""
    ayni = bool(g.idare and kendi_idare and katla(g.idare) == katla(kendi_idare))
    if ayni and g.birim:
        return yalin(g.birim), ""
    if g.idare:
        return yalin(g.idare), (g.birim if g.birim else "")
    return yalin(g.birim), ""
