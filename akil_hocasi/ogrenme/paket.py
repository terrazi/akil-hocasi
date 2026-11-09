"""Öğrenme paketleri: bir bilgisayarın öğrendiğini diğerlerine taşır (sunucu gerekmez).

Paket (.ahp) = ZIP içinde paket.json + özet. İçerik kişisel veri taşımaz (TC/IBAN maskeli):
terim karşılıkları, OCR düzeltmeleri, kaynak puanları, doğrulanmış soru-cevaplar, örnek cevaplar.
İçe aktarmada sayısal öğrenmeler makine başına tutulur (aynı paket iki kez sayılmaz);
gelen soru-cevaplar 'yeniden_dogrulanacak' olarak girer ve gece yerel kütüphaneyle doğrulanır.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

from ..core.maskeleme import metni_maskele

PAKET_SURUMU = 1


def paket_icerigi(ogr) -> dict:
    db = ogr.db
    return {
        "surum": PAKET_SURUMU,
        "makine": ogr.makine,
        "olusturma": datetime.now().isoformat(timespec="seconds"),
        "es_anlam": [{"a": r["a"], "b": r["b"], "sayi": r["sayi"]} for r in db.execute("SELECT * FROM ogr_es_anlam")],
        "ocr": [{"yanlis": r["yanlis"], "dogru": r["dogru"], "sayi": r["sayi"]} for r in db.execute("SELECT * FROM ogr_ocr")],
        "kaynak": [{"anahtar": r["anahtar"], "puan": r["puan"]} for r in db.execute("SELECT * FROM ogr_kaynak")],
        "soru_cevap": [{"soru": metni_maskele(r["soru"]), "kisa_cevap": metni_maskele(r["kisa_cevap"]),
                        "dayanak": json.loads(r["dayanak"]), "kaynaklar": json.loads(r["kaynaklar"])}
                       for r in db.execute("SELECT * FROM soru_cevap WHERE durum='dogrulandi'")],
        "ornek": [{"soru": r["soru"], "cikti": r["cikti"], "etiketler": json.loads(r["etiketler"])}
                  for r in db.execute("SELECT * FROM ogr_ornek WHERE kaynak='yerel'")],
    }


def paket_olustur(ogr, yol: Path | str) -> Path:
    veri = json.dumps(paket_icerigi(ogr), ensure_ascii=False, indent=1).encode("utf-8")
    yol = Path(yol)
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix(".tmp")
    with zipfile.ZipFile(gecici, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("paket.json", veri)
        z.writestr("ozet.sha256", hashlib.sha256(veri).hexdigest())
    gecici.replace(yol)
    return yol


def paket_ice_aktar(ogr, yol: Path | str) -> dict:
    with zipfile.ZipFile(yol) as z:
        veri = z.read("paket.json")
        if z.read("ozet.sha256").decode().strip() != hashlib.sha256(veri).hexdigest():
            raise ValueError("Paket bozuk: özet tutmuyor")
    p = json.loads(veri.decode("utf-8"))
    makine = str(p.get("makine", "bilinmeyen"))
    if makine == ogr.makine:
        return {"atlandi": "kendi paketi"}
    sha = hashlib.sha256(veri).hexdigest()
    db = ogr.db
    onceki = db.execute("SELECT sha FROM ogr_paket_alim WHERE makine=?", (makine,)).fetchone()
    if onceki and onceki["sha"] == sha:
        return {"atlandi": "değişiklik yok"}
    yeni_sc = yeni_ornek = 0
    with db:
        # Makinenin önceki katkısını bu paketle değiştir (çift sayım olmaz)
        db.execute("DELETE FROM ogr_paylasilan WHERE makine=?", (makine,))
        for e in p.get("es_anlam", []):
            db.execute("INSERT OR REPLACE INTO ogr_paylasilan VALUES(?,?,?,?)",
                       (makine, "es_anlam", f"{e['a']}→{e['b']}", float(e["sayi"])))
        for e in p.get("ocr", []):
            db.execute("INSERT OR REPLACE INTO ogr_paylasilan VALUES(?,?,?,?)",
                       (makine, "ocr", f"{e['yanlis']}→{e['dogru']}", float(e["sayi"])))
        for e in p.get("kaynak", []):
            db.execute("INSERT OR REPLACE INTO ogr_paylasilan VALUES(?,?,?,?)",
                       (makine, "kaynak", e["anahtar"], float(e["puan"])))
        for o in p.get("ornek", []):
            yeni_ornek += db.execute(
                "INSERT OR IGNORE INTO ogr_ornek(soru, cikti, etiketler, zaman, kaynak) VALUES(?,?,?,?,?)",
                (o["soru"], o["cikti"], json.dumps(o.get("etiketler", []), ensure_ascii=False),
                 datetime.now().isoformat(timespec="seconds"), f"paket:{makine}")).rowcount
        db.execute("INSERT OR REPLACE INTO ogr_paket_alim VALUES(?,?,?)",
                   (makine, sha, datetime.now().isoformat(timespec="seconds")))
    for sc in p.get("soru_cevap", []):
        if not db.execute("SELECT 1 FROM soru_cevap WHERE soru=?", (sc["soru"],)).fetchone():
            sid = ogr.k.soru_cevap_kaydet(sc["soru"], sc["kisa_cevap"], sc["dayanak"], sc["kaynaklar"])
            with db:   # yerel kütüphaneyle doğrulanana kadar kullanılmaz
                db.execute("UPDATE soru_cevap SET durum='yeniden_dogrulanacak' WHERE id=?", (sid,))
            yeni_sc += 1
    if ogr.duzeltici is not None:
        ogr.duzeltici.ogrenilmis.update(ogr.ocr_duzeltmeleri())
    return {"makine": makine, "soru_cevap": yeni_sc, "ornek": yeni_ornek}


def _dosya_adi(makine: str) -> str:
    return "AkilHocasi-" + re.sub(r"[^A-Za-z0-9_-]", "_", makine)[:60] + ".ahp"


def esitle(ogr, klasor: Path | str) -> str:
    """Kendi paketini ortak klasöre yazar, diğer bilgisayarların paketlerini alır."""
    klasor = Path(klasor)
    if not klasor.is_dir():
        return f"klasöre ulaşılamadı: {klasor}"
    paket_olustur(ogr, klasor / _dosya_adi(ogr.makine))
    alinan = 0
    for dosya in sorted(klasor.glob("*.ahp")):
        if dosya.name == _dosya_adi(ogr.makine):
            continue
        try:
            sonuc = paket_ice_aktar(ogr, dosya)
            alinan += int("makine" in sonuc)
        except (ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
            continue
    return f"paket yazıldı, {alinan} bilgisayardan yeni öğrenme alındı"


def paket_baytlari(ogr) -> bytes:
    tampon = io.BytesIO()
    veri = json.dumps(paket_icerigi(ogr), ensure_ascii=False).encode("utf-8")
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("paket.json", veri)
        z.writestr("ozet.sha256", hashlib.sha256(veri).hexdigest())
    return tampon.getvalue()
