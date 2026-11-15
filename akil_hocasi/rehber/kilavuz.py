"""Kullanım kılavuzu ayrıştırıcı: PDF / Word / HTML kılavuzu sayfa ve bölümlerine böler.

Her bölüm için: başlık, sayfa aralığı, metin, işlem adımları, arayüz etiketleri (düğme, menü, sekme, alan adları)
ve menü yolları ("Ana Sayfa >> Kısayollar >> Evrak Yaz") çıkarılır. Hiçbir şey üretilmez: her etiket ve adım
kılavuzun kendi metninden alınır; cevap doğrulaması da bu metinle yapılır.

Ayıklananlar: her sayfada tekrar eden üst/alt bilgi satırları, içindekiler sayfaları, sayfa numaraları.
"""

from __future__ import annotations

import io
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from ..core.turkce import bosluk_normalle, katla, nfc
from ..library.ayristirici import MaddeParcasi

KILAVUZ_TURLERI = ("kilavuz", "kilavuz_yerel")
EN_UZUN_BOLUM = 6000          # karakter; daha uzun bölüm sayfa sayfa bölünür
EN_KISA_BOLUM = 60


@dataclass
class Satir:
    metin: str
    boyut: float = 0.0
    kalin: bool = False


@dataclass
class Sayfa:
    no: int
    satirlar: list[Satir] = field(default_factory=list)

    @property
    def metin(self) -> str:
        return "\n".join(s.metin for s in self.satirlar)


@dataclass
class KilavuzBolumu:
    no: str                    # sayfa ya da sayfa aralığı: "12", "12-14"; sayfasız biçimlerde "b3"
    baslik: str
    sayfa_bas: int
    sayfa_son: int
    metin: str
    adimlar: list[str] = field(default_factory=list)
    etiketler: list[str] = field(default_factory=list)
    yollar: list[str] = field(default_factory=list)

    def madde(self) -> MaddeParcasi:
        return MaddeParcasi(madde_no=self.no, metin=self.metin, baslik=self.baslik[:200])


@dataclass
class KilavuzBelgesi:
    baslik: str
    tur: str                   # pdf | docx | html
    sayfa_sayisi: int
    bolumler: list[KilavuzBolumu]
    yayimlayan: str = ""
    tarih: str = ""
    surum: str = ""
    taranmis: bool = False     # metin katmanı yok (taranmış görüntü PDF)

    @property
    def metin(self) -> str:
        return "\n\n".join(f"{b.baslik}\n{b.metin}" for b in self.bolumler)

    def maddeler(self) -> list[MaddeParcasi]:
        return [b.madde() for b in self.bolumler]

    def ozet(self) -> dict:
        return {"baslik": self.baslik, "tur": self.tur, "sayfa": self.sayfa_sayisi, "bolum": len(self.bolumler),
                "adim": sum(len(b.adimlar) for b in self.bolumler),
                "etiket": len({e for b in self.bolumler for e in b.etiketler}),
                "yol": len({y for b in self.bolumler for y in b.yollar}),
                "yayimlayan": self.yayimlayan, "tarih": self.tarih, "surum": self.surum, "taranmis": self.taranmis}


# ====================================================================== okuma

def pdf_sayfalari(veri: bytes) -> list[Sayfa]:
    """PDF'i satır satır okur (yazı boyutu ve kalınlık ile). Önce PyMuPDF, yoksa pdfplumber."""
    try:
        import fitz  # PyMuPDF (programla gelir)
    except ImportError:
        fitz = None
    if fitz is not None:
        sayfalar = []
        with fitz.open(stream=veri, filetype="pdf") as belge:
            for i, s in enumerate(belge, 1):
                satirlar = []
                for blok in s.get_text("dict").get("blocks", []):
                    for satir in blok.get("lines", []):
                        parcalar = [p for p in satir.get("spans", []) if p.get("text", "").strip()]
                        if not parcalar:
                            continue
                        metin = "".join(p["text"] for p in parcalar)
                        uzun = sum(len(p["text"]) for p in parcalar) or 1
                        boyut = sum(p.get("size", 0) * len(p["text"]) for p in parcalar) / uzun
                        kalin_uz = sum(len(p["text"]) for p in parcalar
                                       if (p.get("flags", 0) & 16) or "bold" in p.get("font", "").lower())
                        satirlar.append(Satir(bosluk_normalle(metin), round(boyut, 1), kalin_uz * 2 > uzun))
                sayfalar.append(Sayfa(i, satirlar))
        return sayfalar
    import pdfplumber  # yedek okuyucu (geliştirme ortamı ve testler)
    sayfalar = []
    with pdfplumber.open(io.BytesIO(veri)) as belge:
        for i, s in enumerate(belge.pages, 1):
            kelimeler = s.extract_words(extra_attrs=["size", "fontname"], keep_blank_chars=False, use_text_flow=True)
            gruplar: dict[int, list[dict]] = {}
            for k in kelimeler:
                gruplar.setdefault(round(k["top"] / 3), []).append(k)
            satirlar = []
            for _, grup in sorted(gruplar.items()):
                grup.sort(key=lambda k: k["x0"])
                metin = " ".join(k["text"] for k in grup)
                uzun = sum(len(k["text"]) for k in grup) or 1
                boyut = sum(k["size"] * len(k["text"]) for k in grup) / uzun
                kalin_uz = sum(len(k["text"]) for k in grup if "bold" in k.get("fontname", "").lower())
                satirlar.append(Satir(bosluk_normalle(metin), round(boyut, 1), kalin_uz * 2 > uzun))
            sayfalar.append(Sayfa(i, satirlar))
    return sayfalar


def pdf_icindekiler(veri: bytes) -> list[tuple[int, str, int]]:
    """PDF'in kendi içindekiler (yer imi) listesi: (düzey, başlık, sayfa). Yoksa boş."""
    try:
        import fitz
    except ImportError:
        return []
    try:
        with fitz.open(stream=veri, filetype="pdf") as belge:
            return [(int(d), bosluk_normalle(b), int(s)) for d, b, s, *_ in belge.get_toc(simple=True) if s > 0]
    except Exception:  # noqa: BLE001 - bozuk yer imi listesi yok sayılır
        return []


def docx_sayfalari(veri: bytes) -> list[Sayfa]:
    """Word belgesini tek "sayfa" satırları olarak okur; başlık biçemleri kalın + büyük sayılır."""
    import docx

    belge = docx.Document(io.BytesIO(veri))
    satirlar = []
    for p in belge.paragraphs:
        metin = bosluk_normalle(p.text)
        if not metin:
            continue
        stil = (p.style.name or "").lower() if p.style is not None else ""
        baslik = stil.startswith(("heading", "başlık", "baslik", "title"))
        kalin = baslik or (bool(p.runs) and all(r.bold for r in p.runs if r.text.strip()))
        satirlar.append(Satir(metin, 16.0 if baslik else 11.0, kalin))
    for tablo in belge.tables:
        for satir in tablo.rows:
            hucreler = [bosluk_normalle(h.text) for h in satir.cells]
            metin = " | ".join(h for h in dict.fromkeys(hucreler) if h)
            if metin:
                satirlar.append(Satir(metin, 11.0, False))
    return [Sayfa(1, satirlar)]


def html_sayfalari(veri: bytes | str) -> list[Sayfa]:
    from bs4 import BeautifulSoup

    corba = BeautifulSoup(veri, "lxml")
    for etiket in corba(["script", "style", "nav", "header", "footer", "noscript", "form", "iframe", "aside",
                         "button", "select"]):
        etiket.decompose()
    sablon = re.compile(r"(?:^|[-_ ])(?:nav|navbar|menu|menü|header|footer|sidebar|breadcrumb|modal|popup|cookie|"
                        r"social|share|paylas|slider|banner|duyuru-bandi|top-bar|topbar|overlay|lightbox|dialog|"
                        r"fancybox|announcement|notice)(?:$|[-_ ])", re.IGNORECASE)

    for el in corba.find_all(True):
        if el.attrs is None:
            continue
        ad = " ".join(el.get("class") or []) + " " + str(el.get("id") or "") + " " + str(el.get("role") or "")
        if sablon.search(ad) and el.name not in ("html", "body", "main", "article"):
            el.decompose()
    for liste in corba.find_all(["ul", "ol"]):           # bağlantı yoğun listeler (site menüsü, kısayollar)
        metin = bosluk_normalle(liste.get_text(" "))
        baglanti = sum(len(bosluk_normalle(a.get_text(" "))) for a in liste.find_all("a"))
        if metin and baglanti >= 0.6 * len(metin) and len(liste.find_all("a")) >= 4:
            liste.decompose()
    govde = corba.find("main") or corba.find("article") or corba.body or corba
    satirlar = []
    boyutlar = {"h1": 22.0, "h2": 18.0, "h3": 15.0, "h4": 13.0}
    for el in govde.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "dt", "dd", "pre"]):
        if el.find(["p", "li", "td"]) is not None and el.name in ("li", "td"):
            continue
        metin = bosluk_normalle(el.get_text(" "))
        if not metin:
            continue
        if el.name == "li":
            metin = "• " + metin
        satirlar.append(Satir(metin, boyutlar.get(el.name, 11.0), el.name in boyutlar))
    return [Sayfa(1, satirlar)]


def html_basligi(veri: bytes | str) -> str:
    """Sayfanın kendi başlığı: ilk h1, yoksa <title> (site adı ekleri " | ", " - " sonrası atılır)."""
    from bs4 import BeautifulSoup

    corba = BeautifulSoup(veri, "lxml")
    h1 = corba.find("h1")
    if h1 and 4 <= len(bosluk_normalle(h1.get_text(" "))) <= 160:
        return bosluk_normalle(h1.get_text(" "))
    if corba.title and corba.title.string:
        return re.split(r"\s[|–-]\s", bosluk_normalle(corba.title.string))[0][:160]
    return ""


# ====================================================================== temizlik

_SAYFA_NO = re.compile(r"^(?:sayfa\s*)?\d{1,4}(?:\s*(?:/|of|-)\s*\d{1,4})?$", re.IGNORECASE)
_ICINDEKILER_SATIRI = re.compile(r"(?:\.{4,}|…{2,}|(?:\. ){4,})\s*\d{1,4}\s*$")


def _imza(metin: str) -> str:
    return re.sub(r"\d+", "#", katla(metin)).strip()


def tekrarlayanlari_ayikla(sayfalar: list[Sayfa]) -> list[Sayfa]:
    """Sayfaların başında/sonunda tekrar eden üst-alt bilgi satırlarını ve yalın sayfa numaralarını atar."""
    if len(sayfalar) >= 3:
        sayac: Counter[str] = Counter()
        for s in sayfalar:
            uc = s.satirlar[:3] + s.satirlar[-3:]
            sayac.update({_imza(x.metin) for x in uc})
        esik = max(3, int(len(sayfalar) * 0.5))
        tekrar = {i for i, n in sayac.items() if n >= esik and len(i) <= 160}
    else:
        tekrar = set()
    sonuc = []
    for s in sayfalar:
        kalan = []
        for j, x in enumerate(s.satirlar):
            kenar = j < 3 or j >= len(s.satirlar) - 3
            if _SAYFA_NO.match(x.metin.strip()) or (kenar and _imza(x.metin) in tekrar):
                continue
            kalan.append(x)
        sonuc.append(Sayfa(s.no, kalan))
    return sonuc


def icindekiler_sayfasi_mi(s: Sayfa) -> bool:
    if not s.satirlar:
        return False
    nokta = sum(1 for x in s.satirlar if _ICINDEKILER_SATIRI.search(x.metin))
    ilk = katla(" ".join(x.metin for x in s.satirlar[:3]))
    return nokta >= 4 or (("icindekiler" in ilk or "contents" in ilk) and nokta >= 2)


def icindekiler_basliklari(sayfalar: list[Sayfa]) -> list[tuple[str, int]]:
    """İçindekiler sayfasındaki "Başlık ........ 12" satırlarından (başlık, sayfa) çiftleri."""
    sonuc = []
    for s in sayfalar:
        if not icindekiler_sayfasi_mi(s):
            continue
        for x in s.satirlar:
            m = re.match(r"^(.{3,120}?)\s*(?:\.{3,}|…+|(?:\. ){3,})\s*(\d{1,4})\s*$", x.metin)
            if m:
                sonuc.append((bosluk_normalle(m.group(1).strip(" .")), int(m.group(2))))
    return sonuc


# ====================================================================== çıkarım

_NUMARALI_BASLIK = re.compile(r"^(?:\d{1,2}(?:\.\d{1,2}){0,3}[.)]?|[IVX]{1,5}[.)]|[A-H][.)])\s+\S")
_ADIM = re.compile(
    r"^\s*(?:(?:adım|adim)\s*\d+\s*[:.)-]?|\d{1,2}\s*[-.)]\s*(?=\D)|[a-hı]\)\s|[•●▪■◦○o\-–]\s+|[\uf0b7\uf0d8\uf0a7\uf076\uf0fc\uf0e8]\s*)",
    re.IGNORECASE)
_EYLEM = re.compile(
    r"\b(tıkla\w*|seç(?:ilir|iniz|in|ilerek|ilmeli)\w*|gir(?:ilir|iniz|in|ilerek|ilmeli)\w*|bas(?:ılır|ınız|ın|ılarak)\w*|"
    r"yazıl\w*|kaydedil\w*|onayla\w*|açılan\w*|ekranından|menüsünden|sekmesinden|butonuna|düğmesine|"
    r"işaretlen\w*|yüklen\w*|imzala\w*|gönderil\w*|listelen\w*|sorgula\w*|doldurul\w*)",
    re.IGNORECASE)
_ARAYUZ_ADI = (r"(?:butonu(?:na|nu|ndan)?|düğmesi(?:ne|ni|nden)?|tuşu(?:na|nu)?|menüsü(?:ne|nü|nden)?|"
               r"sekmesi(?:ne|ni|nden)?|ekranı(?:na|nı|ndan)?|alanı(?:na|nı|ndan)?|seçeneği(?:ne|ni)?|"
               r"linki(?:ne|ni)?|bağlantısı(?:na|nı)?|penceresi(?:ne|ni|nden)?|kutucuğu(?:na|nu)?|"
               r"ikonu(?:na|nu)?|simgesi(?:ne|ni)?|başlığı(?:na|nı|ndan)?)")
_TIRNAKLI = re.compile(r"[\"“”«]\s*([^\"“”«»\n]{2,60}?)\s*[\"”“»]|‘\s*([^‘’\n]{2,60}?)\s*’")
_ONCESI_BUYUK = re.compile(
    r"((?:[A-ZÇĞİÖŞÜ0-9][\wÇĞİÖŞÜçğıöşü./+-]*\s+){0,4}[A-ZÇĞİÖŞÜ][\wÇĞİÖŞÜçğıöşü./+-]*)\s+" + _ARAYUZ_ADI + r"\b")
_YOL_AYRAC = re.compile(r"\s*(?:>>|»|→|-->|–>|—>|->|>)\s*")
_YAYIMLAYANLAR = (
    "Muhasebat Genel Müdürlüğü", "Hazine ve Maliye Bakanlığı", "Sosyal Güvenlik Kurumu", "Yükseköğretim Kurulu",
    "Kamu İhale Kurumu", "Cumhurbaşkanlığı İnsan Kaynakları Ofisi", "Ölçme, Seçme ve Yerleştirme Merkezi",
    "Kamu Sertifikasyon Merkezi", "Tokat Gaziosmanpaşa Üniversitesi", "Strateji ve Bütçe Başkanlığı",
    "Çalışma ve Sosyal Güvenlik Bakanlığı",
)
_AYLAR = "ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık"
_TARIH = re.compile(rf"\b(\d{{1,2}}[./]\d{{1,2}}[./](?:19|20)\d{{2}})\b|\b(({_AYLAR})\s*[-/ ]?\s*(?:19|20)\d{{2}})\b",
                    re.IGNORECASE)
_SURUM = re.compile(r"\b(?:versiyon|version|sürüm(?:\s*no)?|v)\s*[:.]?\s*(\d{1,2}(?:\.\d{1,3}){0,2})\b", re.IGNORECASE)


def _temiz_etiket(e: str) -> str:
    e = bosluk_normalle(e).strip(" .,:;-–—'\"“”‘’()[]")
    return e


def etiketleri_bul(metin: str) -> list[str]:
    """Arayüz etiketleri: tırnak içindeki adlar ve "X butonu/menüsü/sekmesi/ekranı/alanı" kalıbındaki X."""
    bulunan: list[str] = []
    for m in _TIRNAKLI.finditer(metin):
        e = _temiz_etiket(m.group(1) or m.group(2) or "")
        if 2 <= len(e) <= 60 and not e.isdigit() and len(e.split()) <= 8:
            bulunan.append(e)
    for m in _ONCESI_BUYUK.finditer(metin):
        e = _temiz_etiket(m.group(1))
        # cümle başındaki büyük harfli sıradan sözcükleri (Açılan, Bu, Ardından...) atla
        kelimeler = e.split()
        while kelimeler and katla(kelimeler[0]) in _SIRADAN_BAS:
            kelimeler = kelimeler[1:]
        e = " ".join(kelimeler)
        if 2 <= len(e) <= 60:
            bulunan.append(e)
    return list(dict.fromkeys(bulunan))


_SIRADAN_BAS = {"acilan", "bu", "su", "o", "ardindan", "daha", "sonra", "once", "ilgili", "yukarida", "asagida",
                "sayfanin", "ekranin", "ekrandaki", "ana", "sol", "sag", "ust", "alt", "her", "tum", "yeni", "gelen",
                "sistem", "kullanici", "kullanicilar", "ve", "ile", "veya", "ya", "da", "de", "icin", "olarak"}


def yollari_bul(metin: str) -> list[str]:
    """Menü yolları: en az iki parçalı, ">", ">>", "→", "-->" ile ayrılmış başlık dizileri."""
    sonuc = []
    for satir in metin.splitlines():
        if not _YOL_AYRAC.search(satir):
            continue
        parcalar = [_temiz_etiket(p) for p in _YOL_AYRAC.split(satir)]
        # baştaki/sondaki cümle parçalarını kırp: yol parçaları kısa olmalı
        parcalar = [p for p in parcalar if p]
        if len(parcalar) < 2:
            continue
        # ilk parça: sondaki büyük harfle başlayan sözcük dizisi ("ilgili birimin KBS Saymanlık İşlemleri" → KBS ...)
        ilk = _buyuk_dizi(parcalar[0].split()[::-1])[::-1]
        # son parça: baştaki büyük harfle başlayan sözcük dizisi ("Yeni menüsünden işlem başlatılır" → Yeni)
        son = _buyuk_dizi(parcalar[-1].split())
        parcalar = [" ".join(ilk)] + parcalar[1:-1] + [" ".join(son)]
        if all(2 <= len(p) <= 50 for p in parcalar) and sum(p[:1].isupper() for p in parcalar) >= len(parcalar) - 1:
            sonuc.append(" > ".join(parcalar))
    return list(dict.fromkeys(sonuc))


def _buyuk_dizi(kelimeler: list[str]) -> list[str]:
    dizi = []
    for k in kelimeler:
        if not k or not (k[0].isupper() or k[0].isdigit() or k[0] in "eE" and "-" in k[:3]):
            break
        dizi.append(k)
        if len(dizi) >= 6:
            break
    return dizi


def adimlari_bul(satirlar: list[str]) -> list[str]:
    """İşlem adımları: numaralı/madde imli satırlar ve eylem bildiren kısa cümleler (kılavuzdaki sırasıyla)."""
    adimlar: list[str] = []
    for s in satirlar:
        t = s.strip()
        if len(t) < 6:
            continue
        if _ADIM.match(t) or (len(t) <= 260 and _EYLEM.search(t)):
            adimlar.append(_ADIM.sub("", t, count=1).strip() or t)
    return list(dict.fromkeys(adimlar))


def ust_bilgi(sayfalar: list[Sayfa]) -> tuple[str, str, str]:
    """(yayımlayan, tarih, sürüm) — ilk iki sayfadan."""
    on = "\n".join(s.metin for s in sayfalar[:2])
    k = katla(on)
    yayimlayan = next((y for y in _YAYIMLAYANLAR if katla(y) in k), "")
    m = _TARIH.search(on)
    tarih = (m.group(1) or m.group(2)) if m else ""
    m = _SURUM.search(on)
    surum = m.group(1) if m else ""
    return yayimlayan, tarih, surum


def _govde_boyutu(sayfalar: list[Sayfa]) -> float:
    boyutlar = []
    for s in sayfalar:
        for x in s.satirlar:
            if x.boyut:
                boyutlar.extend([x.boyut] * min(len(x.metin), 200))
    return statistics.median(boyutlar) if boyutlar else 0.0


def _baslik_mi(x: Satir, govde: float) -> bool:
    t = x.metin.strip()
    if not (3 <= len(t) <= 90) or _ICINDEKILER_SATIRI.search(t):
        return False
    if t.endswith((",", ";")) or t[0].islower() or sum(c.isalpha() for c in t) < 3:
        return False
    if govde and x.boyut >= govde * 1.18:
        return True
    if x.kalin and not t.endswith(".") and len(t.split()) <= 12:
        return True
    harfler = [c for c in t if c.isalpha()]
    if len(harfler) >= 6 and all(c.isupper() for c in harfler) and len(t.split()) <= 10:
        return True
    return bool(_NUMARALI_BASLIK.match(t)) and len(t.split()) <= 12 and not t.endswith(".")


def _bolum_kur(baslik: str, parcalar: list[tuple[int, str]]) -> KilavuzBolumu | None:
    satirlar = [m for _, m in parcalar]
    metin = "\n".join(satirlar).strip()
    if not metin and not baslik:
        return None
    sayfalar = [n for n, _ in parcalar] or [0]
    bas, son = min(sayfalar), max(sayfalar)
    no = str(bas) if bas == son else f"{bas}-{son}"
    tum = "\n".join(_ADIM.sub("", s, count=1) for s in ((baslik + "\n" + metin) if baslik else metin).splitlines())
    return KilavuzBolumu(no=no, baslik=baslik or (satirlar[0][:90] if satirlar else ""), sayfa_bas=bas,
                         sayfa_son=son, metin=metin, adimlar=adimlari_bul(satirlar),
                         etiketler=etiketleri_bul(tum), yollar=yollari_bul(tum))


def bolumlere_ayir(sayfalar: list[Sayfa], yer_imleri: list[tuple[int, str, int]] | None = None) -> list[KilavuzBolumu]:
    """Sayfaları başlıklara göre bölümlere ayırır; başlık yoksa her sayfa bir bölüm olur (sunum, ekran kılavuzu)."""
    sayfalar = [s for s in tekrarlayanlari_ayikla(sayfalar) if not icindekiler_sayfasi_mi(s)]
    if len(sayfalar) > 2 and sayfalar[0].no == 1 and len(sayfalar[0].satirlar) <= 8 \
            and len(sayfalar[0].metin) <= 400:
        sayfalar = sayfalar[1:]                         # kapak sayfası (başlık, kurum, tarih) bölüm sayılmaz
    govde = _govde_boyutu(sayfalar)
    hedef_basliklar = {katla(b): sy for _, b, sy in (yer_imleri or [])}

    # başlık satırlarını işaretle
    akis: list[tuple[int, Satir, bool]] = []
    for s in sayfalar:
        for x in s.satirlar:
            akis.append((s.no, x, katla(x.metin.strip()) in hedef_basliklar or _baslik_mi(x, govde)))
    baslik_sayisi = sum(1 for _, _, b in akis if b)
    if baslik_sayisi < 2 or baslik_sayisi > max(8, len(akis) * 0.45):
        # başlık yapısı güvenilmez: sayfa başına bölüm (ilk kısa satır sayfa başlığı sayılır)
        bolumler = []
        for s in sayfalar:
            if not s.satirlar:
                continue
            ilk = s.satirlar[0].metin
            baslik = ilk if len(ilk) <= 90 else ""
            govde_satirlari = [(s.no, x.metin) for x in (s.satirlar[1:] if baslik else s.satirlar)]
            b = _bolum_kur(baslik, govde_satirlari)
            if b:
                bolumler.append(b)
        return _birlestir_ve_bol(bolumler)

    bolumler, baslik, parca = [], "", []
    onceki_baslik_sayfa, onceki_boyut = None, 0.0
    for no, x, b in akis:
        if b:
            # aynı boyda art arda gelen başlık satırları tek başlıktır ("2.1 Kurum İçi" + "Gidecek Evrak Yaz")
            if baslik and not parca and onceki_baslik_sayfa == no and abs(x.boyut - onceki_boyut) < 0.6 \
                    and len(baslik) + len(x.metin) <= 110 and not _NUMARALI_BASLIK.match(x.metin.strip()):
                baslik = f"{baslik} {x.metin.strip()}"
                continue
            if baslik or parca:
                yeni = _bolum_kur(baslik, parca)
                if yeni:
                    bolumler.append(yeni)
            baslik, parca, onceki_baslik_sayfa, onceki_boyut = x.metin.strip(), [], no, x.boyut
        else:
            parca.append((no, x.metin))
    yeni = _bolum_kur(baslik, parca)
    if yeni:
        bolumler.append(yeni)
    return _birlestir_ve_bol(bolumler)


def _birlestir_ve_bol(bolumler: list[KilavuzBolumu]) -> list[KilavuzBolumu]:
    sonuc: list[KilavuzBolumu] = []
    bekleyen: KilavuzBolumu | None = None
    for b in bolumler:
        if bekleyen is not None and not sonuc and not bekleyen.metin:
            bekleyen = None                            # belgenin en üstündeki içeriksiz başlık: belge/bölüm adı
        if bekleyen is not None:                       # içeriksiz başlığı sonrakine kat
            b = _bolum_kur(f"{bekleyen.baslik} — {b.baslik}" if b.baslik else bekleyen.baslik,
                           [(bekleyen.sayfa_bas, bekleyen.metin)] * bool(bekleyen.metin)
                           + [(n, m) for n, m in _satirlar_sayfali(b)]) or b
            bekleyen = None
        if len(b.metin) < EN_KISA_BOLUM and not b.adimlar:
            bekleyen = b
            continue
        if len(b.metin) > EN_UZUN_BOLUM and b.sayfa_son > b.sayfa_bas:
            sonuc.extend(_sayfalara_bol(b))
        else:
            sonuc.append(b)
    if bekleyen is not None and (bekleyen.metin or not sonuc):
        sonuc.append(bekleyen)
    return sonuc


def _satirlar_sayfali(b: KilavuzBolumu) -> list[tuple[int, str]]:
    # bölüm içi satırların sayfası tutulmadığından ilk sayfaya yazılır; sayfa aralığı korunur
    satirlar = b.metin.splitlines()
    if not satirlar:
        return []
    return [(b.sayfa_bas, s) for s in satirlar[:-1]] + [(b.sayfa_son, satirlar[-1])]


def _sayfalara_bol(b: KilavuzBolumu) -> list[KilavuzBolumu]:
    satirlar = b.metin.splitlines()
    parca_boyu = max(1, len(satirlar) // max(1, b.sayfa_son - b.sayfa_bas + 1))
    sonuc = []
    for i in range(0, len(satirlar), parca_boyu):
        sayfa = min(b.sayfa_son, b.sayfa_bas + i // parca_boyu)
        yeni = _bolum_kur(b.baslik + (" (devam)" if i else ""), [(sayfa, s) for s in satirlar[i:i + parca_boyu]])
        if yeni:
            sonuc.append(yeni)
    return sonuc


def _baslik_bul(sayfalar: list[Sayfa], varsayilan: str) -> str:
    if not sayfalar or not sayfalar[0].satirlar:
        return varsayilan
    for s in sayfalar[:2]:                             # "… Uygulama Kılavuzu" satırı en iyi başlıktır
        for x in s.satirlar[:30]:
            k = katla(x.metin)
            if ("kilavuz" in k or "klavuz" in k) and 10 <= len(x.metin) <= 120 and not _ICINDEKILER_SATIRI.search(x.metin) \
                    and not k.startswith(("bu kilavuz", "kilavuzda", "kilavuzun")):
                return bosluk_normalle(x.metin)
    ilk = [x for x in sayfalar[0].satirlar[:25] if len(x.metin) >= 4]
    if not ilk:
        return varsayilan
    en_buyuk = max(x.boyut for x in ilk)
    if not en_buyuk:
        return varsayilan
    buyukler = [x.metin for x in ilk if x.boyut >= en_buyuk * 0.85][:4]
    baslik = ""
    for satir in buyukler:                             # başlık satırları, cümleye taşmadan (en çok ~100 karakter)
        aday = bosluk_normalle(f"{baslik} {satir}")
        if baslik and len(aday) > 100:
            break
        baslik = aday
    return baslik[:160] if len(baslik) >= 6 else varsayilan


def dosya_turu(veri: bytes, ad: str = "") -> str:
    if veri[:5] == b"%PDF-":
        return "pdf"
    if veri[:2] == b"PK" and (ad.lower().endswith(".docx") or b"word/" in veri[:4000]):
        return "docx"
    bas = veri[:600].lower()
    if b"<html" in bas or b"<!doctype html" in bas or ad.lower().endswith((".htm", ".html")):
        return "html"
    return ""


def ayristir(veri: bytes, ad: str = "", baslik: str = "") -> KilavuzBelgesi | None:
    """Kılavuz dosyasını ayrıştırır. Desteklenmeyen biçimde None döner."""
    tur = dosya_turu(veri, ad)
    if tur == "pdf":
        sayfalar = pdf_sayfalari(veri)
        yer_imleri = pdf_icindekiler(veri)
    elif tur == "docx":
        sayfalar, yer_imleri = docx_sayfalari(veri), []
    elif tur == "html":
        sayfalar, yer_imleri = html_sayfalari(veri), []
        baslik = baslik or html_basligi(veri)
    else:
        return None
    sayfalar = [Sayfa(s.no, [Satir(nfc(x.metin), x.boyut, x.kalin) for x in s.satirlar]) for s in sayfalar]
    metinli = sum(1 for s in sayfalar if len(s.metin.strip()) > 40)
    taranmis = tur == "pdf" and bool(sayfalar) and metinli <= max(1, len(sayfalar) // 10)
    yayimlayan, tarih, surum = ust_bilgi(sayfalar)
    ad_baslik = re.sub(r"[_-]+", " ", re.sub(r"\.\w{2,4}$", "", ad.rsplit("/", 1)[-1])).strip()
    belge_basligi = bosluk_normalle(baslik) or _baslik_bul(sayfalar, ad_baslik or "Kullanım kılavuzu")
    bolumler = [] if taranmis else bolumlere_ayir(sayfalar, yer_imleri)
    if tur != "pdf":                                   # sayfasız biçimlerde bölüm sırası numara olur
        for i, b in enumerate(bolumler, 1):
            b.no, b.sayfa_bas, b.sayfa_son = f"b{i}", 0, 0
    return KilavuzBelgesi(baslik=belge_basligi, tur=tur, sayfa_sayisi=len(sayfalar), bolumler=bolumler,
                          yayimlayan=yayimlayan, tarih=tarih, surum=surum, taranmis=taranmis)


def sayfa_goruntusu(dosya: str | bytes, sayfa: int, olcek: float = 1.6) -> bytes | None:
    """Yerel kılavuz PDF'inin bir sayfasını PNG olarak çizer (PyMuPDF). Çizilemezse None."""
    try:
        import fitz
    except ImportError:
        return None
    try:
        belge = fitz.open(stream=dosya, filetype="pdf") if isinstance(dosya, bytes) else fitz.open(dosya)
        with belge:
            if not 1 <= sayfa <= belge.page_count:
                return None
            pix = belge[sayfa - 1].get_pixmap(matrix=fitz.Matrix(olcek, olcek), alpha=False)
            return pix.tobytes("png")
    except Exception:  # noqa: BLE001 - bozuk/şifreli PDF
        return None


_CEVAP_TIRNAK = re.compile(r"[\"“”«]\s*([^\"“”«»\n]{2,60}?)\s*[\"”“»]")
_CEVAP_YOL = re.compile(r"(?:[^\s>»→][^>»→\n]{0,48}?\s*(?:>|»|→)\s*){1,6}[^>»→\n.,;:]{2,50}")


def arayuz_adlari(metin: str) -> list[str]:
    """Cevap cümlesindeki ekran/düğme/menü adları: çift tırnak içindekiler ve "A > B > C" yollarının parçaları.

    Kılavuz kaynaklı cümlede bu adların her biri kılavuz metninde geçmelidir (doğrulama motoru denetler).
    """
    adlar = [_temiz_etiket(m.group(1)) for m in _CEVAP_TIRNAK.finditer(metin)]
    for m in _CEVAP_YOL.finditer(metin):
        parcalar = [_temiz_etiket(x) for x in re.split(r"\s*(?:>|»|→)\s*", m.group(0))]
        parcalar = [x for x in parcalar if x]
        if len(parcalar) >= 2:
            parcalar[0] = " ".join(_buyuk_dizi(parcalar[0].split()[::-1])[::-1]) or parcalar[0]
            parcalar[-1] = " ".join(_buyuk_dizi(parcalar[-1].split())) or parcalar[-1]
            adlar.extend(parcalar)
    return [a for a in dict.fromkeys(adlar) if len(a) >= 2]


def kilavuz_etiketi(baslik: str, no: str, bolum_basligi: str = "") -> str:
    """Kaynak etiketi: "EBYS Eğitim Sunumu, s. 12 (Kurum İçi Gidecek Evrak Yaz)"."""
    if no and no[0].isdigit():
        yer = f"s. {no}"
    elif no.startswith("b") and no[1:].isdigit():
        yer = f"bölüm {no[1:]}"
    else:
        yer = no
    return f"{baslik}, {yer}" + (f" ({bolum_basligi[:60]})" if bolum_basligi and bolum_basligi != baslik else "")
