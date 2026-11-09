"""Model indirici: Hugging Face'ten (ya da kurum içi aynadan / ortak klasörden) GGUF model dosyası alır.

- Dosya adı, depodaki dosya listesinden katalog deseniyle çözümlenir; boyut ve sha256 aynı listeden gelir.
- İndirme yarıda kalırsa kaldığı yerden sürer (HTTP Range); bitince sha256 doğrulanır, sonra yerine konur.
- Kurum ağında Hugging Face kapalıysa: "ayna" adresi (aynı yol yapısı) ya da model dosyalarının konduğu ortak
  klasör kullanılabilir; ortak klasördeki dosya da sha256 ile doğrulanır.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import shutil
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from .katalog import ModelTanimi

log = logging.getLogger("akilhocasi")
HF = "https://huggingface.co"
KULLANICI_AJANI = "AkilHocasi/0.1 (+https://github.com/terrazi/akil-hocasi)"
PARCA = 1024 * 1024


class IndirmeHatasi(RuntimeError):
    pass


def _istek(url: str, basliklar: dict | None = None, zaman_asimi: float = 30):
    r = urllib.request.Request(url, headers={"User-Agent": KULLANICI_AJANI, **(basliklar or {})})
    return urllib.request.urlopen(r, timeout=zaman_asimi)  # noqa: S310 - yalnız https model kaynakları


def sha256_dosya(yol: Path, ilerleme: Callable[[int, int], None] | None = None) -> str:
    h = hashlib.sha256()
    toplam = yol.stat().st_size
    okunan = 0
    with open(yol, "rb") as f:
        while parca := f.read(8 * PARCA):
            h.update(parca)
            okunan += len(parca)
            if ilerleme:
                ilerleme(okunan, toplam)
    return h.hexdigest()


class ModelIndirici:
    def __init__(self, klasor: Path, ayna: str = "", ortak_klasor: str = ""):
        self.klasor = Path(klasor)
        self.klasor.mkdir(parents=True, exist_ok=True)
        self.taban = (ayna or HF).rstrip("/")
        self.ortak = Path(ortak_klasor) if ortak_klasor else None

    # ------------------------------------------------------------------ çözümleme
    def cozumle(self, m: ModelTanimi) -> dict:
        """Depodaki dosyayı bulur: {"dosya", "boyut", "sha256", "url"}."""
        url = f"{self.taban}/api/models/{m.depo}/tree/main?recursive=true"
        try:
            with _istek(url) as y:
                liste = json.loads(y.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise IndirmeHatasi(f"Model listesi alınamadı ({m.depo}): {e}") from e
        adaylar = [d for d in liste if d.get("type") == "file" and m.dosya_eslesir(d.get("path", ""))]
        if not adaylar:
            raise IndirmeHatasi(f"{m.depo} deposunda '{m.desen}' desenine uyan dosya yok")
        d = min(adaylar, key=lambda x: (x["path"].count("/"), len(x["path"])))
        lfs = d.get("lfs") or {}
        sha = lfs.get("oid") or lfs.get("sha256") or ""
        boyut = int(lfs.get("size") or d.get("size") or 0)
        return {"dosya": d["path"].rsplit("/", 1)[-1], "yol": d["path"], "boyut": boyut, "sha256": sha,
                "url": f"{self.taban}/{m.depo}/resolve/main/{quote(d['path'])}"}

    def hedef_yolu(self, dosya: str) -> Path:
        return self.klasor / dosya

    # ------------------------------------------------------------------ indirme
    def indir(self, m: ModelTanimi, ilerleme: Callable[[int, int, str], None] | None = None,
              durdur: threading.Event | None = None) -> Path:
        """Modeli indirir (ya da ortak klasörden alır), doğrular ve yanına üst bilgi dosyası yazar."""
        bilgi = self.cozumle(m)
        hedef = self.hedef_yolu(bilgi["dosya"])
        bildir = ilerleme or (lambda a, b, c: None)
        if hedef.is_file() and self._dogru_mu(hedef, bilgi, bildir):
            self._ust_bilgi_yaz(hedef, m, bilgi)
            return hedef
        if self.ortak and (self.ortak / bilgi["dosya"]).is_file():
            bildir(0, bilgi["boyut"], "Ortak klasörden kopyalanıyor")
            gecici = hedef.with_suffix(hedef.suffix + ".part")
            shutil.copyfile(self.ortak / bilgi["dosya"], gecici)
            if not self._dogru_mu(gecici, bilgi, bildir):
                gecici.unlink(missing_ok=True)
                raise IndirmeHatasi("Ortak klasördeki dosya doğrulanamadı (sha256 uyuşmuyor)")
            gecici.replace(hedef)
            self._ust_bilgi_yaz(hedef, m, bilgi)
            return hedef
        self._http_indir(bilgi, hedef, bildir, durdur)
        self._ust_bilgi_yaz(hedef, m, bilgi)
        return hedef

    def _http_indir(self, bilgi: dict, hedef: Path, bildir, durdur) -> None:
        gecici = hedef.with_suffix(hedef.suffix + ".part")
        for deneme in range(5):
            mevcut = gecici.stat().st_size if gecici.exists() else 0
            if bilgi["boyut"] and mevcut > bilgi["boyut"]:
                gecici.unlink()
                mevcut = 0
            basliklar = {"Range": f"bytes={mevcut}-"} if mevcut else {}
            try:
                with _istek(bilgi["url"], basliklar, zaman_asimi=60) as y:
                    if mevcut and y.status != 206:          # sunucu kaldığı yerden vermiyor: baştan
                        mevcut = 0
                    with open(gecici, "ab" if mevcut else "wb") as f:
                        alinan = mevcut
                        son = time.monotonic()
                        while parca := y.read(PARCA):
                            if durdur is not None and durdur.is_set():
                                raise IndirmeHatasi("İndirme durduruldu (kaldığı yerden sürdürülebilir)")
                            f.write(parca)
                            alinan += len(parca)
                            if time.monotonic() - son > 0.5:
                                bildir(alinan, bilgi["boyut"], "İndiriliyor")
                                son = time.monotonic()
                if bilgi["boyut"] and gecici.stat().st_size < bilgi["boyut"]:
                    raise http.client.IncompleteRead(b"", bilgi["boyut"] - gecici.stat().st_size)  # kopma: sürdür
                break
            except IndirmeHatasi:
                raise
            except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException) as e:
                if deneme == 4:
                    raise IndirmeHatasi(f"İndirme başarısız: {e}") from e
                log.info("İndirme kesildi, yeniden deneniyor (%s): %s", deneme + 1, e)
                time.sleep(2 + deneme * 3)
        if bilgi["boyut"] and gecici.stat().st_size != bilgi["boyut"]:
            raise IndirmeHatasi("İndirilen dosyanın boyutu beklenenden farklı; yeniden deneyin")
        if not self._dogru_mu(gecici, bilgi, bildir):
            gecici.unlink(missing_ok=True)
            raise IndirmeHatasi("İndirilen dosya doğrulanamadı (sha256 uyuşmuyor); silindi")
        gecici.replace(hedef)

    @staticmethod
    def _dogru_mu(yol: Path, bilgi: dict, bildir) -> bool:
        if bilgi["boyut"] and yol.stat().st_size != bilgi["boyut"]:
            return False
        if not bilgi["sha256"]:
            return True                    # depo sha vermediyse boyut denetimi yeterli sayılır
        bildir(0, yol.stat().st_size, "Doğrulanıyor")
        return sha256_dosya(yol, lambda a, b: bildir(a, b, "Doğrulanıyor")) == bilgi["sha256"]

    @staticmethod
    def _ust_bilgi_yaz(yol: Path, m: ModelTanimi, bilgi: dict) -> None:
        yol.with_suffix(".json").write_text(json.dumps(
            {"kimlik": m.kimlik, "ad": m.ad, "tur": m.tur, "depo": m.depo, "dosya": bilgi["dosya"],
             "boyut": bilgi["boyut"], "sha256": bilgi["sha256"], "baglam": m.baglam, "dusunme": m.dusunme,
             "ek": m.ek}, ensure_ascii=False, indent=2), encoding="utf-8")


def kurulu_modeller(klasor: Path) -> list[dict]:
    """Model klasöründeki doğrulanmış modeller (üst bilgi dosyası olanlar)."""
    cikti = []
    for js in sorted(Path(klasor).glob("*.json")):
        try:
            bilgi = json.loads(js.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        gguf = js.with_suffix(".gguf")
        if gguf.is_file() and bilgi.get("kimlik"):
            bilgi["yol"] = str(gguf)
            cikti.append(bilgi)
    return cikti
