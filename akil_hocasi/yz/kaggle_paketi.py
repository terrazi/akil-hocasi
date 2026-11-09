"""Kaggle eğitim paketi: programın bu bilgisayarda biriktirdiği bilgiyi bir sonraki Kaggle eğitimine taşır.

Paket (zip): kütüphane (mevzuat, TOGÜ belgeleri, anlam vektörleri, çalışma soruları) ve sorular.jsonl (altın soru
seti; kullanıcı izin verirse maskelenmiş gerçek sorular). Kaggle'daki 1. defter paketi veri seti olarak alır:
eğitim, programın gerçek kütüphanesi ve gerçek sorularla yapılır; model kurumun ihtiyacına uyar.

Gizlilik: kullanıcı soruları varsayılan olarak pakete girmez. İzin verilirse sorular yeniden maskelenir (T.C.
kimlik no, IBAN, telefon, e-posta…). Cevap günlükleri, ayarlar ve hata kayıtlarının metinleri hiçbir zaman girmez.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from ..core.maskeleme import metni_maskele

# Pakete hiç girmeyen (kişisel olabilecek) tablolar; izinle yalnız ogr_olaylar'ın soru metni sorular.jsonl'e girer
_KISISEL_TABLOLAR = ("ogr_olaylar", "ogr_ornek", "cek_hata", "ogr_degerlendirme")


def paket_olustur(kutuphane, hedef: str | Path, gercek_sorular: bool = False) -> dict:
    hedef = Path(hedef)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    sorular: list[dict] = []
    for r in kutuphane.db.execute("SELECT soru, beklenen_dayanak, beklenen_ifade FROM ogr_altin").fetchall():
        sorular.append({"id": f"altin-{len(sorular)}", "soru": metni_maskele(r["soru"]),
                        "dayanak": json.loads(r["beklenen_dayanak"] or "[]"), "kaynak": "altin"})
    if gercek_sorular:
        gorulen = {s["soru"] for s in sorular}
        for r in kutuphane.db.execute(
                "SELECT soru, durum, kaynaklar FROM ogr_olaylar ORDER BY id DESC LIMIT 5000").fetchall():
            soru = metni_maskele(r["soru"] or "").strip()
            if 10 <= len(soru) <= 600 and soru not in gorulen:
                gorulen.add(soru)
                sorular.append({"id": f"gercek-{len(sorular)}", "soru": soru, "dayanak": [], "kaynak": "gercek"})
    with tempfile.TemporaryDirectory() as gecici:
        db_yolu = Path(gecici) / "kutuphane.db"
        hedef_db = sqlite3.connect(db_yolu)
        with kutuphane._kilit:
            kutuphane.db.backup(hedef_db)
        for tablo in _KISISEL_TABLOLAR:
            try:
                hedef_db.execute(f"DELETE FROM {tablo}")  # noqa: S608 - sabit tablo adları
            except sqlite3.OperationalError:
                pass
        hedef_db.commit()
        hedef_db.execute("VACUUM")
        hedef_db.close()
        belge = kutuphane.db.execute("SELECT COUNT(*) FROM belgeler").fetchone()[0]
        madde = kutuphane.db.execute("SELECT COUNT(*) FROM maddeler WHERE yururluk_bitis IS NULL").fetchone()[0]
        manifest = {"olusturma": datetime.now().isoformat(timespec="seconds"), "belge": belge, "madde": madde,
                    "soru": len(sorular), "gercek_sorular": gercek_sorular,
                    "aciklama": "Akıl Hocası Kaggle eğitim paketi (1. deftere veri seti olarak ekleyin)"}
        with zipfile.ZipFile(hedef, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(db_yolu, "kutuphane.db")
            z.writestr("sorular.jsonl", "\n".join(json.dumps(s, ensure_ascii=False) for s in sorular))
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    manifest["dosya"] = str(hedef)
    manifest["boyut_mb"] = round(hedef.stat().st_size / 1e6, 1)
    return manifest
