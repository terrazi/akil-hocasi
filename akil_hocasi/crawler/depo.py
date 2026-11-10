"""Belge Deposu: resmî sitelerden indirilen orijinal Word, Excel, PDF dosyalarının arşivi.

- Orijinal dosya değiştirilmeden saklanır; kullanıcı her zaman kopyayla çalışır.
- Her kayıt: kaynak bağlantısı, bulunduğu sayfa, belge kodu, RV, tarih, SHA-256, sürüm.
- Dosya türü uzantıdan değil içerikten doğrulanır; makrolu Office dosyaları işaretlenir
  ve kullanıcıya makrosu temizlenmiş kopya verilir.
- Windows'ta dosyalar "internetten geldi" işaretiyle (Mark of the Web) saklanır;
  Office bunları Korumalı Görünüm'de açar.
"""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import sqlite3
import sys
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..core.turkce import katla
from ..library.db import GuvenliBaglanti

UZANTI = {"pdf": ".pdf", "docx": ".docx", "docm": ".docm", "xlsx": ".xlsx", "xlsm": ".xlsm",
          "doc": ".doc", "xls": ".xls", "odt": ".odt", "ods": ".ods", "html": ".html", "pptx": ".pptx"}

_SEMA = """
CREATE TABLE IF NOT EXISTS belgeler (
    id INTEGER PRIMARY KEY,
    kod TEXT DEFAULT '',
    ad TEXT NOT NULL,
    tur TEXT NOT NULL,
    url TEXT NOT NULL,
    sayfa_url TEXT DEFAULT '',
    birim TEXT DEFAULT '',
    rv TEXT DEFAULT '',
    yayin_tarihi TEXT DEFAULT '',
    indirme_tarihi TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    boyut INTEGER NOT NULL,
    dosya_yolu TEXT NOT NULL,
    makrolu INTEGER DEFAULT 0,
    durum TEXT DEFAULT 'guncel'      -- guncel, eski, kaldirildi
);
CREATE INDEX IF NOT EXISTS ix_depo_kod ON belgeler(kod);
CREATE INDEX IF NOT EXISTS ix_depo_url ON belgeler(url);
"""


def dosya_turu(icerik: bytes) -> str | None:
    """Dosya türünü sihirli baytlardan ve ZIP içeriğinden belirler."""
    if icerik.startswith(b"%PDF"):
        return "pdf"
    if icerik.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        # Eski OLE biçimi: Word mü Excel mi?
        return "xls" if b"W\x00o\x00r\x00k\x00b\x00o\x00o\x00k" in icerik[:200_000] else "doc"
    if icerik.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(icerik)) as z:
                adlar = set(z.namelist())
                if "mimetype" in adlar:
                    mt = z.read("mimetype").decode("ascii", "ignore")
                    if "opendocument.text" in mt:
                        return "odt"
                    if "opendocument.spreadsheet" in mt:
                        return "ods"
                makro = any(a.lower().endswith("vbaproject.bin") for a in adlar)
                if any(a.startswith("word/") for a in adlar):
                    return "docm" if makro else "docx"
                if any(a.startswith("xl/") for a in adlar):
                    return "xlsm" if makro else "xlsx"
                if any(a.startswith("ppt/") for a in adlar):
                    return "pptx"
        except zipfile.BadZipFile:
            return None
        return None
    bas = icerik[:512].lstrip().lower()
    if bas.startswith(b"<!doctype html") or bas.startswith(b"<html") or b"<html" in bas:
        return "html"
    return None


def makrolu_mu(icerik: bytes) -> bool:
    tur = dosya_turu(icerik)
    if tur in ("docm", "xlsm"):
        return True
    if tur in ("doc", "xls"):
        return b"_VBA_PROJECT" in icerik or b"V\x00B\x00A" in icerik
    return False


_MAKRO_TURLERI = {
    "application/vnd.ms-word.document.macroEnabled.main+xml":
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    "application/vnd.ms-excel.sheet.macroEnabled.main+xml":
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
}


def makrosuz_kopya(icerik: bytes) -> tuple[bytes, str]:
    """docm/xlsm dosyasından VBA projesini çıkarıp docx/xlsx üretir. Dönüş: (içerik, yeni_tür)."""
    tur = dosya_turu(icerik)
    if tur not in ("docm", "xlsm"):
        return icerik, tur or ""
    giris = zipfile.ZipFile(io.BytesIO(icerik))
    cikis_tampon = io.BytesIO()
    with zipfile.ZipFile(cikis_tampon, "w", zipfile.ZIP_DEFLATED) as cikis:
        for oge in giris.infolist():
            ad = oge.filename
            al = ad.lower()
            if al.endswith("vbaproject.bin") or al.endswith("vbadata.xml") or "/_rels/vbaproject.bin.rels" in al:
                continue
            veri = giris.read(ad)
            if ad == "[Content_Types].xml":
                metin = veri.decode("utf-8")
                for eski, yeni in _MAKRO_TURLERI.items():
                    metin = metin.replace(eski, yeni)
                metin = re.sub(r'<Override[^>]*vbaProject[^>]*/>', "", metin, flags=re.IGNORECASE)
                metin = re.sub(r'<Override[^>]*vbaData[^>]*/>', "", metin, flags=re.IGNORECASE)
                metin = re.sub(r'<Default[^>]*Extension="bin"[^>]*/>', "", metin)
                veri = metin.encode("utf-8")
            elif al.endswith(".rels"):
                metin = veri.decode("utf-8")
                metin = re.sub(r'<Relationship[^>]*(?:vbaProject|vbaData)[^>]*/>', "", metin, flags=re.IGNORECASE)
                veri = metin.encode("utf-8")
            cikis.writestr(oge, veri)
    return cikis_tampon.getvalue(), ("docx" if tur == "docm" else "xlsx")


def _guvenli_ad(ad: str, en_uzun: int = 80) -> str:
    ad = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", ad).strip(" .")
    return ad[:en_uzun] or "belge"


def internet_isareti_koy(yol: Path, url: str) -> None:
    """Windows NTFS'te Zone.Identifier akışı yazar (Mark of the Web)."""
    if sys.platform != "win32":
        return
    try:
        with open(str(yol) + ":Zone.Identifier", "w", encoding="utf-8") as f:
            f.write(f"[ZoneTransfer]\r\nZoneId=3\r\nHostUrl={url}\r\n")
    except OSError:
        pass


class BelgeDeposu:
    def __init__(self, kok: Path | str, disk_siniri_mb: int = 2048):
        self.kok = Path(kok)
        self.kok.mkdir(parents=True, exist_ok=True)
        self.disk_siniri = disk_siniri_mb * 1024 * 1024
        self._kilit = threading.RLock()
        baglanti = sqlite3.connect(str(self.kok / "depo.db"), check_same_thread=False)
        baglanti.row_factory = sqlite3.Row
        self.db = GuvenliBaglanti(baglanti, self._kilit)        # tarayıcı ve arayüz aynı anda kullanır
        self.db.executescript(_SEMA)

    def kaydet(self, icerik: bytes, url: str, *, kod: str = "", ad: str = "", sayfa_url: str = "",
               birim: str = "", rv: str = "", yayin_tarihi: str = "") -> dict | None:
        """Dosyayı depoya ekler. Aynı içerik zaten varsa mevcut kaydı döndürür.

        Desteklenmeyen tür veya disk sınırı aşımında None döner.
        """
        tur = dosya_turu(icerik)
        if tur is None or tur == "html":
            return None
        sha = hashlib.sha256(icerik).hexdigest()
        with self._kilit, self.db:
            r = self.db.execute("SELECT * FROM belgeler WHERE sha256=?", (sha,)).fetchone()
            if r:
                return dict(r)
            if self._toplam_boyut() + len(icerik) > self.disk_siniri:
                return None
            u = urlparse(url)
            dosya_adi = _guvenli_ad(unquote(Path(u.path).stem) or kod or "belge")
            klasor = self.kok / _guvenli_ad(u.hostname or "yerel") / _guvenli_ad(kod or dosya_adi, 60)
            klasor.mkdir(parents=True, exist_ok=True)
            yol = klasor / f"{sha[:8]}_{dosya_adi}{UZANTI[tur]}"
            yol.write_bytes(icerik)
            internet_isareti_koy(yol, url)
            zaman = datetime.now().isoformat(timespec="seconds")
            if kod:
                self.db.execute("UPDATE belgeler SET durum='eski' WHERE kod=? AND durum='guncel'", (kod,))
            else:
                self.db.execute("UPDATE belgeler SET durum='eski' WHERE url=? AND durum='guncel'", (url,))
            bid = self.db.execute(
                "INSERT INTO belgeler(kod,ad,tur,url,sayfa_url,birim,rv,yayin_tarihi,indirme_tarihi,sha256,boyut,"
                "dosya_yolu,makrolu) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (kod, ad or dosya_adi, tur, url, sayfa_url, birim, rv, yayin_tarihi, zaman, sha, len(icerik),
                 str(yol), int(makrolu_mu(icerik)))).lastrowid
            return dict(self.db.execute("SELECT * FROM belgeler WHERE id=?", (bid,)).fetchone())

    def _toplam_boyut(self) -> int:
        return self.db.execute("SELECT COALESCE(SUM(boyut),0) FROM belgeler").fetchone()[0]

    def bul(self, kod: str) -> dict | None:
        r = self.db.execute(
            "SELECT * FROM belgeler WHERE kod=? ORDER BY (durum='guncel') DESC, id DESC LIMIT 1", (kod,)).fetchone()
        return dict(r) if r else None

    def surumler(self, kod: str) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM belgeler WHERE kod=? ORDER BY id DESC", (kod,))]

    def ara(self, metin: str = "", tur: str = "", birim: str = "", sadece_guncel: bool = True,
            limit: int = 200) -> list[dict]:
        kosul, deger = ["1=1"], []
        if sadece_guncel:
            kosul.append("durum='guncel'")
        if tur:
            kosul.append("tur LIKE ?")
            deger.append(f"{tur}%")
        if birim:
            kosul.append("birim=?")
            deger.append(birim)
        satirlar = [dict(r) for r in self.db.execute(
            f"SELECT * FROM belgeler WHERE {' AND '.join(kosul)} ORDER BY indirme_tarihi DESC", deger)]
        if metin:
            k = katla(metin)
            satirlar = [s for s in satirlar if k in katla(f"{s['kod']} {s['ad']} {s['birim']}")]
        return satirlar[:limit]

    def kopya_ver(self, kayit: dict, hedef_klasor: Path | str) -> Path:
        """Kullanıcıya kopya verir; makrolu dosyada makrosuz kopya üretir. Orijinal değişmez."""
        kaynak = Path(kayit["dosya_yolu"])
        hedef_klasor = Path(hedef_klasor)
        hedef_klasor.mkdir(parents=True, exist_ok=True)
        ad = _guvenli_ad(kayit.get("ad") or kaynak.stem)
        if kayit.get("makrolu") and kayit.get("tur") in ("docm", "xlsm"):
            icerik, yeni_tur = makrosuz_kopya(kaynak.read_bytes())
            hedef = hedef_klasor / f"{ad} (makrosuz){UZANTI[yeni_tur]}"
            hedef.write_bytes(icerik)
        else:
            hedef = hedef_klasor / f"{ad}{kaynak.suffix}"
            shutil.copyfile(kaynak, hedef)
        internet_isareti_koy(hedef, kayit.get("url", ""))
        return hedef


def metin_cikar(icerik: bytes, tur: str | None = None) -> str:
    """Kütüphaneye eklemek için dosyadan düz metin çıkarır (desteklenmeyen türde boş döner)."""
    tur = tur or dosya_turu(icerik)
    try:
        if tur == "pdf":
            try:
                import fitz  # PyMuPDF
            except ImportError:
                return ""
            with fitz.open(stream=icerik, filetype="pdf") as doc:
                return "\n".join(sayfa.get_text() for sayfa in doc)
        if tur in ("docx", "docm"):
            import docx
            belge = docx.Document(io.BytesIO(icerik))
            satirlar = [p.text for p in belge.paragraphs]
            for tablo in belge.tables:
                for satir in tablo.rows:
                    satirlar.append(" | ".join(h.text.strip() for h in satir.cells))
            return "\n".join(satirlar)
        if tur in ("xlsx", "xlsm"):
            import openpyxl
            kitap = openpyxl.load_workbook(io.BytesIO(icerik), read_only=True, data_only=True)
            satirlar = []
            for sayfa in kitap.worksheets:
                satirlar.append(f"[{sayfa.title}]")
                for satir in sayfa.iter_rows(values_only=True):
                    hucreler = [str(h) for h in satir if h is not None]
                    if hucreler:
                        satirlar.append(" | ".join(hucreler))
            return "\n".join(satirlar)
        if tur == "html":
            from bs4 import BeautifulSoup
            corba = BeautifulSoup(icerik, "lxml")
            for etiket in corba(["script", "style", "nav", "header", "footer"]):
                etiket.decompose()
            return corba.get_text("\n")
    except Exception:
        return ""
    return ""
