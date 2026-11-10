"""Kaggle defterlerini GitHub Actions'tan başlatma ve izleme (Kaggle API).

Gerekenler: depo ayarlarında gizli değerler (Settings → Secrets and variables → Actions):
  KAGGLE_USERNAME   — Kaggle kullanıcı adı (kaggle.com/<kullanıcı adı>)
  KAGGLE_API_TOKEN  — kaggle.com → Settings → API → "Generate New Token" ile verilen anahtar
  (eski tür: "Create Legacy API Key" ile inen kaggle.json'daki key → KAGGLE_KEY)
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
    """Kaggle kullanıcı adı. Kimlik: yeni tür API anahtarı (KAGGLE_API_TOKEN) ya da eski tür (KAGGLE_KEY)."""
    for ad in ("KAGGLE_USERNAME", "KAGGLE_API_TOKEN", "KAGGLE_KEY"):
        if not os.environ.get(ad, "").strip():
            os.environ.pop(ad, None)                  # boş gizli değer Kaggle aracını yanıltmasın
    k = os.environ.get("KAGGLE_USERNAME", "").strip()
    if not k and os.environ.get("KAGGLE_API_TOKEN"):
        k = _kullanici_bul()                          # yeni tür anahtar kullanıcı adını kendisi taşır
        if k:
            os.environ["KAGGLE_USERNAME"] = k
    if not k or not (os.environ.get("KAGGLE_API_TOKEN") or os.environ.get("KAGGLE_KEY")):
        sys.exit("Kaggle kimliği eksik. GitHub › Settings › Secrets and variables › Actions altına KAGGLE_USERNAME "
                 "ve KAGGLE_API_TOKEN (ya da eski tür anahtar için KAGGLE_KEY) ekleyin.")
    return k


_BULUNAN: dict[str, str] = {}


def _kullanici_bul() -> str:
    """KAGGLE_USERNAME verilmemişse kullanıcı adını anahtardan bulur (Kaggle aracı 1.8+)."""
    if "ad" in _BULUNAN:
        return _BULUNAN["ad"]
    ad = ""
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate()
        for kaynak in (lambda: api.get_config_value("username"), lambda: api.config_values.get("username"),
                       lambda: getattr(api, "username", "")):
            try:
                ad = str(kaynak() or "").strip()
            except Exception:  # noqa: BLE001
                ad = ""
            if ad:
                break
    except Exception as e:  # noqa: BLE001
        print(f"(kullanıcı adı API'den alınamadı: {type(e).__name__}: {e})")
    if not ad:
        for komut in (["kaggle", "config", "view"], ["kaggle", "kernels", "list", "--mine", "--csv"]):
            c = subprocess.run(komut, capture_output=True, text=True)
            print(f"$ {' '.join(komut)} → {c.returncode}\n{(c.stdout + c.stderr)[-800:]}")
            m = re.search(r"username:\s*(\S+)", c.stdout) or re.search(r"^([\w-]+)/[\w-]+,", c.stdout, re.M)
            if m and m.group(1).lower() not in ("none", "ref"):
                ad = m.group(1)
                break
    if ad:
        print(f"Kaggle kullanıcı adı anahtardan bulundu: {ad}")
    _BULUNAN["ad"] = ad
    return ad


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


def kimlik(asama: str, tur: int, veri_turu: int = 1) -> str:
    if asama == "veri":
        return f"{kullanici()}/akilhocasi-veri-{tur}"
    return f"{kullanici()}/akilhocasi-egitim" + ("-deneme" if veri_turu == 0 else "")


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


def derleme_veri_seti() -> str:
    return f"{kullanici()}/akilhocasi-llama-bin"


def derleme_hazir() -> bool:
    c = subprocess.run(["kaggle", "datasets", "status", derleme_veri_seti()], capture_output=True, text=True)
    return c.returncode == 0 and "ready" in c.stdout.lower()


def derleme_paylas(cikti: Path) -> None:
    """Defter çıktısındaki llama.cpp derlemesini özel bir veri seti yapar; sonraki defterler yeniden derlemez
    (her defterde ~30 dk kazanç)."""
    arsiv = next(iter(cikti.rglob("llama_bin.tar.gz")), None)
    if arsiv is None or derleme_hazir():
        return
    klasor = Path("kaggle_gonder") / "llama_bin"
    shutil.rmtree(klasor, ignore_errors=True)
    klasor.mkdir(parents=True)
    shutil.copy2(arsiv, klasor / arsiv.name)
    (klasor / "dataset-metadata.json").write_text(json.dumps(
        {"title": "akilhocasi-llama-bin", "id": derleme_veri_seti(), "licenses": [{"name": "other"}]}), "utf-8")
    c = subprocess.run(["kaggle", "datasets", "status", derleme_veri_seti()], capture_output=True, text=True)
    if c.returncode == 0:
        kaggle("datasets", "version", "-p", str(klasor), "-m", "llama.cpp CUDA derlemesi", yakala=True)
    else:
        kaggle("datasets", "create", "-p", str(klasor), yakala=True)


def baslat(arg) -> None:
    k = kimlik(arg.asama, arg.tur, arg.veri_turu)
    klasor = Path("kaggle_gonder") / k.split("/")[1]
    shutil.rmtree(klasor, ignore_errors=True)
    klasor.mkdir(parents=True)
    if arg.asama == "veri":
        ayar = {"SURE_SAAT": arg.sure_saat, "SORU": arg.soru, "PARALEL": arg.paralel, "TARAMA_DK": arg.tarama_dk}
        girdiler = [f"{kullanici()}/akilhocasi-veri-{i}" for i in range(1, arg.tur)]
    else:
        ayar = {"OGRENCI": arg.ogrenci, "SURE_SAAT": arg.sure_saat, "EPOCH": arg.epoch, "SINAV": arg.sinav,
                "SINAV_PAYI": arg.sinav_payi}
        girdiler = [f"{kullanici()}/akilhocasi-veri-{i}" for i in range(1, arg.veri_turu + 1)] \
            or [f"{kullanici()}/akilhocasi-veri-0"]              # veri turu 0: eğitim hattının denemesi
    defter = defter_hazirla(arg.asama, ayar)
    dosya = f"{k.split('/')[1]}.ipynb"
    (klasor / dosya).write_text(json.dumps(defter, ensure_ascii=False), "utf-8")
    kalan, yenilenme = kalan_gpu_saat()
    if kalan is not None:
        print(f"Kalan GPU kotası: {kalan:.1f} saat (yenilenme {yenilenme}); istenen süre {arg.sure_saat} saat")
        if kalan < arg.sure_saat:
            print("UYARI: kota yetmiyor; Kaggle defteri kota yenilenene dek kuyrukta bekletir. Süreyi kotaya sığdırın.")
    veri_setleri = [x for x in arg.veri_seti if x] + ([derleme_veri_seti()] if derleme_hazir() else [])
    meta = {"id": k, "title": k.split("/")[1], "code_file": dosya, "language": "python", "kernel_type": "notebook",
            "is_private": True, "enable_gpu": True, "enable_internet": True, "machine_shape": arg.hizlandirici,
            "dataset_sources": veri_setleri, "kernel_sources": girdiler,
            "competition_sources": [], "model_sources": []}
    (klasor / "kernel-metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    kaggle("kernels", "push", "-p", str(klasor), "--accelerator", arg.hizlandirici)
    print(f"Başlatıldı: https://www.kaggle.com/code/{k}")


def durum(arg) -> None:
    k = kimlik(arg.asama, arg.tur, arg.veri_turu)
    cikti = kaggle("kernels", "status", k, yakala=True)
    print(f"Defter: https://www.kaggle.com/code/{k}")
    durum_metni = cikti.lower()
    hedef = Path("kaggle_cikti") / k.split("/")[1]
    if "complete" in durum_metni or "error" in durum_metni or "cancel" in durum_metni:
        shutil.rmtree(hedef, ignore_errors=True)
        hedef.mkdir(parents=True)
        kaggle("kernels", "output", k, "-p", str(hedef), yakala=True)
        for g in hedef.rglob("*.log"):                  # defter günlüğünün sonu Actions günlüğünde görünsün
            print(f"===== {g.name} (önemli satırlar) =====")
            try:
                satirlar = []
                for kayit in json.loads(g.read_text("utf-8", errors="replace")):
                    satirlar += str(kayit.get("data", "")).splitlines()
            except ValueError:
                satirlar = g.read_text("utf-8", errors="replace").splitlines()
            satirlar = [s for s in satirlar if "%|" not in s and s.strip() and not s.startswith("INFO:hf-to-gguf")]
            onemli = [s for s in satirlar if re.match(r"^\[\d\d:\d\d:\d\d\]", s) or any(
                a in s for a in ("Error", "Traceback", "'loss'", "train_runtime", "Unsloth:", "Exception", "Num examples",
                                 "Total steps", "Trainable parameters"))]
            print("\n".join(onemli[-300:]))
            print("----- günlüğün sonu -----")
            print("\n".join(satirlar[-120:]))
        if "complete" in durum_metni:
            derleme_paylas(hedef)
        for ad in ("manifest.json", "rapor.json", "EGITIM_RAPORU.md"):
            for f in hedef.rglob(ad):
                print(f"===== {f} =====\n{f.read_text('utf-8', errors='replace')[:6000]}")
        for f in hedef.rglob("atilan_ornekler.jsonl"):     # tanılama (Actions eki indirilemeyebilir: günlüğe)
            print(f"===== {f.name} =====")
            for satir in f.read_text("utf-8", errors="replace").splitlines()[:80]:
                try:
                    d = json.loads(satir)
                except ValueError:
                    print(satir[:1500])
                    continue
                ozet = {a: d.get(a) for a in ("neden", "bitis", "belirtec", "sure", "durum", "altin", "dayanak_yok",
                                              "cikarilan", "model", "hata") if a in d}
                ozet["cevap"] = str(d.get("cevap", ""))[:1400]
                if "bozuk" in str(d.get("neden")) or not ozet["cevap"]:
                    ozet["ham"] = str(d.get("ham", ""))[:900]
                print(json.dumps(ozet, ensure_ascii=False))
        for f in sorted(hedef.rglob("sunucu_*.txt")):
            print(f"===== {f.name} (son 80 satır) =====")
            print("\n".join(f.read_text("utf-8", errors="replace").splitlines()[-80:]))
        for f in hedef.rglob("ornekler.jsonl"):
            satirlar = f.read_text("utf-8", errors="replace").splitlines()
            print(f"===== {f.name}: {len(satirlar)} örnek; ilk üçü =====")
            for satir in satirlar[:3]:
                print(satir[:3000])
        for f in hedef.rglob("akilhocasi-*.json"):
            print(f"===== {f.name} =====\n{f.read_text('utf-8')[:4000]}")
    Path(os.environ.get("GITHUB_OUTPUT", os.devnull)).open("a").write(
        f"durum={'bitti' if 'complete' in durum_metni else 'hata' if 'error' in durum_metni else 'suruyor'}\n")


def dogrula(arg) -> None:
    """Kimliği sınar: hesaptaki defterleri listeler (hiçbir şey başlatmaz)."""
    print(f"Kaggle kullanıcısı: {kullanici()}")
    kaggle("kernels", "list", "--mine", "--page-size", "20")
    print("Kaggle kimliği çalışıyor.")
    kota_goster()


def kota_goster() -> dict | None:
    """Hızlandırıcı (GPU) kotası: kullanılan ve kalan süre (yalnız okuma)."""
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        from kagglesdk.kernels.types.kernels_api_service import ApiGetAcceleratorQuotaStatisticsRequest
        api = KaggleApi()
        api.authenticate()
        with api.build_kaggle_client() as istemci:
            hizmet = istemci.kernels.kernels_api_client
            yanit = hizmet.get_accelerator_quota_statistics(ApiGetAcceleratorQuotaStatisticsRequest())
        veri = yanit.to_dict() if hasattr(yanit, "to_dict") else {a: getattr(yanit, a) for a in dir(yanit)
                                                                    if not a.startswith("_")}
        print("GPU KOTASI:", json.dumps(veri, ensure_ascii=False, default=str)[:3000])
        return veri
    except Exception as e:  # noqa: BLE001
        print(f"(kota bilgisi alınamadı: {type(e).__name__}: {e})")
        return None


def kalan_gpu_saat() -> tuple[float | None, str]:
    """(Kalan GPU saati, yenilenme zamanı). Kaggle kotası haftalıktır; oturum bitince düşülür."""
    veri = kota_goster() or {}
    g = veri.get("gpuQuota") or {}

    def sn(x) -> float:
        m = re.match(r"^(\d+(?:\.\d+)?)", str(x or "0"))
        return float(m.group(1)) if m else 0.0
    if not g:
        return None, ""
    return (sn(g.get("totalTimeAllowed")) - sn(g.get("timeUsed")) - sn(g.get("timeReserved"))) / 3600, \
        str(veri.get("quotaRefreshTime", ""))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("islem", choices=["baslat", "durum", "dogrula"])
    p.add_argument("asama", choices=["veri", "egit"], nargs="?", default="veri")
    p.add_argument("--tur", type=int, default=1, help="veri turu numarası (1, 2, 3…)")
    p.add_argument("--veri-turu", type=int, default=1, help="eğitimde kullanılacak veri turu sayısı")
    p.add_argument("--sure-saat", type=float, default=10.5)
    p.add_argument("--soru", type=int, default=4000)
    p.add_argument("--paralel", type=int, default=8)
    p.add_argument("--tarama-dk", type=float, default=40)
    p.add_argument("--ogrenci", default="4B")
    p.add_argument("--epoch", type=float, default=2)
    p.add_argument("--hizlandirici", default="NvidiaTeslaT4", choices=["NvidiaTeslaT4", "NvidiaTeslaP100"],
                   help="T4 x2 (varsayılan; eğitim iki kartta) ya da P100 (tek kart; T4 kuyruğu uzunsa)")
    p.add_argument("--sinav", type=int, default=150, help="eğitim sonrası sınavdaki en çok soru")
    p.add_argument("--sinav-payi", type=float, default=1.75, help="dönüştürme ve sınava ayrılan saat")
    p.add_argument("--veri-seti", nargs="*", default=[], help="kullanıcı eğitim paketi veri seti (kullanici/ad)")
    arg = p.parse_args()
    {"baslat": baslat, "durum": durum, "dogrula": dogrula}[arg.islem](arg)


if __name__ == "__main__":
    main()
