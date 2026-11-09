# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller tarifi: Python yorumlayıcısı ve tüm kütüphaneler gömülü, tek klasörlük Windows uygulaması.

Çalıştırma (proje kökünden):  pyinstaller paketleme/akilhocasi.spec --noconfirm
Çıktı: derleme/dist/AkilHocasi/AkilHocasi.exe  (+ _internal klasörü)
Tek klasör biçimi seçildi: tek dosyaya göre daha hızlı açılır ve virüs tarayıcılarına daha az takılır.
"""

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

KOK = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, KOK)
from akil_hocasi import __version__  # noqa: E402

datas = []
hiddenimports = collect_submodules("akil_hocasi")

for paket in ("rapidocr_onnxruntime", "docx"):
    try:
        datas += collect_data_files(paket)
    except Exception:
        pass

# Windows yerleşik OCR (winrt) modülleri dinamik içe aktarıldığı için açıkça eklenir
for modul in ("winrt.windows.media.ocr", "winrt.windows.globalization", "winrt.windows.graphics.imaging",
              "winrt.windows.storage.streams", "winrt.windows.foundation", "winrt.windows.foundation.collections"):
    try:
        __import__(modul)
        hiddenimports.append(modul)
    except Exception:
        pass

# Taşınabilir Tesseract + Türkçe dil dosyası (derleme hattı derleme/tesseract içine koyar)
tesseract = os.path.join(KOK, "derleme", "tesseract")
if os.path.isdir(tesseract):
    datas.append((tesseract, "tesseract"))

# Yerel model sunucusu: llama.cpp llama-server (CPU) ve DLL'leri (derleme hattı derleme/llama içine koyar).
# Model dosyaları (GGUF) pakete girmez: ilk açılışta bilgisayarın belleğine uygun olanı indirilir.
llama = os.path.join(KOK, "derleme", "llama")
if os.path.isdir(llama):
    datas.append((llama, "llama"))

# Akıl Hocası Gözlemci tarayıcı eklentisi (Chrome/Edge, MV3); ilk açılışta veri klasörüne kopyalanır
datas.append((os.path.join(KOK, "gozlemci_eklenti"), "gozlemci_eklenti"))

# Windows dosya sürüm bilgisi (Özellikler > Ayrıntılar sekmesi)
surum_dosyasi = None
try:
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    parcalar = tuple(int(x) for x in (__version__.split(".") + ["0", "0", "0"])[:4])
    bilgi = VSVersionInfo(
        ffi=FixedFileInfo(filevers=parcalar, prodvers=parcalar),
        kids=[StringFileInfo([StringTable("041F04B0", [
            StringStruct("CompanyName", "Akıl Hocası"),
            StringStruct("FileDescription", "Akıl Hocası — kaynak gösteren mevzuat danışmanı"),
            StringStruct("FileVersion", __version__),
            StringStruct("ProductName", "Akıl Hocası"),
            StringStruct("ProductVersion", __version__),
            StringStruct("OriginalFilename", "AkilHocasi.exe"),
        ])]), VarFileInfo([VarStruct("Translation", [0x041F, 1200])])])
    os.makedirs(os.path.join(KOK, "derleme"), exist_ok=True)
    surum_dosyasi = os.path.join(KOK, "derleme", "surum_bilgisi.txt")
    with open(surum_dosyasi, "w", encoding="utf-8") as f:
        f.write(str(bilgi))
except Exception:
    surum_dosyasi = None

a = Analysis(
    [os.path.join(SPECPATH, "giris.py")],
    pathex=[KOK],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "tkinter", "matplotlib", "IPython", "pytest",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtMultimedia", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml",
        "PySide6.QtDesigner", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSensors",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AkilHocasi",
    console=False,
    icon=os.path.join(SPECPATH, "akilhocasi.ico"),
    version=surum_dosyasi,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AkilHocasi")
