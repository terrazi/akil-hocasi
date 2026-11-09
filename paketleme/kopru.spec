# -*- mode: python ; coding: utf-8 -*-
"""Eklenti köprüsü: küçük, tek dosyalık konsol programı (Qt ve ağır kütüphaneler yok).

Çalıştırma (proje kökünden):  pyinstaller paketleme/kopru.spec --noconfirm
Çıktı derleme betiğince AkilHocasi klasörüne, AkilHocasi.exe'nin yanına kopyalanır.
"""

import os
import sys

KOK = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, KOK)

a = Analysis(
    [os.path.join(SPECPATH, "kopru_giris.py")],
    pathex=[KOK],
    binaries=[],
    datas=[],
    hiddenimports=["akil_hocasi.config", "akil_hocasi.gozlem.eslestirme"],
    excludes=[
        "PySide6", "shiboken6", "numpy", "PIL", "cv2", "requests", "urllib3", "sqlite3", "tkinter", "onnxruntime",
        "rapidocr_onnxruntime", "docx", "lxml", "llama_cpp", "pytesseract", "winrt", "pytest",
        "akil_hocasi.ui", "akil_hocasi.library", "akil_hocasi.crawler", "akil_hocasi.ocr", "akil_hocasi.answer",
        "akil_hocasi.ogrenme", "akil_hocasi.core",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AkilHocasiKopru",
    console=True,
    icon=os.path.join(SPECPATH, "akilhocasi.ico"),
    upx=False,
)
