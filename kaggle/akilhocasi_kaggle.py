"""Akıl Hocası — Kaggle eğitim hattı (yoğun eğitim, çekirdeğe uyum).

İki aşama, iki Kaggle defteri (her biri en çok ~11 saat; "GPU T4 x2" ve İnternet açık):

  1) veri  — Öğretmen model (Qwen3.5-35B-A3B, iki T4'e bölünmüş) programın KENDİ çekirdek iş akışını çalıştırır:
             durum çözümleme, gerekçeli sentez, öz eleştiri, düzeltme, hatadan ders çıkarma, çalışma sorusu
             üretme ve resmî yazı. Yalnızca programın sınamasından geçen çağrılar eğitim örneği olur.
             Defter tekrar çalıştırılırsa önceki çıktısından KALDIĞI YERDEN sürer (veri birikir).
  2) egit  — Öğrenci model (Qwen3.5-4B; 8 GB bilgisayarlar için) 16 bit LoRA ile, programın çalışırken
             gönderdiği istemlerin aynısıyla eğitilir; GGUF Q4_K_M'e dönüştürülür; eğitimde görülmemiş sınav
             sorularında temel modelle yarıştırılır ve programın ilke karnesi + gelişim kapısıyla değerlendirilir.

Kullanım (defterler bunu çağırır):
  python kaggle/akilhocasi_kaggle.py veri --sure-saat 10.5
  python kaggle/akilhocasi_kaggle.py egit --ogrenci 4B --sure-saat 6
Yerelde denemek için: veri --ogretmen-adres http://127.0.0.1:8080 --anlamsiz --tarama-dk 0 --sure-saat 0.05
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import os
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

KOK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KOK))

KAGGLE = Path("/kaggle").is_dir()
CALISMA = Path("/kaggle/working") if KAGGLE else KOK / "derleme" / "kaggle" / "working"
GECICI = Path("/kaggle/tmp" if Path("/kaggle/tmp").is_dir() else "/tmp") / "akilhocasi"
VERI_ADI, MODEL_ADI = "akilhocasi_veri", "akilhocasi_model"

OGRETMENLER = {   # Kaggle T4 x2 (2 x 15 GB) için: ağırlıklar iki karta bölünür
    "Q4_K_M": ("Qwen3.5 35B-A3B (öğretmen)", "unsloth/Qwen3.5-35B-A3B-GGUF", r"Qwen3\.5-35B-A3B-Q4_K_M\.gguf$", 22.0),
    "Q4_K_S": ("Qwen3.5 35B-A3B (öğretmen)", "unsloth/Qwen3.5-35B-A3B-GGUF", r"Qwen3\.5-35B-A3B-Q4_K_S\.gguf$", 20.7),
    "Q3_K_M": ("Qwen3.5 35B-A3B (öğretmen)", "unsloth/Qwen3.5-35B-A3B-GGUF", r"Qwen3\.5-35B-A3B-Q3_K_M\.gguf$", 16.4),
}
OGRENCILER = {"4B": ("unsloth/Qwen3.5-4B", "qwen3.5-4b", 7.5), "2B": ("unsloth/Qwen3.5-2B", "qwen3.5-2b", 5.5)}


def bildir(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def sh(komut: str, **kw) -> None:
    bildir("$ " + komut)
    subprocess.run(komut, shell=True, check=True, **kw)


def girdide_bul(desen: str) -> list[Path]:
    """Kaggle girdilerinde (önceki defter çıktısı ya da yüklenen veri seti) dosya arar."""
    return [Path(p) for p in glob.glob(f"/kaggle/input/**/{desen}", recursive=True)] if KAGGLE else []


# ---------------------------------------------------------------------------- llama.cpp (CUDA)
def llama_hazirla(gpu: bool = True) -> Path:
    """llama-server ve llama-quantize: önceki defter çıktısındaki derleme varsa o, yoksa CUDA ile derlenir."""
    hedef = GECICI / "llama_bin"
    if (hedef / "llama-server").is_file():
        return hedef
    for arsiv in girdide_bul("llama_bin.tar.gz") + [CALISMA / VERI_ADI / "llama_bin.tar.gz"]:
        if arsiv.is_file():
            hedef.mkdir(parents=True, exist_ok=True)
            with tarfile.open(arsiv) as t:
                t.extractall(hedef, filter="data")
            if (hedef / "llama-server").is_file() and llama_calisiyor(hedef):
                bildir(f"llama.cpp önceki derlemeden alındı ({arsiv})")
                return hedef
            bildir(f"Önceki derleme bu ortamda çalışmıyor ({arsiv}); yeniden derlenecek")
            shutil.rmtree(hedef, ignore_errors=True)
    kaynak = GECICI / "llama.cpp"
    if not kaynak.is_dir():
        sh(f"git clone --depth 1 https://github.com/ggml-org/llama.cpp {kaynak}")
    secenek = f'-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="{cuda_mimarileri()}"' if gpu else "-DGGML_CUDA=OFF"
    if gpu and Path("/usr/local/cuda/bin/nvcc").is_file():
        secenek += " -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc"
    if gpu:
        surucu = cuda_surucu_kutuphanesi()
        # Kaggle görüntüsünde araç takımı libcuda.so'yu kendisi bulamıyor (CUDA::cuda_driver yok): yolu veriyoruz;
        # hiç bulunamazsa sürücüye doğrudan bağlanmayan (VMM'siz) derlemeye geçilir.
        secenek += f" -DCUDA_cuda_driver_LIBRARY={surucu}" if surucu else " -DGGML_CUDA_NO_VMM=ON"
    genel = "-DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DCMAKE_BUILD_TYPE=Release"
    try:
        sh(f"cmake -S {kaynak} -B {kaynak}/build {secenek} {genel}")
    except subprocess.CalledProcessError:
        if not gpu:
            raise
        bildir("CUDA yapılandırması başarısız; sürücüye doğrudan bağlanmayan derleme deneniyor")
        shutil.rmtree(kaynak / "build", ignore_errors=True)
        secenek = re.sub(r" -DCUDA_cuda_driver_LIBRARY=\S+", "", secenek)
        sh(f"cmake -S {kaynak} -B {kaynak}/build {secenek} -DGGML_CUDA_NO_VMM=ON {genel}")
    sh(f"cmake --build {kaynak}/build --config Release -j {os.cpu_count() or 4} --target llama-server llama-quantize")
    hedef.mkdir(parents=True, exist_ok=True)
    for f in Path(kaynak, "build", "bin").iterdir():
        if f.is_file():
            shutil.copy2(f, hedef / f.name)
    return hedef


def llama_calisiyor(klasor: Path) -> bool:
    """Arşivden açılan derleme bu görüntüde çalışıyor mu (CUDA sürümü değişmiş olabilir)?"""
    ortam = {**os.environ, "LD_LIBRARY_PATH": f"{klasor}:{os.environ.get('LD_LIBRARY_PATH', '')}"}
    try:
        c = subprocess.run([str(klasor / "llama-server"), "--version"], capture_output=True, text=True, timeout=60,
                           env=ortam)
        return c.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def cuda_surucu_kutuphanesi() -> str:
    """libcuda.so: önce araç takımındaki bağlama taslağı (stub), yoksa gerçek sürücü (gerekirse .so bağlantısıyla)."""
    adaylar = (glob.glob("/usr/local/cuda*/**/stubs/libcuda.so", recursive=True)
               + glob.glob("/usr/lib/x86_64-linux-gnu/libcuda.so*") + glob.glob("/usr/local/nvidia/lib64/libcuda.so*")
               + glob.glob("/usr/lib64/libcuda.so*"))
    for a in adaylar:
        if not Path(a).exists():
            continue
        if a.endswith("libcuda.so"):
            return a
        baglanti = GECICI / "cuda_surucu" / "libcuda.so"      # libcuda.so.1 → libcuda.so (bağlayıcı bu adı arar)
        baglanti.parent.mkdir(parents=True, exist_ok=True)
        baglanti.unlink(missing_ok=True)
        baglanti.symlink_to(Path(a).resolve())
        return str(baglanti)
    return ""


def cuda_mimarileri() -> str:
    """Takılı kartların hesaplama yetenekleri (T4: 75, P100: 60); yalnız onlar için derlemek süreyi kısaltır."""
    try:
        c = subprocess.run(["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"], capture_output=True,
                           text=True, timeout=30)
        bulunan = {x.strip().replace(".", "") for x in c.stdout.splitlines() if x.strip()}
    except (OSError, subprocess.SubprocessError):
        bulunan = set()
    return ";".join(sorted(bulunan or {"60", "75"}))


def llama_arsivle(klasor: Path, hedef: Path) -> None:
    with tarfile.open(hedef, "w:gz") as t:
        for f in klasor.iterdir():
            t.add(f, arcname=f.name)


def sunucu(model: Path, tur: str, bin_klasoru: Path, baglam: int, paralel: int = 1, ek: list[str] | None = None,
           havuzlama: str = "last"):
    from akil_hocasi.yz.sunucu import LlamaSunucusu
    gunluk = GECICI / "gunluk"
    gunluk.mkdir(parents=True, exist_ok=True)
    argumanlar = ["-ngl", "999", "-np", str(paralel)] + (ek or [])
    s = LlamaSunucusu(str(model), tur, baglam, os.cpu_count() or 4, str(bin_klasoru / "llama-server"), gunluk,
                      argumanlar, havuzlama)
    os.environ["LD_LIBRARY_PATH"] = f"{bin_klasoru}:{os.environ.get('LD_LIBRARY_PATH', '')}"
    s.baslat(zaman_asimi=2400, ilerleme=lambda m: None)
    return s


def model_indir(kimlik: str, ad: str, depo: str, desen: str, gb: float, tur: str = "sohbet", ek=None) -> Path:
    from akil_hocasi.yz.indirici import ModelIndirici
    from akil_hocasi.yz.katalog import ModelTanimi
    son = [0.0]

    def ilerleme(alinan, toplam, metin):
        if time.monotonic() - son[0] > 60:
            son[0] = time.monotonic()
            bildir(f"  {metin}: {alinan / 1e9:.1f}/{toplam / 1e9:.1f} GB")

    m = ModelTanimi(kimlik, ad, tur, depo, desen, gb, 0, ek=ek or {})
    return ModelIndirici(GECICI / "modeller").indir(m, ilerleme)


def katalog_modeli(kimlik: str) -> Path:
    from akil_hocasi.yz.indirici import ModelIndirici
    from akil_hocasi.yz.katalog import Katalog
    return ModelIndirici(GECICI / "modeller").indir(Katalog().getir(kimlik), None)


# ---------------------------------------------------------------------------- kütüphane ve servisler
def servisler(k, anlam=None):
    from akil_hocasi.answer.dogrulama import DogrulamaMotoru
    from akil_hocasi.answer.hat import CevapHatti
    from akil_hocasi.cekirdek.dersler import DersHafizasi
    from akil_hocasi.cekirdek.strateji import StratejiDeposu
    from akil_hocasi.crawler.beyaz_liste import BIRINCIL
    strateji, dersler = StratejiDeposu(k), DersHafizasi(k)
    hat = CevapHatti(k, DogrulamaMotoru(k, BIRINCIL), strateji=strateji, dersler=dersler, anlam=anlam)
    return SimpleNamespace(hat=hat, kutuphane=k, dersler=dersler, strateji=strateji, yz=None, ayarlar=None)


def kutuphane_hazirla(veri: Path, tarama_dk: float) -> tuple[object, list[dict]]:
    """Kütüphane: önceki çıktı > kullanıcı paketi (programdan dışa aktarılan) > boş; ardından çekirdek mevzuat
    resmî kaynaktan ve (süre verilirse) TOGÜ sayfaları taranır. Kullanıcı paketindeki sorular da döner."""
    from akil_hocasi.crawler.depo import BelgeDeposu
    from akil_hocasi.crawler.indirici import Indirici
    from akil_hocasi.crawler.tarayici import Tarayici
    from akil_hocasi.library.bilgi_paketi import paketi_yukle
    from akil_hocasi.library.db import Kutuphane
    ek_sorular: list[dict] = []
    db = veri / "kutuphane.db"
    for paket in girdide_bul("akilhocasi_egitim_paketi*.zip"):
        import zipfile
        with zipfile.ZipFile(paket) as z:
            if not db.is_file() and "kutuphane.db" in z.namelist():
                z.extract("kutuphane.db", veri)
                bildir(f"Kullanıcı paketindeki kütüphane alındı ({paket.name})")
            if "sorular.jsonl" in z.namelist():
                for satir in z.read("sorular.jsonl").decode("utf-8").splitlines():
                    try:
                        ek_sorular.append(json.loads(satir))
                    except ValueError:
                        pass
        bildir(f"Kullanıcı paketinden {len(ek_sorular)} soru (altın set ve gerçek sorular)")
    k = Kutuphane(db)
    t = Tarayici(k, BelgeDeposu(GECICI / "depo"), Indirici())
    paket = GECICI / "bilgi_paketi"
    try:
        sh(f"{sys.executable} {KOK / 'paketleme' / 'bilgi_paketi.py'} {paket}")
        bildir(f"Çekirdek mevzuat: {paketi_yukle(t, paket)}")
    except subprocess.CalledProcessError as e:
        bildir(f"UYARI: çekirdek mevzuat indirilemedi: {e}")
    if tarama_dk > 0:
        bildir(f"TOGÜ sayfaları taranıyor (en çok {tarama_dk:g} dk)")
        is_ = threading.Thread(target=t.calistir, args=("derin", lambda m: None), daemon=True)
        is_.start()
        is_.join(tarama_dk * 60)
        t.durdur.set()
        is_.join(120)
    n = k.db.execute("SELECT COUNT(*) FROM maddeler WHERE yururluk_bitis IS NULL").fetchone()[0]
    b = k.db.execute("SELECT COUNT(*) FROM belgeler").fetchone()[0]
    bildir(f"Kütüphane: {b} belge, {n} yürürlükte madde")
    return k, ek_sorular


def anlam_kur(k, bin_klasoru: Path):
    from akil_hocasi.yz.anlam import AnlamDizini
    from akil_hocasi.yz.katalog import Katalog
    t = Katalog().getir("qwen3-embedding-0.6b")
    yol = katalog_modeli(t.kimlik)
    s = sunucu(yol, "anlam", bin_klasoru, 8192, havuzlama=t.ek.get("havuzlama", "last"))
    a = AnlamDizini(k, s, t.kimlik, t.ek.get("sorgu_talimati", ""))
    toplam = 0
    while True:
        n = a.eksikleri_isle(2048)
        toplam += n
        if n == 0:
            break
    bildir(f"Anlam dizini: {toplam} madde vektörlendi")
    return a, s


# ---------------------------------------------------------------------------- 1) veri
def veri(arg) -> None:
    bas = time.monotonic()
    bitis_saat = bas + arg.sure_saat * 3600
    veri_k = CALISMA / VERI_ADI
    veri_k.mkdir(parents=True, exist_ok=True)
    # Önceki veri turları (bir ya da birkaç defter çıktısı): birleştirilir, kaldığı yerden sürer
    onceki_turlar = onceki_veriler()
    if onceki_turlar:
        birlestir(onceki_turlar, veri_k)
        bildir(f"Önceki {len(onceki_turlar)} veri turu birleştirildi; kaldığı yerden sürüyor")
    k, ek_sorular = kutuphane_hazirla(veri_k, arg.tarama_dk)
    from akil_hocasi.yz.damitma import Damitici, OgretmenModeli
    sunucular, bin_k = [], None
    try:
        anlam = None
        if not arg.ogretmen_adres:
            bin_k = llama_hazirla(gpu=True)
        if not arg.anlamsiz and bin_k:
            anlam, sa = anlam_kur(k, bin_k)
            sunucular.append(sa)
        s = servisler(k, anlam)
        adres = arg.ogretmen_adres
        if not adres:
            ad, depo, desen, gb = OGRETMENLER[arg.ogretmen]
            yol = model_indir("ogretmen", ad, depo, desen, gb)
            so = sunucu(yol, "sohbet", bin_k, arg.paralel * arg.yuva_baglami, arg.paralel,
                        ["--split-mode", "layer", "--jinja"])
            sunucular.append(so)
            adres = so.adres
        ogretmen = OgretmenModeli(adres, OGRETMENLER.get(arg.ogretmen, ("öğretmen",))[0])
        kalan_dk = max(1.0, (bitis_saat - time.monotonic()) / 60 - 15)   # paketleme payı
        d = Damitici(s, ogretmen, veri_k, bildir)
        rapor = d.calistir(kalan_dk, arg.soru, arg.yazi_orani, arg.paralel, ek_sorular)
    finally:
        for sv in sunucular:
            sv.durdur()
        gunluk_kopyala(veri_k)
    if bin_k:
        llama_arsivle(bin_k, veri_k / "llama_bin.tar.gz")
    k.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    ornek_sayisi = sum(1 for _ in (veri_k / "ornekler.jsonl").open("r", encoding="utf-8")) \
        if (veri_k / "ornekler.jsonl").is_file() else 0
    (veri_k / "manifest.json").write_text(json.dumps({
        "olusturma": datetime.now().isoformat(timespec="seconds"), "ogretmen": arg.ogretmen,
        "ornek_toplam": ornek_sayisi, "bu_oturum": rapor.__dict__, "program": _surum()}, ensure_ascii=False, indent=1),
        "utf-8")
    bildir(f"Veri hazır: {ornek_sayisi} örnek ({veri_k}). Defteri yeniden çalıştırırsanız veri birikir.")


def gunluk_kopyala(hedef: Path, satir: int = 400) -> None:
    """Model sunucularının günlüklerinin sonu çıktıya (tanılama)."""
    for g in sorted((GECICI / "gunluk").glob("*.log")):
        try:
            satirlar = g.read_text("utf-8", errors="replace").splitlines()
            (hedef / f"sunucu_{g.stem}.txt").write_text("\n".join(satirlar[-satir:]) + "\n", "utf-8")
        except OSError:
            pass


def onceki_veriler() -> list[Path]:
    """Girdilerdeki önceki veri turlarının klasörleri (eskiden yeniye). Deneme turunun (tur 0) verisi
    birleştirilmez; ondan yalnız llama.cpp derlemesi alınır."""
    return sorted({p.parent for p in girdide_bul(f"{VERI_ADI}/manifest.json") if "akilhocasi-veri-0" not in str(p)},
                  key=lambda d: (d / "manifest.json").stat().st_mtime)


def birlestir(kaynaklar: list[Path], hedef: Path) -> None:
    """Veri turlarını tek klasörde toplar: örnek/sınav/işlenen satırları yinelemesiz eklenir, kütüphane en yeniden."""
    hedef.mkdir(parents=True, exist_ok=True)
    for ad in ("ornekler.jsonl", "sinav.jsonl", "islenen.txt"):
        gorulen, satirlar = set(), []
        for d in [hedef] + list(kaynaklar):
            if (d / ad).is_file():
                for s in (d / ad).read_text("utf-8").splitlines():
                    if s.strip() and s not in gorulen:
                        gorulen.add(s)
                        satirlar.append(s)
        if satirlar:
            (hedef / ad).write_text("\n".join(satirlar) + "\n", "utf-8")
    for d in reversed(kaynaklar):
        if (d / "kutuphane.db").is_file():
            if not (hedef / "kutuphane.db").is_file() or d != hedef:
                shutil.copy2(d / "kutuphane.db", hedef / "kutuphane.db")
            break


def _surum() -> str:
    try:
        return subprocess.run(["git", "-C", str(KOK), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# ---------------------------------------------------------------------------- 2) eğitim
def _veri_klasorleri() -> list[Path]:
    yerel = CALISMA / VERI_ADI
    turlar = onceki_veriler() + ([yerel] if (yerel / "ornekler.jsonl").is_file() else [])
    if not turlar:
        raise SystemExit("Eğitim verisi bulunamadı: 1. defterin çıktısını 'Add Input' ile bu deftere ekleyin.")
    return turlar


def egit(arg) -> None:
    bas = time.monotonic()
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")          # eğitim tek kartta (Unsloth); sınav sunucusu ikisini de kullanır
    import gc

    import torch
    from unsloth import FastLanguageModel  # noqa: I001 - unsloth, transformers'tan önce yüklenmeli
    from transformers import DataCollatorForSeq2Seq, Trainer, TrainerCallback, TrainingArguments
    from datasets import Dataset

    from akil_hocasi.yz.damitma import dengele, egitim_metinleri, ornekleri_oku
    veri_k = GECICI / "veri"
    if veri_k.exists():
        shutil.rmtree(veri_k)
    turlar = _veri_klasorleri()
    birlestir(turlar, veri_k)
    bildir(f"{len(turlar)} veri turu birleştirildi")
    hf_kimlik, katalog_kimlik, bellek = OGRENCILER[arg.ogrenci]
    ornekler = ornekleri_oku([veri_k / "ornekler.jsonl"])
    secilen = dengele(ornekler)
    bildir(f"{len(ornekler)} geçerli örnek, dengelenmiş {len(secilen)}: "
           + ", ".join(f"{g} {sum(1 for o in secilen if o['gorev'] == g)}" for g in sorted({o['gorev'] for o in secilen})))

    model, tokenizer = FastLanguageModel.from_pretrained(model_name=hf_kimlik, max_seq_length=arg.en_cok_belirtec,
                                                         load_in_4bit=False, load_in_16bit=True, full_finetuning=False)
    tok = getattr(tokenizer, "tokenizer", tokenizer)            # çok kipli modelde işlemcinin içindeki belirteçleyici

    def sablon(mesajlar):
        for nesne in (tokenizer, tok):
            try:
                return nesne.apply_chat_template(mesajlar, tokenize=False, add_generation_prompt=True,
                                                 enable_thinking=False)
            except Exception:  # noqa: BLE001 - işlemci düz metin içeriği kabul etmezse belirteçleyiciyle
                continue
        raise RuntimeError("Sohbet şablonu uygulanamadı")

    def uzunluk(metin):
        return len(tok(metin, add_special_tokens=False)["input_ids"])

    bitis_isareti = "<|im_end|>"
    ornek_istem = sablon(secilen[0]["messages"])
    bildir("İstem sonu (çalışırken llama-server'ın üreteceğiyle aynı olmalı): " + repr(ornek_istem[-80:]))
    ciftler, atilan = egitim_metinleri(secilen, sablon, uzunluk, arg.en_cok_belirtec)
    bildir(f"{len(ciftler)} örnek eğitime giriyor, {atilan} örnek uzunluk sınırını aştı")

    def kodla(c):
        p = tok(c["prompt"], add_special_tokens=False)["input_ids"]
        t = tok(c["completion"] + bitis_isareti, add_special_tokens=False)["input_ids"]
        return {"input_ids": p + t, "attention_mask": [1] * (len(p) + len(t)), "labels": [-100] * len(p) + t}

    veri_seti = Dataset.from_list([{"prompt": c["prompt"], "completion": c["completion"]} for c in ciftler])
    veri_seti = veri_seti.map(kodla, remove_columns=["prompt", "completion"])

    model = FastLanguageModel.get_peft_model(
        model, r=arg.lora_r, lora_alpha=arg.lora_r, lora_dropout=0, bias="none", random_state=3407,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth")

    egitim_sonu = bas + arg.sure_saat * 3600 - 2.5 * 3600            # dönüştürme ve sınav payı

    class SureSiniri(TrainerCallback):
        def on_step_end(self, args, state, control, **kw):
            if time.monotonic() > egitim_sonu:
                bildir("Süre bütçesi doldu; eğitim burada tamamlanıyor")
                control.should_training_stop = True
            return control

    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    ayar = TrainingArguments(
        output_dir=str(GECICI / "egitim"), per_device_train_batch_size=1, gradient_accumulation_steps=8,
        num_train_epochs=arg.epoch, learning_rate=arg.ogrenme_hizi, warmup_ratio=0.03, lr_scheduler_type="cosine",
        logging_steps=10, save_strategy="no", report_to="none", optim="adamw_8bit", weight_decay=0.01,
        bf16=bf16, fp16=not bf16, seed=3407, remove_unused_columns=False)
    egitici = Trainer(model=model, args=ayar, train_dataset=veri_seti,
                      data_collator=DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100),
                      callbacks=[SureSiniri()])
    sonuc = egitici.train()
    kayiplar = [x["loss"] for x in egitici.state.log_history if "loss" in x]
    bildir(f"Eğitim bitti: {sonuc.global_step} adım, kayıp {kayiplar[0]:.3f} → {kayiplar[-1]:.3f}"
           if kayiplar else "Eğitim bitti")

    # GGUF'a dönüştürme
    surum = arg.surum or datetime.now().strftime("%Y%m%d")
    kimlik = f"akilhocasi-{arg.ogrenci.lower()}-{surum}"
    model_k = CALISMA / MODEL_ADI
    model_k.mkdir(parents=True, exist_ok=True)
    hedef = model_k / f"{kimlik}.gguf"
    bin_k = llama_hazirla(gpu=True)
    birlesik = GECICI / "birlesik"
    try:
        model.save_pretrained_merged(str(birlesik), tokenizer, save_method="merged_16bit")
        kaynak_llama = GECICI / "llama.cpp"
        if not kaynak_llama.is_dir():
            sh(f"git clone --depth 1 https://github.com/ggml-org/llama.cpp {kaynak_llama}")
        sh(f"{sys.executable} -m pip install -q {kaynak_llama / 'gguf-py'} sentencepiece protobuf")
        f16 = GECICI / f"{kimlik}-f16.gguf"
        sh(f"{sys.executable} {kaynak_llama / 'convert_hf_to_gguf.py'} {birlesik} --outtype f16 --outfile {f16}")
        sh(f"LD_LIBRARY_PATH={bin_k} {bin_k / 'llama-quantize'} {f16} {hedef} Q4_K_M")
        f16.unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001 - Unsloth'un kendi dönüştürücüsüyle yeniden dene
        bildir(f"Dönüştürme yedek yolla deneniyor ({e})")
        model.save_pretrained_gguf(str(GECICI / "gguf"), tokenizer, quantization_method="q4_k_m")
        aday = [p for p in (GECICI / "gguf").rglob("*.gguf") if "mmproj" not in p.name.lower()]
        shutil.move(str(max(aday, key=lambda p: p.stat().st_size)), hedef)
    bildir(f"GGUF: {hedef.name} ({hedef.stat().st_size / 1e9:.2f} GB)")
    del model, egitici
    gc.collect()
    torch.cuda.empty_cache()
    shutil.rmtree(birlesik, ignore_errors=True)
    os.environ.pop("CUDA_VISIBLE_DEVICES", None)               # sınav sunucusu bütün kartları görsün

    # Sınav: temel model ile eğitilen model, eğitimde hiç görülmemiş sorularda, programın karnesiyle
    karne_temel, karne_yeni, kapi_sonucu = sina(veri_k, bin_k, katalog_modeli(katalog_kimlik), hedef, arg.sinav,
                                                 bas + arg.sure_saat * 3600 - 15 * 60)
    bilgi = {
        "kimlik": kimlik, "ad": f"Akıl Hocası {arg.ogrenci} (Kaggle eğitimli, {surum})", "tur": "sohbet",
        "baglam": 8192, "dusunme": False, "temel": katalog_kimlik, "en_az_bellek_gb": bellek,
        "oncelik": 80 if kapi_sonucu[0] else 0, "dosya": hedef.name,
        "egitim": {"tarih": datetime.now().isoformat(timespec="seconds"), "ornek": len(ciftler),
                   "adim": sonuc.global_step, "kayip": [round(kayiplar[0], 3), round(kayiplar[-1], 3)] if kayiplar else [],
                   "karne_temel": karne_temel, "karne_yeni": karne_yeni, "kapi": kapi_sonucu[0],
                   "gerekce": kapi_sonucu[1], "program": _surum()}}
    (model_k / f"{kimlik}.json").write_text(json.dumps(bilgi, ensure_ascii=False, indent=1), "utf-8")
    rapor_yaz(model_k / "EGITIM_RAPORU.md", bilgi, secilen)
    bildir(("Gelişim kapısı GEÇİLDİ" if kapi_sonucu[0] else "Gelişim kapısı geçilemedi") + f": {kapi_sonucu[1]}")
    bildir(f"Çıktı: {model_k} (Output sekmesinden indirip Zekâ › Eğitilmiş modeli ekle ile yükleyin)")


def sina(veri_k: Path, bin_k: Path, temel: Path, yeni: Path, sinir: int, bitis: float):
    from akil_hocasi.cekirdek.gelisim import GelisimDongusu
    from akil_hocasi.cekirdek.karne import kapi
    from akil_hocasi.library.db import Kutuphane
    from akil_hocasi.yz.sunucu import SunucuModeli
    sorular = []
    if (veri_k / "sinav.jsonl").is_file():
        for satir in (veri_k / "sinav.jsonl").read_text("utf-8").splitlines():
            try:
                x = json.loads(satir)
                sorular.append({"soru": x["soru"], "beklenen_dayanak": x.get("beklenen_dayanak", []),
                                "beklenen_ifade": ""})
            except (ValueError, KeyError):
                continue
    sorular = sorular[:sinir]
    k = Kutuphane(veri_k / "kutuphane.db")
    anlam, sa = None, None
    try:
        anlam, sa = anlam_kur(k, bin_k)
    except Exception as e:  # noqa: BLE001
        bildir(f"Anlam araması olmadan sınanıyor ({e})")
    s = servisler(k, anlam)
    sonuclar = []
    pay = (bitis - time.monotonic()) / 2
    try:
        for ad, yol in (("temel", temel), ("yeni", yeni)):
            sv = sunucu(yol, "sohbet", bin_k, 8192, 1, ["--jinja"])
            try:
                s.hat.model = SunucuModeli(sv, ad, dusunme_destegi=False)
                g = GelisimDongusu(s.hat, k, s.strateji, s.dersler, bildir)
                karne = g.sinav(sorular, time.monotonic() + pay)
                sonuclar.append(karne)
                bildir(f"Sınav ({ad}): {karne.toplam} soru, başarı %{round(100 * karne.basari)}, "
                       f"kritik {karne.kritik}, ilke ortalaması {karne.ortalama():.3f}")
            finally:
                sv.durdur()
    finally:
        if sa:
            sa.durdur()
    eski, yeni_k = sonuclar
    return eski.sozluk(), yeni_k.sozluk(), kapi(eski, yeni_k)


def rapor_yaz(yol: Path, bilgi: dict, secilen: list[dict]) -> None:
    from akil_hocasi.cekirdek.ilkeler import ILKELER
    e = bilgi["egitim"]
    t, y = e["karne_temel"], e["karne_yeni"]
    satirlar = [f"# {bilgi['ad']}", "", f"- Temel model: {bilgi['temel']}", f"- Eğitim örneği: {e['ornek']}",
                f"- Adım: {e['adim']}, kayıp: {' → '.join(map(str, e['kayip']))}",
                f"- Gelişim kapısı: **{'geçti' if e['kapi'] else 'geçemedi'}** — {e['gerekce']}", "",
                "## Görevlere göre örnek", ""]
    for g in sorted({o["gorev"] for o in secilen}):
        satirlar.append(f"- {g}: {sum(1 for o in secilen if o['gorev'] == g)}")
    satirlar += ["", "## İlke karnesi (eğitimde görülmemiş sınav soruları)", "", "| İlke | Temel | Eğitilmiş |",
                 "| --- | --- | --- |"]
    for i in ILKELER:
        a, b = t["notlar"].get(i.kod), y["notlar"].get(i.kod)
        if a is not None or b is not None:
            satirlar.append(f"| {i.ad} | {a if a is not None else '—'} | {b if b is not None else '—'} |")
    satirlar += ["", f"Başarı: %{round(100 * t['basari'])} → %{round(100 * y['basari'])}; kritik hata: "
                     f"{t['kritik']} → {y['kritik']}; soru sayısı: {y['toplam']}", "",
                 "Program bu modeli Zekâ › Eğitilmiş modeli ekle ile alır; kendi bilgisayarındaki altın soru setiyle "
                 "yeniden sınar ve daha iyi değilse kullanmaz."]
    yol.write_text("\n".join(satirlar), "utf-8")


# ---------------------------------------------------------------------------- komut satırı
def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    alt = p.add_subparsers(dest="komut", required=True)
    v = alt.add_parser("veri", help="öğretmenle eğitim verisi üret (1. defter)")
    v.add_argument("--sure-saat", type=float, default=10.5)
    v.add_argument("--soru", type=int, default=4000, help="bu oturumda en çok işlenecek soru")
    v.add_argument("--paralel", type=int, default=4)
    v.add_argument("--yuva-baglami", type=int, default=16384, help="sunucu yuvası başına bağlam")
    v.add_argument("--ogretmen", choices=sorted(OGRETMENLER), default="Q4_K_M")
    v.add_argument("--ogretmen-adres", default="", help="hazır bir öğretmen sunucusu (derleme/indirme atlanır)")
    v.add_argument("--anlamsiz", action="store_true", help="anlam araması olmadan")
    v.add_argument("--tarama-dk", type=float, default=40, help="TOGÜ sayfalarını tarama süresi (0: tarama yok)")
    v.add_argument("--yazi-orani", type=float, default=0.15)
    e = alt.add_parser("egit", help="öğrenciyi eğit, GGUF'a dönüştür ve sına (2. defter)")
    e.add_argument("--ogrenci", choices=sorted(OGRENCILER), default="4B")
    e.add_argument("--sure-saat", type=float, default=11)
    e.add_argument("--epoch", type=float, default=2)
    e.add_argument("--ogrenme-hizi", type=float, default=1e-4)
    e.add_argument("--lora-r", type=int, default=32)
    e.add_argument("--en-cok-belirtec", type=int, default=6144)
    e.add_argument("--sinav", type=int, default=150, help="sınavda kullanılacak en çok soru")
    e.add_argument("--surum", default="")
    arg = p.parse_args()
    GECICI.mkdir(parents=True, exist_ok=True)
    CALISMA.mkdir(parents=True, exist_ok=True)
    {"veri": veri, "egit": egit}[arg.komut](arg)


if __name__ == "__main__":
    main()
