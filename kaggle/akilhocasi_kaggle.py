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


def onceki_egitilmis(ogrenci: str) -> tuple[Path | None, str]:
    """Programın sürüm sayfasında yayımlanmış, Kaggle kapısını geçmiş en yeni eğitilmiş model (aynı boy)."""
    try:
        from akil_hocasi.yz import surum_modeli
        b = surum_modeli.son_egitilmis()
        if not b or not (b["bilgi"].get("egitim") or {}).get("kapi"):
            return None, ""
        if not b["bilgi"]["kimlik"].startswith(f"akilhocasi-{ogrenci.lower()}-"):
            return None, ""
        return surum_modeli.indir(b, GECICI / "onceki"), b["bilgi"]["kimlik"]
    except Exception as e:  # noqa: BLE001
        bildir(f"Önceki eğitilmiş model alınamadı ({e}); temel modelle kıyaslanacak")
        return None, ""


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
        ogretmen = OgretmenModeli(adres, OGRETMENLER.get(arg.ogretmen, ("öğretmen",))[0],
                                  OgretmenModeli.DUSUNEN_GOREVLER if arg.dusunme else ())
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


def onceki_veriler(deneme: bool = False) -> list[Path]:
    """Girdilerdeki önceki veri turlarının klasörleri (eskiden yeniye). Deneme turunun (tur 0) verisi asıl
    turlarla birleştirilmez; yalnız eğitim hattının denemesinde (başka veri yokken) kullanılır."""
    return sorted({p.parent for p in girdide_bul(f"{VERI_ADI}/manifest.json")
                   if deneme or "akilhocasi-veri-0" not in str(p)},
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
    turlar = (onceki_veriler() or onceki_veriler(deneme=True)) + ([yerel] if (yerel / "ornekler.jsonl").is_file() else [])
    if not turlar:
        raise SystemExit("Eğitim verisi bulunamadı: 1. defterin çıktısını 'Add Input' ile bu deftere ekleyin.")
    return turlar


def egit(arg) -> None:
    """Veriyi hazırlar; eğitimi iki kartta (DDP, torchrun) ayrı süreçte yürütür; LoRA'yı asıl tabana birleştirip
    GGUF'a çevirir; temel ve eğitilmiş modeli görülmemiş sorularda sınar."""
    bas = time.monotonic()
    bitis_duvar = time.time() + arg.sure_saat * 3600
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

    tok = belirtecleyici(hf_kimlik)

    def sablon(mesajlar):
        return tok.apply_chat_template(mesajlar, tokenize=False, add_generation_prompt=True, enable_thinking=False)

    def uzunluk(metin):
        return len(tok(metin, add_special_tokens=False)["input_ids"])

    bildir("İstem sonu (çalışırken llama-server'ın üreteceğiyle aynı olmalı): " + repr(sablon(secilen[0]["messages"])[-80:]))
    ciftler, atilan = egitim_metinleri(secilen, sablon, uzunluk, arg.en_cok_belirtec)
    bildir(f"{len(ciftler)} örnek eğitime giriyor, {atilan} örnek uzunluk sınırını aştı")
    veri_dosyasi = GECICI / "egitim_ciftleri.jsonl"
    veri_dosyasi.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in ciftler), "utf-8")

    # Eğitim: iki kart varsa DDP; olmazsa tek kart. Dönüştürme ve sınav payı ayrılır.
    pay = min(arg.sinav_payi_saat * 3600, 0.4 * arg.sure_saat * 3600)
    egitim_bitis = bitis_duvar - pay
    uyarlayici, istatistik = GECICI / "lora", GECICI / "egitim_istatistik.json"
    kart = gpu_sayisi()
    # Denemeler sırayla: fp32 hesap (T4'te emüle bf16 katmanları yavaşlatıyor), Unsloth'un varsayılanı, tek kart.
    denemeler = ([(kart, "fp32"), (kart, "oto")] if kart > 1 else []) + [(1, "fp32"), (1, "oto")]
    for n, hesap in denemeler:
        shutil.rmtree(uyarlayici, ignore_errors=True)
        istatistik.unlink(missing_ok=True)
        if time.time() > egitim_bitis - 600:
            break
        ortam = {**os.environ}
        ortam.pop("CUDA_VISIBLE_DEVICES", None)
        betik = [str(Path(__file__).resolve()), "ogren", "--model", hf_kimlik, "--veri", str(veri_dosyasi),
                 "--cikti", str(uyarlayici), "--istatistik", str(istatistik), "--bitis", str(egitim_bitis),
                 "--epoch", str(arg.epoch), "--ogrenme-hizi", str(arg.ogrenme_hizi), "--lora-r", str(arg.lora_r),
                 "--en-cok-belirtec", str(arg.en_cok_belirtec), "--dort-bit", arg.dort_bit,
                 "--ornek-sn", str(arg.ornek_sn), "--hesap", hesap]
        if n > 1:
            komut = [sys.executable, "-m", "torch.distributed.run", "--standalone", f"--nproc_per_node={n}"] + betik
        else:
            ortam["CUDA_VISIBLE_DEVICES"] = "0"
            komut = [sys.executable] + betik
        bildir(f"Eğitim {n} kartta başlıyor (hesap: {hesap})")
        r = subprocess.run(komut, env=ortam)
        if r.returncode == 0 and (uyarlayici / "adapter_config.json").is_file():
            break
        bildir(f"{n} kart / {hesap} eğitimi başarısız (çıkış {r.returncode}); sonraki deneme")
    if not (uyarlayici / "adapter_config.json").is_file():
        raise SystemExit("Eğitim tamamlanamadı (uyarlayıcı yok)")
    ist = json.loads(istatistik.read_text("utf-8")) if istatistik.is_file() else {}
    kayiplar = ist.get("kayip", [])
    bildir(f"Eğitim bitti: {ist.get('adim', '?')} adım, {ist.get('kart', '?')} kart, "
           f"{ist.get('epoch', '?')} dönem, örnek başına {ist.get('ornek_sn', '?')} sn"
           + (f", kayıp {kayiplar[0]:.3f} → {kayiplar[-1]:.3f}" if kayiplar else ""))

    # GGUF'a dönüştürme
    surum = arg.surum or datetime.now().strftime("%Y%m%d")
    kimlik = f"akilhocasi-{arg.ogrenci.lower()}-{surum}"
    model_k = CALISMA / MODEL_ADI
    model_k.mkdir(parents=True, exist_ok=True)
    hedef = model_k / f"{kimlik}.gguf"
    bin_k = llama_hazirla(gpu=True)
    birlesik = GECICI / "birlesik"
    temiz_birlestir(uyarlayici, hf_kimlik, birlesik)
    kaynak_llama = GECICI / "llama.cpp"
    if not kaynak_llama.is_dir():
        sh(f"git clone --depth 1 https://github.com/ggml-org/llama.cpp {kaynak_llama}")
    sh(f"{sys.executable} -m pip install -q {kaynak_llama / 'gguf-py'} sentencepiece protobuf")
    f16 = GECICI / f"{kimlik}-f16.gguf"
    sh(f"{sys.executable} {kaynak_llama / 'convert_hf_to_gguf.py'} {birlesik} --outtype f16 --outfile {f16}")
    sh(f"{bin_k / 'llama-quantize'} {f16} {hedef} Q4_K_M", env=llama_ortami(bin_k))
    f16.unlink(missing_ok=True)
    shutil.rmtree(birlesik, ignore_errors=True)
    shutil.copytree(uyarlayici, model_k / "lora", dirs_exist_ok=True)   # sonraki turlar isterse buradan sürdürebilir
    bildir(f"GGUF: {hedef.name} ({hedef.stat().st_size / 1e9:.2f} GB)")

    # Sınav: temel model ile eğitilen model, eğitimde hiç görülmemiş sorularda, programın karnesiyle
    sinav_bitis = time.monotonic() + max(600.0, bitis_duvar - time.time() - 15 * 60)
    # Kıyas modeli: yayımlanmış ve kapıyı geçmiş önceki eğitilmiş model varsa o (yeni model ondan iyi olmalı),
    # yoksa katalogdaki temel model. Her yeni tur tabandan, birikmiş bütün veriyle yeniden eğitilir.
    kiyas_yolu, kiyas_adi = onceki_egitilmis(arg.ogrenci)
    if kiyas_yolu is None:
        kiyas_yolu, kiyas_adi = katalog_modeli(katalog_kimlik), katalog_kimlik
    bildir(f"Kıyas modeli: {kiyas_adi}")
    karne_temel, karne_yeni, kapi_sonucu = sina(veri_k, bin_k, kiyas_yolu, hedef, arg.sinav, sinav_bitis)
    bilgi = {
        "kimlik": kimlik, "ad": f"Akıl Hocası {arg.ogrenci} (Kaggle eğitimli, {surum})", "tur": "sohbet",
        "baglam": 8192, "dusunme": False, "temel": katalog_kimlik, "en_az_bellek_gb": bellek,
        "oncelik": 80 if kapi_sonucu[0] else 0, "dosya": hedef.name, "kiyas": kiyas_adi,
        "egitim": {"tarih": datetime.now().isoformat(timespec="seconds"), "ornek": len(ciftler),
                   "adim": ist.get("adim", 0), "dongu": ist.get("epoch"), "kart": ist.get("kart"),
                   "kayip": [round(kayiplar[0], 3), round(kayiplar[-1], 3)] if kayiplar else [],
                   "karne_temel": karne_temel, "karne_yeni": karne_yeni, "kapi": kapi_sonucu[0],
                   "gerekce": kapi_sonucu[1], "program": _surum(), "sure_dk": round((time.monotonic() - bas) / 60)}}
    (model_k / f"{kimlik}.json").write_text(json.dumps(bilgi, ensure_ascii=False, indent=1), "utf-8")
    rapor_yaz(model_k / "EGITIM_RAPORU.md", bilgi, secilen)
    bildir(("Gelişim kapısı GEÇİLDİ" if kapi_sonucu[0] else "Gelişim kapısı geçilemedi") + f": {kapi_sonucu[1]}")
    bildir(f"Çıktı: {model_k} (Output sekmesinden indirip Zekâ › Eğitilmiş modeli ekle ile yükleyin)")


def belirtecleyici(hf_kimlik: str):
    """Yalnız metin belirteçleyicisi (model yüklenmez; ana süreç kartı boş bırakır)."""
    from transformers import AutoProcessor, AutoTokenizer
    try:
        return AutoTokenizer.from_pretrained(hf_kimlik)
    except Exception:  # noqa: BLE001
        p = AutoProcessor.from_pretrained(hf_kimlik)
        return getattr(p, "tokenizer", p)


def llama_ortami(bin_k: Path) -> dict:
    """llama.cpp araçları için ortam: derleme kütüphaneleri öne eklenir, mevcut yol (CUDA sürücüsü) korunur."""
    return {**os.environ, "LD_LIBRARY_PATH": f"{bin_k}:{os.environ.get('LD_LIBRARY_PATH', '')}"}


def ogren(arg) -> None:
    """Eğitim süreci (torchrun ile her kartta bir tane). 4 bit taban + LoRA; süre dolunca bütün süreçler aynı adımda
    durur; 0. süreç uyarlayıcıyı ve istatistiği kaydeder."""
    import torch
    import torch.distributed as dist
    from unsloth import FastLanguageModel  # noqa: I001 - unsloth, transformers'tan önce yüklenmeli
    from transformers import DataCollatorForSeq2Seq, Trainer, TrainerCallback, TrainingArguments
    from datasets import Dataset
    sira, dunya = int(os.environ.get("LOCAL_RANK", 0)), int(os.environ.get("WORLD_SIZE", 1))
    if dunya > 1:
        torch.cuda.set_device(sira)
    ana = int(os.environ.get("RANK", 0)) == 0
    kart_gb = torch.cuda.get_device_properties(0).total_memory / 2**30
    dort_bit = arg.dort_bit == "evet" or (arg.dort_bit == "oto" and kart_gb < 20)
    if ana:
        bildir(f"Eğitim kipi: {'4 bit taban (QLoRA)' if dort_bit else '16 bit taban (LoRA)'}; {dunya} kart, {kart_gb:.1f} GB")
    ek = {"device_map": {"": f"cuda:{sira}"}} if dunya > 1 else {}
    if arg.hesap == "fp32" and torch.cuda.get_device_capability(sira)[0] < 8:
        ek["dtype"] = torch.float32
    model, tokenizer = FastLanguageModel.from_pretrained(model_name=arg.model, max_seq_length=arg.en_cok_belirtec,
                                                         load_in_4bit=dort_bit, load_in_16bit=not dort_bit,
                                                         full_finetuning=False, **ek)
    tok = getattr(tokenizer, "tokenizer", tokenizer)
    ciftler = [json.loads(s) for s in Path(arg.veri).read_text("utf-8").splitlines() if s.strip()]

    def kodla(c):
        p = tok(c["prompt"], add_special_tokens=False)["input_ids"]
        t = tok(c["completion"] + "<|im_end|>", add_special_tokens=False)["input_ids"]
        return {"input_ids": p + t, "attention_mask": [1] * (len(p) + len(t)), "labels": [-100] * len(p) + t}

    veri_seti = Dataset.from_list([{"prompt": c["prompt"], "completion": c["completion"]} for c in ciftler])
    veri_seti = veri_seti.map(kodla, remove_columns=["prompt", "completion"])
    model = FastLanguageModel.get_peft_model(
        model, r=arg.lora_r, lora_alpha=arg.lora_r, lora_dropout=0, bias="none", random_state=3407,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth")

    # Dönem sayısı süreye sığdırılır (kosinüs takvimi tamamlansın): örnek başına süre denemeden ölçüldü.
    kalan = max(600.0, arg.bitis - time.time())
    sigan = kalan / max(1.0, len(veri_seti) * arg.ornek_sn / dunya)
    donem = round(min(arg.epoch, max(0.3, 0.9 * sigan)), 2)
    birikim = max(1, 8 // dunya)
    toplam_adim = max(1, int(len(veri_seti) * donem / (birikim * dunya)))
    if ana:
        bildir(f"{len(veri_seti)} örnek, {donem} dönem ({toplam_adim} adım, etkin parti {birikim * dunya}); "
               f"kalan süre {kalan / 3600:.1f} saat")

    class SureSiniri(TrainerCallback):
        def on_step_end(self, args, state, control, **kw):
            dur = torch.tensor([1.0 if time.time() > arg.bitis else 0.0], device=f"cuda:{sira}")
            if dunya > 1:
                dist.all_reduce(dur, op=dist.ReduceOp.MAX)          # bütün süreçler aynı adımda dursun
            if dur.item() > 0:
                if ana:
                    bildir("Süre bütçesi doldu; eğitim burada tamamlanıyor")
                control.should_training_stop = True
            return control

    bf16 = torch.cuda.get_device_capability(sira)[0] >= 8      # T4 (7.5): bf16 yok; Unsloth qwen3_5'i fp32 hesaplar
    ayar = TrainingArguments(
        output_dir=str(GECICI / "egitim"), per_device_train_batch_size=1, gradient_accumulation_steps=birikim,
        num_train_epochs=donem, learning_rate=arg.ogrenme_hizi, warmup_steps=max(1, int(0.03 * toplam_adim)),
        lr_scheduler_type="cosine", logging_steps=5, save_strategy="no", report_to="none", optim="adamw_8bit",
        weight_decay=0.01, bf16=bf16, fp16=False, seed=3407, remove_unused_columns=False,
        ddp_find_unused_parameters=False if dunya > 1 else None)
    egitici = Trainer(model=model, args=ayar, train_dataset=veri_seti,
                      data_collator=DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100),
                      callbacks=[SureSiniri()])
    bas = time.time()
    sonuc = egitici.train()
    if ana:
        kayiplar = [x["loss"] for x in egitici.state.log_history if "loss" in x]
        gecen = time.time() - bas
        islenen = sonuc.global_step * birikim * dunya
        model.save_pretrained(arg.cikti)
        tokenizer.save_pretrained(arg.cikti)
        Path(arg.istatistik).write_text(json.dumps({
            "adim": sonuc.global_step, "kayip": kayiplar, "kart": dunya, "epoch": round(islenen / len(veri_seti), 2),
            "ornek_sn": round(gecen * dunya / max(1, islenen), 1)}, ensure_ascii=False), "utf-8")
        bildir(f"Uyarlayıcı kaydedildi: {sonuc.global_step} adım, {gecen / 60:.0f} dk")
    if dunya > 1:
        dist.barrier()
        dist.destroy_process_group()


def temiz_birlestir(uyarlayici: Path, hf_kimlik: str, hedef: Path) -> None:
    """LoRA'yı asıl (16 bit) tabana CPU'da birleştirir: 4 bit eğitimin nicemleme hatası modele işlenmez. Olmazsa
    Unsloth ile uyarlayıcıdan birleştirilir."""
    import torch
    import transformers
    from peft import PeftModel
    taban = None
    for sinif in ("AutoModelForImageTextToText", "AutoModelForCausalLM"):
        try:
            taban = getattr(transformers, sinif).from_pretrained(hf_kimlik, dtype=torch.bfloat16, device_map="cpu",
                                                                 low_cpu_mem_usage=True)
            break
        except Exception as e:  # noqa: BLE001
            bildir(f"Taban {sinif} ile yüklenemedi: {type(e).__name__}: {str(e)[:200]}")
    try:
        if taban is None:
            raise RuntimeError("taban model yüklenemedi")
        birlesik = PeftModel.from_pretrained(taban, str(uyarlayici)).merge_and_unload()
        hedef.mkdir(parents=True, exist_ok=True)
        birlesik.save_pretrained(str(hedef), safe_serialization=True)
        for sinif in ("AutoProcessor", "AutoTokenizer"):
            try:
                getattr(transformers, sinif).from_pretrained(str(uyarlayici)).save_pretrained(str(hedef))
                break
            except Exception:  # noqa: BLE001
                continue
        bildir("LoRA asıl 16 bit tabana CPU'da birleştirildi")
        del birlesik, taban
    except Exception as e:  # noqa: BLE001
        bildir(f"Temiz birleştirme olmadı ({type(e).__name__}: {str(e)[:200]}); Unsloth birleştirmesi kullanılıyor")
        shutil.rmtree(hedef, ignore_errors=True)
        from unsloth import FastLanguageModel
        model, tokenizer = FastLanguageModel.from_pretrained(model_name=str(uyarlayici), load_in_4bit=False,
                                                             load_in_16bit=True)
        model.save_pretrained_merged(str(hedef), tokenizer, save_method="merged_16bit")


def gpu_sayisi() -> int:
    try:
        c = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=30)
        return max(1, sum(1 for s in c.stdout.splitlines() if s.startswith("GPU")))
    except (OSError, subprocess.SubprocessError):
        return 1


def sina(veri_k: Path, bin_k: Path, temel: Path, yeni: Path, sinir: int, bitis: float):
    """Temel ve eğitilmiş modeli aynı sorularda, aynı anda (her biri kendi kartında) programın karnesiyle sınar.
    Süre biterse karşılaştırma iki modelin de cevapladığı ortak sorularla yapılır (adil kıyas)."""
    from akil_hocasi.cekirdek.karne import kapi, karne_hesapla
    from akil_hocasi.library.db import Kutuphane
    from akil_hocasi.ogrenme.degerlendirme import altin_sonucu
    from akil_hocasi.yz.sunucu import SunucuModeli
    sorular = []
    if (veri_k / "sinav.jsonl").is_file():
        for satir in (veri_k / "sinav.jsonl").read_text("utf-8").splitlines():
            try:
                x = json.loads(satir)
                sorular.append({"soru": x["soru"], "beklenen_dayanak": x.get("beklenen_dayanak", [])})
            except (ValueError, KeyError):
                continue
    sorular = sorular[:sinir]
    bildir(f"Sınav: {len(sorular)} görülmemiş soru, temel ve eğitilmiş model aynı anda")
    k = Kutuphane(veri_k / "kutuphane.db")
    anlam, sa = None, None
    try:
        anlam, sa = anlam_kur(k, bin_k)
    except Exception as e:  # noqa: BLE001
        bildir(f"Anlam araması olmadan sınanıyor ({e})")
    kart = gpu_sayisi()
    sunucular, sonuclar = {}, {}
    try:
        for i, (ad, yol) in enumerate((("temel", temel), ("yeni", yeni))):
            onceki = os.environ.get("CUDA_VISIBLE_DEVICES")
            os.environ["CUDA_VISIBLE_DEVICES"] = str(i % kart)        # her model kendi kartında
            try:
                sunucular[ad] = sunucu(yol, "sohbet", bin_k, 8192, 1, ["--jinja"])
            finally:
                if onceki is None:
                    os.environ.pop("CUDA_VISIBLE_DEVICES", None)
                else:
                    os.environ["CUDA_VISIBLE_DEVICES"] = onceki

        def calis(ad: str) -> None:
            s = servisler(k, anlam)
            s.hat.model = SunucuModeli(sunucular[ad], ad, dusunme_destegi=False)
            liste = sonuclar.setdefault(ad, [])
            for n, soru in enumerate(sorular, 1):
                if time.monotonic() > bitis:
                    break
                try:
                    c = s.hat.cevapla(soru["soru"], "derin", kayit=False)
                    gecti, kritik = altin_sonucu(c, soru["beklenen_dayanak"], "")
                    liste.append((c, {"netlestirme": False}, gecti, kritik))
                except Exception as e:  # noqa: BLE001
                    bildir(f"Sınav sorusu işlenemedi ({ad}): {e}")
                    liste.append(None)
                if n % 25 == 0:
                    bildir(f"Sınav ({ad}): {n} soru")

        isler = [threading.Thread(target=calis, args=(ad,), daemon=True) for ad in sunucular]
        for x in isler:
            x.start()
        for x in isler:
            x.join()
    finally:
        for sv in sunucular.values():
            sv.durdur()
        if sa:
            sa.durdur()
    n = min(len(sonuclar.get("temel", [])), len(sonuclar.get("yeni", [])))
    ortak = [i for i in range(n) if sonuclar["temel"][i] is not None and sonuclar["yeni"][i] is not None]
    eski = karne_hesapla([sonuclar["temel"][i] for i in ortak])
    yeni_k = karne_hesapla([sonuclar["yeni"][i] for i in ortak])
    for ad, karne in (("temel", eski), ("yeni", yeni_k)):
        bildir(f"Sınav ({ad}): {karne.toplam} ortak soru, başarı %{round(100 * karne.basari)}, "
               f"kritik {karne.kritik}, ilke ortalaması {karne.ortalama():.3f}")
    return eski.sozluk(), yeni_k.sozluk(), kapi(eski, yeni_k)


def rapor_yaz(yol: Path, bilgi: dict, secilen: list[dict]) -> None:
    from akil_hocasi.cekirdek.ilkeler import ILKELER
    e = bilgi["egitim"]
    t, y = e["karne_temel"], e["karne_yeni"]
    satirlar = [f"# {bilgi['ad']}", "", f"- Temel model: {bilgi['temel']}",
                f"- Sınavda kıyaslanan: {bilgi.get('kiyas') or bilgi['temel']}", f"- Eğitim örneği: {e['ornek']}",
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
    def isabet(k):
        return f"%{round(100 * (k['dogrulanan'] - k['kritik']) / k['dogrulanan'])}" if k.get("dogrulanan") else "—"

    satirlar += ["", f"Başarı: %{round(100 * t['basari'])} → %{round(100 * y['basari'])}; kritik hata: "
                     f"{t['kritik']} → {y['kritik']}; güvenle verilen cevapların isabeti: {isabet(t)} → {isabet(y)}; "
                     f"soru sayısı: {y['toplam']}", "",
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
    v.add_argument("--paralel", type=int, default=8, help="öğretmen sunucusundaki eşzamanlı istek (yuva)")
    v.add_argument("--yuva-baglami", type=int, default=12288, help="sunucu yuvası başına bağlam")
    v.add_argument("--dusunme", action="store_true", help="öğretmen sentez/düzeltme/yazıda düşünsün (yavaş)")
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
    e.add_argument("--dort-bit", choices=["oto", "evet", "hayir"], default="oto",
                   help="taban model eğitimde 4 bit (QLoRA); oto: 20 GB'tan küçük kartta")
    e.add_argument("--sinav", type=int, default=150, help="sınavda kullanılacak en çok soru")
    e.add_argument("--surum", default="")
    e.add_argument("--sinav-payi-saat", type=float, default=1.75, help="dönüştürme ve sınava ayrılan saat")
    e.add_argument("--ornek-sn", type=float, default=22.0,
                   help="kart başına örnek eğitim süresi tahmini, sn (T4 QLoRA ölçümü ~22; dönemi süreye sığdırır)")
    o = alt.add_parser("ogren", help="(iç) eğitim süreci; egit tarafından torchrun ile başlatılır")
    o.add_argument("--model", required=True)
    o.add_argument("--veri", required=True)
    o.add_argument("--cikti", required=True)
    o.add_argument("--istatistik", required=True)
    o.add_argument("--bitis", type=float, required=True, help="duvar saati (time.time) cinsinden son an")
    o.add_argument("--epoch", type=float, default=2)
    o.add_argument("--ogrenme-hizi", type=float, default=1e-4)
    o.add_argument("--lora-r", type=int, default=32)
    o.add_argument("--en-cok-belirtec", type=int, default=6144)
    o.add_argument("--dort-bit", choices=["oto", "evet", "hayir"], default="oto")
    o.add_argument("--ornek-sn", type=float, default=22.0)
    o.add_argument("--hesap", choices=["oto", "fp32"], default="oto")
    arg = p.parse_args()
    GECICI.mkdir(parents=True, exist_ok=True)
    CALISMA.mkdir(parents=True, exist_ok=True)
    {"veri": veri, "egit": egit, "ogren": ogren}[arg.komut](arg)


if __name__ == "__main__":
    main()
