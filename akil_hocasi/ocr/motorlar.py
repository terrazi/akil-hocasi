"""OCR motorları: Windows.Media.Ocr, Tesseract (tur), RapidOCR (PaddleOCR modelleri, ONNX).

Her motor gri numpy görüntü alır, kelime kutularıyla OcrSonuc döndürür.
Kurulu olmayan motor kullanilabilir() = False döner; program kalan motorlarla çalışır.
"""

from __future__ import annotations

import asyncio
import sys
import time

import numpy as np

from .sonuc import OcrKelime, OcrSonuc


class OcrMotoru:
    ad = "temel"

    def kullanilabilir(self) -> bool:
        return False

    def oku(self, g: np.ndarray) -> OcrSonuc:
        raise NotImplementedError


# ------------------------------------------------------------------ Tesseract

def paketteki_tesseract() -> str:
    """Kurulum paketiyle gelen taşınabilir Tesseract'ın yolu (yoksa boş).

    PyInstaller paketinde veri dosyaları exe'nin yanındaki '_internal' klasörüne
    (sys._MEIPASS) ya da doğrudan exe klasörüne konur; ikisine de bakılır.
    """
    import os
    from pathlib import Path
    adaylar = []
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            adaylar.append(Path(sys._MEIPASS) / "tesseract")
        adaylar.append(Path(sys.executable).parent / "tesseract")
    for klasor in adaylar:
        exe = klasor / ("tesseract.exe" if sys.platform == "win32" else "tesseract")
        if exe.is_file():
            os.environ.setdefault("TESSDATA_PREFIX", str(klasor / "tessdata"))
            return str(exe)
    return ""


class TesseractMotoru(OcrMotoru):
    ad = "Tesseract"

    def __init__(self, yol: str = ""):
        self.yol = yol or paketteki_tesseract()
        self._durum: bool | None = None

    def kullanilabilir(self) -> bool:
        if self._durum is None:
            try:
                import pytesseract
                if self.yol:
                    pytesseract.pytesseract.tesseract_cmd = self.yol
                self._durum = "tur" in pytesseract.get_languages(config="")
            except Exception:
                self._durum = False
        return self._durum

    def oku(self, g: np.ndarray) -> OcrSonuc:
        import pytesseract
        bas = time.time()
        veri = pytesseract.image_to_data(g, lang="tur", config="--oem 1 --psm 3",
                                         output_type=pytesseract.Output.DICT)
        kelimeler = []
        for i, metin in enumerate(veri["text"]):
            metin = (metin or "").strip()
            if not metin:
                continue
            guven = float(veri["conf"][i])
            kelimeler.append(OcrKelime(metin, int(veri["left"][i]), int(veri["top"][i]),
                                       int(veri["width"][i]), int(veri["height"][i]),
                                       max(0.0, guven) / 100.0))
        return OcrSonuc(kelimeler, self.ad, g.shape[1], g.shape[0], time.time() - bas)


# ------------------------------------------------------------------ RapidOCR

class RapidOcrMotoru(OcrMotoru):
    """Satır düzeyinde okur; kelime kutuları satır içinde karakter oranına göre bölünür.

    Türkçe karakterler için PaddleOCR 'latin' tanıma modeli önerilir (README'ye bakınız).
    """
    ad = "RapidOCR"

    def __init__(self, tanima_modeli: str = "", sozluk: str = ""):
        self._motor = None
        self._durum: bool | None = None
        self.tanima_modeli = tanima_modeli
        self.sozluk = sozluk

    def kullanilabilir(self) -> bool:
        if self._durum is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
                kw = {}
                if self.tanima_modeli:
                    kw["rec_model_path"] = self.tanima_modeli
                if self.sozluk:
                    kw["rec_keys_path"] = self.sozluk
                self._motor = RapidOCR(**kw)
                self._durum = True
            except Exception:
                self._durum = False
        return self._durum

    def oku(self, g: np.ndarray) -> OcrSonuc:
        bas = time.time()
        sonuc, _ = self._motor(g)
        kelimeler = []
        for kutu, metin, guven in sonuc or []:
            xs = [p[0] for p in kutu]
            ys = [p[1] for p in kutu]
            x0, y0, x1, y1 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
            parcalar = metin.split()
            toplam = max(1, len(metin))
            imlec = x0
            for p in parcalar:
                gen = int((x1 - x0) * (len(p) / toplam))
                kelimeler.append(OcrKelime(p, imlec, y0, max(1, gen), y1 - y0, float(guven)))
                imlec += gen + int((x1 - x0) / toplam)
        return OcrSonuc(kelimeler, self.ad, g.shape[1], g.shape[0], time.time() - bas)


# ------------------------------------------------------------------ Windows OCR

class WindowsOcrMotoru(OcrMotoru):
    """Windows 10/11 yerleşik OCR. Türkçe dil paketi yüklü olmalıdır (Ayarlar > Dil)."""
    ad = "Windows OCR"

    def __init__(self, dil: str = "tr"):
        self.dil = dil
        self._durum: bool | None = None
        self._modul = None

    def _yukle(self):
        for kok in ("winsdk", "winrt"):
            try:
                ocr = __import__(f"{kok}.windows.media.ocr", fromlist=["OcrEngine"])
                glob = __import__(f"{kok}.windows.globalization", fromlist=["Language"])
                img = __import__(f"{kok}.windows.graphics.imaging", fromlist=["SoftwareBitmap"])
                akis = __import__(f"{kok}.windows.storage.streams", fromlist=["DataWriter"])
                return ocr, glob, img, akis
            except ImportError:
                continue
        return None

    def kullanilabilir(self) -> bool:
        if self._durum is None:
            self._durum = False
            if sys.platform == "win32":
                self._modul = self._yukle()
                if self._modul:
                    ocr, glob, _, _ = self._modul
                    try:
                        self._durum = ocr.OcrEngine.is_language_supported(glob.Language(self.dil))
                    except Exception:
                        self._durum = False
        return self._durum

    def oku(self, g: np.ndarray) -> OcrSonuc:
        ocr, glob, img, akis = self._modul
        bas = time.time()
        rgba = np.dstack([g, g, g, np.full_like(g, 255)]) if g.ndim == 2 else g
        h, w = rgba.shape[:2]

        async def calistir():
            yazici = akis.DataWriter()
            yazici.write_bytes(list(rgba.tobytes()))
            bitmap = img.SoftwareBitmap.create_copy_from_buffer(
                yazici.detach_buffer(), img.BitmapPixelFormat.RGBA8, w, h, img.BitmapAlphaMode.PREMULTIPLIED)
            motor = ocr.OcrEngine.try_create_from_language(glob.Language(self.dil))
            return await motor.recognize_async(bitmap)

        sonuc = asyncio.run(calistir())
        kelimeler = []
        for satir in sonuc.lines:
            for k in satir.words:
                r = k.bounding_rect
                kelimeler.append(OcrKelime(k.text, int(r.x), int(r.y), int(r.width), int(r.height), 0.9))
        return OcrSonuc(kelimeler, self.ad, w, h, time.time() - bas)


def motorlari_hazirla(sira: list[str], tesseract_yolu: str = "", rapid_model: str = "",
                      rapid_sozluk: str = "") -> list[OcrMotoru]:
    """Ayarlardaki sıraya göre kullanılabilir motorları döndürür."""
    adaylar = {
        "windows": lambda: WindowsOcrMotoru(),
        "tesseract": lambda: TesseractMotoru(tesseract_yolu),
        "rapidocr": lambda: RapidOcrMotoru(rapid_model, rapid_sozluk),
    }
    motorlar = []
    for ad in sira:
        if ad in adaylar:
            m = adaylar[ad]()
            if m.kullanilabilir():
                motorlar.append(m)
    return motorlar
