"""Derleme hattı için küçük test modellerini programın kendi indiricisiyle indirir.

Kullanım: python paketleme/test_modelleri.py <klasör>
Paket öz testi bu klasörü AKILHOCASI_MODELLER ile kullanarak gerçek llama-server ile uçtan uca sınama yapar.
İndirme başarısız olursa uyarı verir ve 0 döner (öz test model adımını atlar; derleme durmaz).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from akil_hocasi.yz.indirici import ModelIndirici, kurulu_modeller  # noqa: E402
from akil_hocasi.yz.katalog import Katalog  # noqa: E402

TEST_MODELLERI = ("qwen3.5-0.8b", "qwen3-embedding-0.6b")


def main() -> int:
    klasor = Path(sys.argv[1] if len(sys.argv) > 1 else "derleme/modeller")
    klasor.mkdir(parents=True, exist_ok=True)
    katalog, indirici = Katalog(), ModelIndirici(klasor)
    son = [0.0]

    def ilerleme(alinan, toplam, metin):
        if time.monotonic() - son[0] > 15:
            son[0] = time.monotonic()
            print(f"  {metin}: {alinan / 1e6:.0f}/{toplam / 1e6:.0f} MB", flush=True)

    kurulu = {m["kimlik"] for m in kurulu_modeller(klasor)}
    for kimlik in TEST_MODELLERI:
        if kimlik in kurulu:
            print(f"{kimlik}: önbellekte")
            continue
        try:
            yol = indirici.indir(katalog.getir(kimlik), ilerleme)
            print(f"{kimlik}: indirildi ve doğrulandı ({yol.name}, {yol.stat().st_size / 1e6:.0f} MB)")
        except Exception as e:  # noqa: BLE001
            print(f"UYARI: {kimlik} indirilemedi: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
