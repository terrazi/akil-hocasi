"""Kaggle'da eğitilip programın GitHub sürümü olarak yayımlanan modeli bulur ve indirir.

Eğitim iş akışı, Kaggle'da eğitilen ve sınanan modeli "model-<kimlik>" etiketli bir sürüme koyar: GitHub tek
dosyada 2 GB sınırı koyduğu için GGUF parçalara bölünür; yanında model.json (parça listesi, sha256'lar, eğitim
ve sınav karnesi) bulunur. Program parçaları kaldığı yerden sürdürerek indirir, her parçayı ve birleşik dosyayı
sha256 ile doğrular, ardından "eğitilmiş model" olarak ekler (Kaggle kapısı ve bu bilgisayarın sınavı
geçerliyse kullanılır). Böylece bütün birim bilgisayarları aynı eğitilmiş modeli tek tıkla alır.
Yalnız okuma yapılır; hiçbir kurum sistemine bağlanılmaz.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from .indirici import IndirmeHatasi, ModelIndirici, _istek, sha256_dosya

log = logging.getLogger("akilhocasi")
DEPO = "terrazi/akil-hocasi"
API = "https://api.github.com"


def son_egitilmis(depo: str = DEPO, zaman_asimi: float = 20, api: str = API) -> dict | None:
    """En yeni eğitilmiş model sürümünün bildirimi (model.json) ve indirme adresleri; yoksa None."""
    try:
        with _istek(f"{api}/repos/{depo}/releases?per_page=30", {"Accept": "application/vnd.github+json"},
                    zaman_asimi) as y:
            surumler = json.loads(y.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 - çevrimdışı ya da erişim yok
        log.info("Eğitilmiş model sürümleri alınamadı: %s", e)
        return None
    for s in surumler:
        if not str(s.get("tag_name", "")).startswith("model-") or s.get("draft"):
            continue
        varliklar = {a["name"]: a["browser_download_url"] for a in s.get("assets", [])}
        if "model.json" not in varliklar:
            continue
        try:
            with _istek(varliklar["model.json"], zaman_asimi=zaman_asimi) as y:
                bildirim = json.loads(y.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            log.info("model.json okunamadı (%s): %s", s.get("tag_name"), e)
            continue
        if not bildirim_gecerli(bildirim, varliklar):
            continue
        bildirim["varliklar"] = varliklar
        bildirim["etiket"] = s["tag_name"]
        bildirim["yayin"] = s.get("published_at", "")
        return bildirim
    return None


def bildirim_gecerli(b: dict, varliklar: dict) -> bool:
    parcalar = b.get("parcalar") or []
    return bool(b.get("bilgi", {}).get("kimlik") and b.get("dosya", "").endswith(".gguf") and b.get("sha256")
                and parcalar and all(p.get("ad") in varliklar and p.get("sha256") and p.get("boyut") for p in parcalar))


def indir(bildirim: dict, klasor: Path, ilerleme: Callable[[int, int, str], None] | None = None,
          durdur: threading.Event | None = None) -> Path:
    """Parçaları indirir ve doğrular, birleştirir, birleşik dosyayı doğrular; yanına eğitim bilgisini yazar.
    Dönüş: GGUF dosyasının yolu (ardından yonetici.ozel_model_ekle ile eklenir)."""
    klasor = Path(klasor)
    klasor.mkdir(parents=True, exist_ok=True)
    bildir = ilerleme or (lambda a, b, c: None)
    toplam = sum(int(p["boyut"]) for p in bildirim["parcalar"])
    indirici = ModelIndirici(klasor)
    biten = 0
    yollar = []
    for i, p in enumerate(bildirim["parcalar"], 1):
        hedef = klasor / p["ad"]
        etiket = f"Parça {i}/{len(bildirim['parcalar'])} indiriliyor"
        bilgi = {"url": bildirim["varliklar"][p["ad"]], "boyut": int(p["boyut"]), "sha256": p["sha256"]}
        if not (hedef.is_file() and hedef.stat().st_size == bilgi["boyut"] and sha256_dosya(hedef) == bilgi["sha256"]):
            indirici._http_indir(bilgi, hedef, lambda a, b, c, o=biten, e=etiket: bildir(o + a, toplam, e), durdur)
        biten += bilgi["boyut"]
        yollar.append(hedef)
    gguf = klasor / bildirim["dosya"]
    gecici = gguf.with_suffix(".gguf.part")
    bildir(0, toplam, "Parçalar birleştiriliyor")
    with open(gecici, "wb") as cikis:
        for y in yollar:
            with open(y, "rb") as f:
                while parca := f.read(8 * 1024 * 1024):
                    cikis.write(parca)
    if sha256_dosya(gecici, lambda a, b: bildir(a, b, "Doğrulanıyor")) != bildirim["sha256"]:
        gecici.unlink(missing_ok=True)
        raise IndirmeHatasi("Birleştirilen model doğrulanamadı (sha256 uyuşmuyor); yeniden deneyin")
    gecici.replace(gguf)
    for y in yollar:
        y.unlink(missing_ok=True)
    gguf.with_suffix(".json").write_text(json.dumps({**bildirim["bilgi"], "dosya": gguf.name}, ensure_ascii=False,
                                                    indent=1), "utf-8")
    return gguf
