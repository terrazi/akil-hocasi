"""Gözlemci eklentisinin kurulumu: sabit klasöre kopyalama, eşleştirme anahtarı ve kurulum yönergesi.

Eklenti %LOCALAPPDATA%\\AkilHocasi\\gozlemci_eklenti klasörüne kopyalanır; Chrome/Edge "paketlenmemiş
öğe" olarak bu sabit yolu hatırlar, program güncellenince dosyalar yerinde yenilenir.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from .sunucu import VARSAYILAN_PORT, yeni_anahtar

YONERGE = (
    "Akıl Hocası Gözlemci eklentisini Chrome veya Edge'e eklemek için:\n\n"
    "1. Tarayıcıda adres çubuğuna chrome://extensions (Edge: edge://extensions) yazın.\n"
    "2. Sağ üstteki (Edge'de sol alttaki) \"Geliştirici modu\" anahtarını açın.\n"
    "3. \"Paketlenmemiş öğe yükle\" düğmesine basıp açılan gözlemci_eklenti klasörünü seçin.\n"
    "4. Eklentinin Ayarlar sayfasına Akıl Hocası > Ayarlar > Tarayıcı gözlemcisi bölümündeki\n"
    "   eşleştirme anahtarını yapıştırın ve \"Kaydet ve bağlantıyı sına\"ya basın.\n\n"
    "Eklenti yalnızca herkese açık resmî sayfaları okur; KBS, MYS, HYS, EBYS, HİTAP, e-Devlet ve\n"
    "giriş gerektiren sayfalara girmez, hiçbir düğmeye tıklamaz."
)


def eklenti_kaynagi() -> Path:
    """Program paketindeki eklenti klasörü (geliştirmede proje kökündeki klasör)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "gozlemci_eklenti"
    return Path(__file__).resolve().parents[2] / "gozlemci_eklenti"


def _surum(klasor: Path) -> str:
    try:
        return json.loads((klasor / "manifest.json").read_text("utf-8")).get("version", "")
    except (OSError, ValueError):
        return ""


def eklentiyi_hazirla(veri_koku: Path) -> Path | None:
    """Eklentiyi sabit klasöre kopyalar (yoksa ya da sürüm/dosyalar değiştiyse). Hedef yolu döndürür."""
    kaynak = eklenti_kaynagi()
    if not (kaynak / "manifest.json").is_file():
        return None
    hedef = veri_koku / "gozlemci_eklenti"
    degisti = _surum(hedef) != _surum(kaynak) or any(
        not (hedef / p.relative_to(kaynak)).is_file()
        or (hedef / p.relative_to(kaynak)).read_bytes() != p.read_bytes()
        for p in kaynak.rglob("*") if p.is_file())
    if degisti:
        if hedef.exists():
            shutil.rmtree(hedef, ignore_errors=True)
        shutil.copytree(kaynak, hedef, ignore=shutil.ignore_patterns("__pycache__", "*.test.js"))
    return hedef


def anahtari_hazirla(ayarlar) -> str:
    """Eşleştirme anahtarı yoksa üretir ve kaydeder."""
    anahtar = ayarlar.al("gozlem.anahtar", "")
    if not anahtar:
        anahtar = yeni_anahtar()
        ayarlar.ayarla("gozlem.anahtar", anahtar)
        if not ayarlar.al("gozlem.port"):
            ayarlar.ayarla("gozlem.port", VARSAYILAN_PORT)
        ayarlar.kaydet()
    return anahtar


def kurulumu_goster(veri_koku: Path) -> int:
    """Başlat menüsündeki "Gözlemci eklentisini kur" kısayolu: klasörü hazırlar, açar ve yönergeyi gösterir."""
    hedef = eklentiyi_hazirla(veri_koku)
    if hedef is None:
        metin = "Eklenti dosyaları program paketinde bulunamadı. Programı yeniden kurun."
    else:
        metin = YONERGE + f"\n\nEklenti klasörü:\n{hedef}"
    if sys.platform == "win32":
        import ctypes
        import os
        if hedef is not None:
            os.startfile(str(hedef))  # noqa: S606 - kullanıcının kendi klasörü Gezgin'de açılır
        ctypes.windll.user32.MessageBoxW(None, metin, "Akıl Hocası Gözlemci", 0x40)
    else:
        print(metin)
    return 0 if hedef is not None else 1
