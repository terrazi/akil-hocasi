"""Ayarlar ve veri klasörleri.

Tüm veri kullanıcı klasöründe tutulur (yönetici yetkisi gerekmez):
Windows: %LOCALAPPDATA%\\AkilHocasi    Diğer: ~/.local/share/AkilHocasi
"""

from __future__ import annotations

import copy
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

VARSAYILAN_AYARLAR: dict = {
    "profil": {"ad": "", "rol": "Genel", "birim": ""},
    "guncelleme": {
        "acik": True,
        "aralik_dk": 60,             # saat başı hafif kontrol
        "gece_saati": "00:30",       # günün Resmî Gazete'si tam tarama
        "sabah_saati": "08:30",      # "Bugün neler değişti" özeti
        "derin_tarama_bostayken": True,
        "olculu_baglantida_hafif": True,
    },
    "kisayol": {"hizli_yakala": "Win+Shift+Y", "yedek": "Ctrl+Alt+Shift+Y"},
    "ocr": {
        "motor_sirasi": ["windows", "tesseract", "rapidocr"],
        "oylama": True,
        "tesseract_yolu": "",
        "pano_izleme": True,         # Print Screen sonrası "metni al?" bildirimi
    },
    "llm": {
        "model_yolu": "",            # .gguf dosyası; boşsa alıntıya dayalı mod
        "baglam": 8192,
        "is_parcacigi": 0,           # 0 = otomatik
        "bulut_acik": False,         # kurum izni olmadan açılmaz
    },
    "gizlilik": {"maske_varsayilan": True, "gecmis_gun": 30},
    "arayuz": {"tema": "acik", "kaynak_paneli": True},
    "depo": {"disk_siniri_mb": 2048},
    "ogrenme": {
        "acik": True,
        "paylasim_klasoru": "",      # ortak ağ klasörü: bilgisayarlar arası öğrenme paylaşımı
        "yerel_egitim_komutu": "",   # {veri} {temel_model} {cikti} yer tutucularıyla ek katman eğitimi
        "en_az_ornek": 200,
        "en_az_bellek_gb": 15,
    },
    "yz": {
        "sohbet_modeli": "",         # boşsa kurulu modellerin bu bilgisayara uyan en iyisi
        "anlam_modeli": "",
        "model_klasoru": "",         # boşsa veri klasöründeki "modeller"
        "ayna": "",                  # kurum içi Hugging Face aynası (isteğe bağlı)
        "ortak_klasor": "",          # model dosyalarının konduğu ortak ağ klasörü (isteğe bağlı)
        "sunucu_yolu": "",           # boşsa programla gelen llama-server
        "kendini_gelistir": True,    # boştayken gelişim döngüsü (sınav, ders, strateji, model yarışı)
        "gelisim_suresi_dk": 45,
        "kurulum_soruldu": False,
    },
    "gozlem": {
        "acik": True,                # Akıl Hocası Gözlemci eklentisinden gelen sayfaları değerlendir
        "port": 47231,               # yalnız 127.0.0.1
        "anahtar": "",               # eşleştirme anahtarı; ilk açılışta üretilir, eklenti köprüyle kendisi alır
        "motor": {                   # gömülü tarayıcı (görünmez Edge/Chrome, yalıtılmış geçici profil)
            "acik": True,
            "hiz": "normal",         # yavas | normal | hizli
            "en_cok_sayfa": 200,
            "derinlik": 4,
            "tarayici_yolu": "",     # boşsa Edge, yoksa Chrome kendiliğinden bulunur
            # Haftada bir, bilgisayar boştayken taranır (Faz 0'da TOGÜ birim adresleri doğrulanacak)
            "siteler": ["https://kalite.gop.edu.tr/", "https://personel.gop.edu.tr/", "https://strateji.gop.edu.tr/",
                        "https://imid.gop.edu.tr/", "https://ebysyardim.gop.edu.tr/"],
        },
    },
}


def veri_klasoru() -> Path:
    ozel = os.environ.get("AKILHOCASI_VERI")
    if ozel:
        return Path(ozel)
    if sys.platform == "win32":
        taban = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        taban = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return taban / "AkilHocasi"


@dataclass
class Yollar:
    kok: Path

    @property
    def veritabani(self) -> Path:
        return self.kok / "kutuphane.db"

    @property
    def depo(self) -> Path:
        return self.kok / "depo"

    @property
    def modeller(self) -> Path:
        return self.kok / "modeller"

    @property
    def gunluk(self) -> Path:
        return self.kok / "gunluk"

    @property
    def ayarlar(self) -> Path:
        return self.kok / "ayarlar.json"

    def olustur(self) -> "Yollar":
        for p in (self.kok, self.depo, self.modeller, self.gunluk):
            p.mkdir(parents=True, exist_ok=True)
        return self


def _birlestir(taban: dict, ust: dict) -> dict:
    sonuc = copy.deepcopy(taban)
    for k, v in (ust or {}).items():
        if isinstance(v, dict) and isinstance(sonuc.get(k), dict):
            sonuc[k] = _birlestir(sonuc[k], v)
        else:
            sonuc[k] = v
    return sonuc


class Ayarlar:
    """JSON tabanlı ayarlar; eksik anahtarlar varsayılanlarla tamamlanır."""

    def __init__(self, yol: Path):
        self.yol = yol
        self.veri = copy.deepcopy(VARSAYILAN_AYARLAR)
        if yol.exists():
            try:
                self.veri = _birlestir(VARSAYILAN_AYARLAR, json.loads(yol.read_text("utf-8")))
            except (OSError, json.JSONDecodeError):
                pass

    def al(self, yol: str, varsayilan=None):
        dugum = self.veri
        for parca in yol.split("."):
            if not isinstance(dugum, dict) or parca not in dugum:
                return varsayilan
            dugum = dugum[parca]
        return dugum

    def ayarla(self, yol: str, deger) -> None:
        parcalar = yol.split(".")
        dugum = self.veri
        for parca in parcalar[:-1]:
            dugum = dugum.setdefault(parca, {})
        dugum[parcalar[-1]] = deger

    def kaydet(self) -> None:
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        gecici = self.yol.with_suffix(".tmp")
        gecici.write_text(json.dumps(self.veri, ensure_ascii=False, indent=2), "utf-8")
        gecici.replace(self.yol)
