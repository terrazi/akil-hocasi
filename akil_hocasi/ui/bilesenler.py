"""Ortak arayüz bileşenleri."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QKeyEvent
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QSizePolicy, QWidget)

from .tema import R


def golge(w: QWidget, bulaniklik: int = 28, y: int = 6, alfa: int = 28) -> None:
    efekt = QGraphicsDropShadowEffect(w)
    efekt.setBlurRadius(bulaniklik)
    efekt.setOffset(0, y)
    efekt.setColor(QColor(40, 40, 90, alfa))
    w.setGraphicsEffect(efekt)


class Cip(QLabel):
    """Renkli küçük etiket."""

    def __init__(self, metin: str, renk: str, zemin: str | None = None, parent=None):
        super().__init__(metin, parent)
        zemin = zemin or _alfali(renk, 0.12)
        self.setStyleSheet(f"background:{zemin}; color:{renk}; border-radius:9px; padding:3px 9px;"
                           f"font-size:11.5px; font-weight:700;")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)


def _alfali(hex_renk: str, alfa: float) -> str:
    c = QColor(hex_renk)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alfa})"


class Ayrac(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background:{R['cizgi']}; border:none;")


class SegmentSecici(QFrame):
    """İki/üç seçenekli yuvarlak anahtar (ör. Hızlı | Derin)."""
    degisti = Signal(str)

    def __init__(self, secenekler: list[tuple[str, str]], varsayilan: str, parent=None):
        super().__init__(parent)
        self.setObjectName("SegmentKap")
        yer = QHBoxLayout(self)
        yer.setContentsMargins(3, 3, 3, 3)
        yer.setSpacing(2)
        self.dugmeler: dict[str, QPushButton] = {}
        for anahtar, etiket in secenekler:
            d = QPushButton(etiket)
            d.setObjectName("Segment")
            d.setCheckable(True)
            d.setCursor(Qt.PointingHandCursor)
            d.clicked.connect(lambda _=False, a=anahtar: self.sec(a))
            yer.addWidget(d)
            self.dugmeler[anahtar] = d
        self.secili = varsayilan
        self.sec(varsayilan, sessiz=True)

    def sec(self, anahtar: str, sessiz: bool = False) -> None:
        self.secili = anahtar
        for a, d in self.dugmeler.items():
            d.setChecked(a == anahtar)
        if not sessiz:
            self.degisti.emit(anahtar)


class OtomatikMetin(QPlainTextEdit):
    """Yazdıkça büyüyen giriş kutusu. Enter gönderir, Shift+Enter yeni satır.
    Panoya kopyalanmış görüntü yapıştırılırsa goruntu_yapistirildi yayılır."""
    gonder = Signal()
    goruntu_yapistirildi = Signal(QImage)

    def __init__(self, parent=None, en_az: int = 26, en_cok: int = 180):
        super().__init__(parent)
        self.en_az, self.en_cok = en_az, en_cok
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().contentsChanged.connect(self._boyutla)
        self._boyutla()

    def _boyutla(self) -> None:
        h = int(self.document().size().height() * self.fontMetrics().lineSpacing()) + 14
        self.setFixedHeight(max(self.en_az + 14, min(self.en_cok, h)))

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            self.gonder.emit()
            return
        super().keyPressEvent(e)

    def canInsertFromMimeData(self, kaynak) -> bool:
        return kaynak.hasImage() or super().canInsertFromMimeData(kaynak)

    def insertFromMimeData(self, kaynak) -> None:
        if kaynak.hasImage():
            img = kaynak.imageData()
            if isinstance(img, QImage) and not img.isNull():
                self.goruntu_yapistirildi.emit(img)
                return
        super().insertFromMimeData(kaynak)


def ikon_dugme(ikon, ipucu: str, ad: str = "Hayalet", boyut: int = 20) -> QPushButton:
    d = QPushButton()
    d.setObjectName(ad)
    d.setIcon(ikon)
    d.setIconSize(QSize(boyut, boyut))
    d.setToolTip(ipucu)
    d.setCursor(Qt.PointingHandCursor)
    return d


def qimage_to_numpy(img: QImage) -> np.ndarray:
    """QImage → BGR numpy dizisi (OCR için)."""
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    dizi = np.frombuffer(ptr, np.uint8, count=img.sizeInBytes()).reshape(h, img.bytesPerLine() // 4, 4)[:, :w]
    return dizi[:, :, [2, 1, 0]].copy()


def numpy_to_qimage(dizi: np.ndarray) -> QImage:
    if dizi.ndim == 2:
        h, w = dizi.shape
        return QImage(dizi.data, w, h, w, QImage.Format_Grayscale8).copy()
    h, w = dizi.shape[:2]
    rgb = np.ascontiguousarray(dizi[:, :, [2, 1, 0]])
    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
