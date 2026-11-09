"""Kaggle defterlerini GitHub Actions'tan başlatma ve izleme (Kaggle API).

Gerekenler: depo ayarlarında iki gizli değer (Settings → Secrets and variables → Actions):
  KAGGLE_USERNAME, KAGGLE_KEY  — kaggle.com → Settings → API → "Create New Token" ile inen kaggle.json'daki değerler.
Kaggle hesabı telefonla doğrulanmış olmalıdır (GPU ve internet için).

  python kaggle/kaggle_api.py baslat veri --tur 1 --sure-saat 10.5
  python kaggle/kaggle_api.py baslat egit --ogrenci 4B
  python kaggle/kaggle_api.py durum veri --tur 1      # bitmişse çıktıyı ve günlüğü indirir

Defterler "GPU T4 x2" (NvidiaTeslaT4) ve internet açık çalışır. Veri turları ayrı defterlerdir
(akilhocasi-veri-1, -2, …); her tur öncekilerin çıktısını girdi olarak alır ve veriyi kaldığı yerden büyütür.
Eğitim defteri bütün veri turlarını girdi olarak alır.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent


def kullanici() -> str:
    k = os.environ.get("KAGGLE_USERNAME", "").strip()
    if not k or not os.environ.get("KAGGLE_KEY", "").strip():
        sys.exit("KAGGLE_USERNAME ve KAGGLE_KEY tanımlı değil (GitHub › Settings › Secrets and variables › Actions).")
    return k


def kaggle(*argumanlar: str, yakala: bool = False) -> str:
    print("$ kaggle " + " ".join(argumanlar), flush=True)
    c = subprocess.run(["kaggle", *argumanlar], capture_output=True, text=True)
    if c.stdout:
        print(c.stdout.strip())
    if c.returncode != 0:
        print(c.stderr.strip(), file=sys.stderr)
        if not yakala:
            sys.exit(c.returncode)
    return c.stdout


def kimlik(asama: str, tur: int) -> str:
    return f"{kullanici()}/akilhocasi-veri-{tur}" if asama == "veri" else f"{kullanici()}/akilhocasi-egitim"


def defter_hazirla(asama: str, ayarlar: dict[str, object]) -> dict:
    ad = "1_veri_uretimi.ipynb" if asama == "veri" else "2_egitim_ve_sinama.ipynb"
    d = json.loads((KOK / ad).read_text("utf-8"))
    for h in d["cells"]:
        if h["cell_type"] != "code":
            continue
        kaynak = "".join(h["source"])
        for anahtar, deger in ayarlar.items():
            kaynak = re.sub(rf"^{anahtar} = .*?(\s+#.*)?$", lambda m, a=anahtar, v=deger: f"{a} = {v!r}{m.group(1) or ''}",
                            kaynak, flags=re.M)
        h["source"] = kaynak.splitlines(keepends=True)
    return d


def baslat(arg) -> None:
    k = kimlik(arg.asama, arg.tur)
    klasor = Path("kaggle_gonder") / k.split("/")[1]
    shutil.rmtree(klasor, ignore_errors=True)
    klasor.mkdir(parents=True)
    if arg.asama == "veri":
        ayar = {"SURE_SAAT": arg.sure_saat, "SORU": arg.soru, "PARALEL": arg.paralel, "TARAMA_DK": arg.tarama_dk}
        girdiler = [f"{kullanici()}/akilhocasi-veri-{i}" for i in range(1, arg.tur)]
    else:
        ayar = {"OGRENCI": arg.ogrenci, "SURE_SAAT": arg.sure_saat, "EPOCH": arg.epoch}
        girdiler = [f"{kullanici()}/akilhocasi-veri-{i}" for i in range(1, arg.veri_turu + 1)]
    defter = defter_hazirla(arg.asama, ayar)
    dosya = f"{k.split('/')[1]}.ipynb"
    (klasor / dosya).write_text(json.dumps(defter, ensure_ascii=False), "utf-8")
    meta = {"id": k, "title": k.split("/")[1], "code_file": dosya, "language": "python", "kernel_type": "notebook",
            "is_private": True, "enable_gpu": True, "enable_internet": True, "machine_shape": "NvidiaTeslaT4",
            "dataset_sources": [x for x in arg.veri_seti if x], "kernel_sources": girdiler,
            "competition_sources": [], "model_sources": []}
    (klasor / "kernel-metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    kaggle("kernels", "push", "-p", str(klasor), "--accelerator", "NvidiaTeslaT4")
    print(f"Başlatıldı: https://www.kaggle.com/code/{k}")


def durum(arg) -> None:
    k = kimlik(arg.asama, arg.tur)
    cikti = kaggle("kernels", "status", k, yakala=True)
    print(f"Defter: https://www.kaggle.com/code/{k}")
    durum_metni = cikti.lower()
    hedef = Path("kaggle_cikti") / k.split("/")[1]
    if "complete" in durum_metni or "error" in durum_metni or "cancel" in durum_metni:
        shutil.rmtree(hedef, ignore_errors=True)
        hedef.mkdir(parents=True)
        kaggle("kernels", "output", k, "-p", str(hedef), yakala=True)
        for g in hedef.rglob("*.log"):                  # defter günlüğünün sonu Actions günlüğünde görünsün
            print(f"===== {g.name} (son 400 satır) =====")
            try:
                satirlar = []
                for kayit in json.loads(g.read_text("utf-8", errors="replace")):
                    satirlar += str(kayit.get("data", "")).splitlines()
            except ValueError:
                satirlar = g.read_text("utf-8", errors="replace").splitlines()
            print("\n".join(satirlar[-400:]))
        for ad in ("manifest.json", "rapor.json", "EGITIM_RAPORU.md"):
            for f in hedef.rglob(ad):
                print(f"===== {f} =====\n{f.read_text('utf-8', errors='replace')[:6000]}")
        for f in hedef.rglob("akilhocasi-*.json"):
            print(f"===== {f.name} =====\n{f.read_text('utf-8')[:4000]}")
    Path(os.environ.get("GITHUB_OUTPUT", os.devnull)).open("a").write(
        f"durum={'bitti' if 'complete' in durum_metni else 'hata' if 'error' in durum_metni else 'suruyor'}\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("islem", choices=["baslat", "durum"])
    p.add_argument("asama", choices=["veri", "egit"])
    p.add_argument("--tur", type=int, default=1, help="veri turu numarası (1, 2, 3…)")
    p.add_argument("--veri-turu", type=int, default=1, help="eğitimde kullanılacak veri turu sayısı")
    p.add_argument("--sure-saat", type=float, default=10.5)
    p.add_argument("--soru", type=int, default=4000)
    p.add_argument("--paralel", type=int, default=4)
    p.add_argument("--tarama-dk", type=float, default=40)
    p.add_argument("--ogrenci", default="4B")
    p.add_argument("--epoch", type=float, default=2)
    p.add_argument("--veri-seti", nargs="*", default=[], help="kullanıcı eğitim paketi veri seti (kullanici/ad)")
    arg = p.parse_args()
    {"baslat": baslat, "durum": durum}[arg.islem](arg)


if __name__ == "__main__":
    main()
