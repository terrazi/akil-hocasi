"""Dil modelinin gelişimi: eğitim verisi, yerel eğitim ve "daha iyiyse devreye al" kapısı.

- Eğitim verisi yalnızca doğrulama motorundan geçmiş ve personelin "faydalı" işaretlediği
  cevaplardan üretilir; hedef çıktı, doğrulanmış cevabın kendisidir (model doğrulanabilir
  cevap yazmayı öğrenir, mevzuat ezberlemez).
- Yerel eğitim: bilgisayar boştayken ve donanım yeterliyse, ayarlarda tanımlı eğitim komutu
  (ör. llama.cpp ince ayar aracı veya bir LoRA betiği) çalıştırılır. Komut tanımlı değilse ya da
  donanım yetmiyorsa adım atlanır ve veri birikmeye devam eder. İlk/büyük eğitim için Kaggle
  not defteri (egitim/ klasörü) isteğe bağlı bir hızlandırıcıdır.
- Kapı: yeni model ya da ek katman altın soru setinde eskisinden daha başarılı ve kritik hatası
  eskisinden fazla değilse devreye girer; değilse eski model kalır.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from ..answer.llm import TASLAK_ISTEMI
from ..core.maskeleme import metni_maskele
from .degerlendirme import altin_seti_olc


def egitim_verisi_disa_aktar(ogr, yol: Path | str) -> int:
    """Sohbet biçiminde JSONL (SFT) üretir. Dönüş: örnek sayısı."""
    satirlar, gorulen = [], set()
    for r in ogr.db.execute(
            "SELECT soru, girdi, cikti FROM ogr_olaylar WHERE geri_bildirim>0 AND durum!='Doğrudan hüküm yok'"
            " AND girdi!='' AND cikti!='' ORDER BY id"):
        if r["soru"] in gorulen:
            continue
        gorulen.add(r["soru"])
        satirlar.append(json.dumps({"messages": [
            {"role": "system", "content": TASLAK_ISTEMI},
            {"role": "user", "content": metni_maskele(r["girdi"])},
            {"role": "assistant", "content": metni_maskele(r["cikti"])},
        ]}, ensure_ascii=False))
    yol = Path(yol)
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text("\n".join(satirlar) + ("\n" if satirlar else ""), encoding="utf-8")
    return len(satirlar)


def bellek_gb() -> float:
    """Toplam fiziksel bellek (GB)."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MEMORYSTATUSEX()
            m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 1024 ** 3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except (OSError, ValueError, AttributeError):
        return 0.0


def yerel_egitim_uygun_mu(ayarlar, ornek_sayisi: int) -> tuple[bool, str]:
    komut = ayarlar.al("ogrenme.yerel_egitim_komutu", "")
    if not komut:
        return False, "Yerel eğitim komutu tanımlı değil; veri birikmeye devam ediyor"
    if ornek_sayisi < int(ayarlar.al("ogrenme.en_az_ornek", 200)):
        return False, f"Eğitim için en az {ayarlar.al('ogrenme.en_az_ornek', 200)} doğrulanmış örnek gerekiyor ({ornek_sayisi} var)"
    gb = bellek_gb()
    if gb and gb < float(ayarlar.al("ogrenme.en_az_bellek_gb", 15)):
        return False, f"Bellek yetersiz ({gb:.0f} GB); eğitim atlandı"
    return True, "uygun"


def yerel_egitimi_calistir(ayarlar, veri_yolu: Path, temel_model: str, cikti_yolu: Path,
                           zaman_asimi_sn: int = 8 * 3600) -> tuple[bool, str]:
    """Ayarlardaki komutu {veri} {temel_model} {cikti} yer tutucularıyla çalıştırır."""
    sablon = ayarlar.al("ogrenme.yerel_egitim_komutu", "")
    komut = sablon.format(veri=str(veri_yolu), temel_model=temel_model, cikti=str(cikti_yolu))
    try:
        sonuc = subprocess.run(shlex.split(komut, posix=(sys.platform != "win32")), capture_output=True,
                               text=True, timeout=zaman_asimi_sn)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"Eğitim çalıştırılamadı: {e}"
    if sonuc.returncode != 0 or not Path(cikti_yolu).exists():
        return False, f"Eğitim başarısız (kod {sonuc.returncode}): {sonuc.stderr[-300:]}"
    return True, "eğitim tamamlandı"


def modelleri_karsilastir(hat, kutuphane, eski_model, yeni_model) -> dict:
    """Altın sette iki modeli sırayla dener. 'devreye_al' anahtarı kararı verir."""
    import copy
    h = copy.copy(hat)                     # kopya hat: kullanıcının o sıradaki soruları adaya gitmez
    h.model = eski_model
    eski = altin_seti_olc(h, kutuphane, getattr(eski_model, "ad", "eski"))
    h.model = yeni_model
    yeni = altin_seti_olc(h, kutuphane, getattr(yeni_model, "ad", "yeni"))
    if not yeni["toplam"]:
        return {"eski": eski, "yeni": yeni, "devreye_al": False, "neden": "altın soru seti yok"}
    # Önce doğru cevap sayısı; eşitse modelin alıntıya dönülmeden kendi başına doğru cevapladığı soru sayısı
    daha_iyi = (yeni["gecen"], yeni.get("model_kendi", 0)) > (eski["gecen"], eski.get("model_kendi", 0))
    devreye = daha_iyi and yeni["gecen"] >= eski["gecen"] and yeni["kritik"] <= eski["kritik"]
    neden = ("yeni model daha başarılı" if devreye else
             "yeni model daha başarılı değil veya kritik hatası fazla; eski model korunuyor")
    return {"eski": eski, "yeni": yeni, "devreye_al": devreye, "neden": neden}
