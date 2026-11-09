"""Çekirdek bilgi paketi: kurulumla gelen temel mevzuat (657, 2547, 5018, 4734, 6245, Resmî Yazışma Yönetmeliği…).

Derleme hattı bu metinleri resmî kaynaktan (mevzuat.gov.tr) indirir ve özgün dosyaları sha256 ile birlikte
pakete koyar. Program ilk açılışta, kütüphanesinde olmayanları aynı ayrıştırıcıyla işler; böylece internet
yokken de ilk gün temel mevzuattan kaynaklı cevap verir. Paket yalnızca başlangıçtır: tarayıcı aynı adresleri
düzenli kontrol eder ve resmî kaynaktaki güncel sürümü alır (paketteki sürüm eskiyse yenisiyle değişir).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

log = logging.getLogger("akilhocasi")
MANIFEST = "manifest.json"


def paket_klasoru() -> Path | None:
    adaylar = []
    if getattr(sys, "frozen", False):
        adaylar.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "bilgi_paketi")
    adaylar.append(Path(__file__).resolve().parents[2] / "derleme" / "bilgi_paketi")
    for a in adaylar:
        if (a / MANIFEST).is_file():
            return a
    return None


def paketi_yukle(tarayici, klasor: Path | None = None) -> dict:
    """Kütüphanede olmayan paket belgelerini işler. {"yeni": n, "atlanan": n, "hata": [..]}"""
    from ..crawler.indirici import IndirmeSonucu
    from ..crawler.tarayici import TaramaRaporu
    klasor = klasor or paket_klasoru()
    sonuc = {"yeni": 0, "atlanan": 0, "hata": []}
    if klasor is None or tarayici is None:
        return sonuc
    try:
        kayitlar = json.loads((klasor / MANIFEST).read_text("utf-8")).get("belgeler", [])
    except (OSError, ValueError) as e:
        sonuc["hata"].append(f"manifest okunamadı: {e}")
        return sonuc
    rapor = TaramaRaporu("bilgi_paketi")
    for k in kayitlar:
        if tarayici.kutuphane.belge_bilgisi(k["kimlik"]):
            sonuc["atlanan"] += 1
            continue
        dosya = klasor / k["dosya"]
        try:
            icerik = dosya.read_bytes()
        except OSError as e:
            sonuc["hata"].append(f"{k['kimlik']}: {e}")
            continue
        sha = hashlib.sha256(icerik).hexdigest()
        if sha != k.get("sha256"):
            sonuc["hata"].append(f"{k['kimlik']}: bütünlük denetimi başarısız")
            continue
        s = IndirmeSonucu(url=k["url"], durum=200, icerik=icerik, sha256=sha)
        try:
            durum = tarayici.belge_isle(s, rapor, tur=k["tur"], kimlik=k["kimlik"], baslik=k["baslik"],
                                        kaynak_turu=k.get("kaynak_turu", "Mevzuat"))
            # Tarayıcı aynı adresi sonra yeniden indirdiğinde, değişmemişse "değişmedi" sayılsın
            tarayici.kutuphane.kaynak_durumu_yaz(k["url"], "", "", sha)
            sonuc["yeni"] += int(durum == "yeni")
        except Exception as e:  # noqa: BLE001 - bir belgenin hatası diğerlerini durdurmaz
            sonuc["hata"].append(f"{k['kimlik']}: {e}")
    if sonuc["yeni"]:
        log.info("Çekirdek bilgi paketi: %d belge kütüphaneye işlendi", sonuc["yeni"])
    return sonuc
