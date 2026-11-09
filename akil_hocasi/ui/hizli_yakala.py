"""Hızlı Yakala: ekran bölgesi seçme ve canlı metin penceresi (Google Lens / telefon benzeri).

Akış: kısayol / düğme / Ctrl+V → (bölge seç) → OCR → görüntü üzerinde seçilebilir metin.
Sürükleyerek seç, çift tık kelime, üçlü tık satır, Ctrl+A tümü, Ctrl+C kopyala.
"""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QGuiApplication, QImage, QKeySequence, QPainter, QPen,
                           QPixmap, QShortcut)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..core.algilama import algila
from ..core.maskeleme import metni_maskele
from ..ocr.sonuc import OcrKelime, OcrSonuc
from .bilesenler import Cip, qimage_to_numpy
from .calisanlar import OcrCalisani
from .ikonlar import ikon, logo_pixmap
from .tema import R


# ====================================================================== bölge seçme katmanı

class YakalamaKatmani(QWidget):
    """Tüm ekranları donduran, fareyle alan seçtiren tam ekran katman."""
    secildi = Signal(QImage)
    iptal = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.ekranlar = []          # (mantıksal geometri, fiziksel QPixmap, dpr)
        sanal = QRect()
        for ekran in QGuiApplication.screens():
            g = ekran.geometry()
            pm = ekran.grabWindow(0)
            self.ekranlar.append((g, pm, ekran.devicePixelRatio()))
            sanal = sanal.united(g)
        self.sanal = sanal
        self.setGeometry(sanal)
        self.bas: QPoint | None = None
        self.son: QPoint | None = None

    def _secim(self) -> QRect:
        if self.bas is None or self.son is None:
            return QRect()
        return QRect(self.bas, self.son).normalized()

    def paintEvent(self, _):
        p = QPainter(self)
        for g, pm, _dpr in self.ekranlar:
            p.drawPixmap(g.translated(-self.sanal.topLeft()), pm)
        p.fillRect(self.rect(), QColor(18, 16, 48, 135))
        secim = self._secim()
        if not secim.isNull():
            for g, pm, dpr in self.ekranlar:
                yerel = g.translated(-self.sanal.topLeft())
                kes = secim.intersected(yerel)
                if kes.isEmpty():
                    continue
                kaynak = QRectF((kes.x() - yerel.x()) * dpr, (kes.y() - yerel.y()) * dpr,
                                kes.width() * dpr, kes.height() * dpr)
                p.drawPixmap(QRectF(kes), pm, kaynak)
            p.setPen(QPen(QColor(R["camgobegi"]), 2))
            p.drawRect(secim.adjusted(0, 0, -1, -1))
            etiket = f"{secim.width()} × {secim.height()}"
            p.setFont(QFont("Segoe UI", 9, QFont.Bold))
            kutu = QRect(secim.left(), max(0, secim.top() - 26), 90, 22)
            p.fillRect(kutu, QColor(R["ana"]))
            p.setPen(Qt.white)
            p.drawText(kutu, Qt.AlignCenter, etiket)
        # Bilgi şeridi
        birincil = QGuiApplication.primaryScreen().geometry().translated(-self.sanal.topLeft())
        serit = QRect(birincil.center().x() - 300, birincil.top() + 24, 600, 40)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(30, 33, 64, 230))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(serit, 20, 20)
        p.setPen(Qt.white)
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(serit, Qt.AlignCenter, "Metnini almak istediğiniz alanı seçin   ·   Boşluk: tüm ekran   ·   Esc: iptal")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.bas = self.son = e.position().toPoint()
            self.update()
        elif e.button() == Qt.RightButton:
            self._iptal()

    def mouseMoveEvent(self, e):
        if self.bas is not None:
            self.son = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self.bas is None:
            return
        secim = self._secim()
        if secim.width() < 8 or secim.height() < 8:
            self.bas = self.son = None
            self.update()
            return
        self._bitir(secim)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._iptal()
        elif e.key() == Qt.Key_Space:
            imlec = self.mapFromGlobal(QCursor.pos())
            for g, _pm, _dpr in self.ekranlar:
                yerel = g.translated(-self.sanal.topLeft())
                if yerel.contains(imlec):
                    self._bitir(yerel)
                    return

    def _bitir(self, secim: QRect) -> None:
        merkez = secim.center()
        for g, pm, dpr in self.ekranlar:
            yerel = g.translated(-self.sanal.topLeft())
            if yerel.contains(merkez):
                kes = secim.intersected(yerel)
                fiziksel = QRect(int((kes.x() - yerel.x()) * dpr), int((kes.y() - yerel.y()) * dpr),
                                 int(kes.width() * dpr), int(kes.height() * dpr))
                img = pm.copy(fiziksel).toImage()
                self.hide()
                self.secildi.emit(img)
                self.close()
                return
        self._iptal()

    def _iptal(self) -> None:
        self.iptal.emit()
        self.close()


# ====================================================================== canlı metin tuvali

class GoruntuTuvali(QWidget):
    secim_degisti = Signal()
    bolge_secildi = Signal(QRect)       # görüntü koordinatlarında

    def __init__(self, img: QImage, parent=None):
        super().__init__(parent)
        self.img = img
        self.pm = QPixmap.fromImage(img)
        self.yakinlik = 1.0
        self.kelimeler: list[OcrKelime] = []
        self.secili: set[int] = set()
        self.uzerinde: int | None = None
        self.okunuyor = False
        self._mod = ""
        self._capa: int | None = None
        self._bolge_bas: QPoint | None = None
        self._bolge: QRect | None = None
        self._cift_zaman = 0.0
        self.setMouseTracking(True)
        self.setCursor(Qt.IBeamCursor)
        self._boyutla()

    # ---- veri
    def sonucu_yukle(self, sonuc: OcrSonuc) -> None:
        self.kelimeler = [k for satir in sonuc.satirlara_ayir() for k in satir]
        self.secili.clear()
        self.okunuyor = False
        self.update()

    def yakinlastir(self, kat: float) -> None:
        self.yakinlik = float(np.clip(kat, 0.25, 6.0))
        self._boyutla()
        self.update()

    def _boyutla(self) -> None:
        self.setFixedSize(QSize(int(self.img.width() * self.yakinlik), int(self.img.height() * self.yakinlik)))

    def _goruntu_noktasi(self, p: QPoint) -> tuple[float, float]:
        return p.x() / self.yakinlik, p.y() / self.yakinlik

    def _kelime_kutusu(self, k: OcrKelime) -> QRectF:
        z = self.yakinlik
        return QRectF(k.x * z - 2, k.y * z - 2, k.w * z + 4, k.h * z + 4)

    def kelime_bul(self, p: QPoint) -> int | None:
        for i, k in enumerate(self.kelimeler):
            if self._kelime_kutusu(k).contains(p):
                return i
        return None

    def _en_yakin(self, p: QPoint) -> int | None:
        if not self.kelimeler:
            return None
        x, y = self._goruntu_noktasi(p)
        return min(range(len(self.kelimeler)),
                   key=lambda i: abs(self.kelimeler[i].merkez_y - y) * 3 + abs(self.kelimeler[i].x + self.kelimeler[i].w / 2 - x))

    # ---- metin
    def secili_metin(self) -> str:
        if not self.secili:
            return ""
        sirali = sorted(self.secili)
        satirlar, son_satir = [], None
        for i in sirali:
            k = self.kelimeler[i]
            if son_satir is None or k.satir != son_satir:
                satirlar.append([])
                son_satir = k.satir
            satirlar[-1].append(k.metin)
        return "\n".join(" ".join(s) for s in satirlar)

    def tumunu_sec(self) -> None:
        self.secili = set(range(len(self.kelimeler)))
        self.update()
        self.secim_degisti.emit()

    # ---- çizim
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(self.rect(), self.pm)
        p.setRenderHint(QPainter.Antialiasing)
        for i, k in enumerate(self.kelimeler):
            kutu = self._kelime_kutusu(k)
            if i in self.secili:
                p.fillRect(kutu, QColor(79, 70, 229, 90))
            elif i == self.uzerinde:
                p.fillRect(kutu, QColor(79, 70, 229, 35))
            if k.supheli:
                p.setPen(QPen(QColor(R["sari"]), 2, Qt.DotLine))
                p.drawLine(kutu.bottomLeft(), kutu.bottomRight())
        if self._bolge is not None:
            p.setPen(QPen(QColor(R["camgobegi"]), 2, Qt.DashLine))
            p.setBrush(QColor(34, 211, 238, 30))
            z = self.yakinlik
            p.drawRect(QRectF(self._bolge.x() * z, self._bolge.y() * z, self._bolge.width() * z, self._bolge.height() * z))
        if self.okunuyor:
            p.fillRect(self.rect(), QColor(255, 255, 255, 150))
            p.setPen(QColor(R["ana"]))
            p.setFont(QFont("Segoe UI", 12, QFont.Bold))
            p.drawText(self.rect(), Qt.AlignCenter, "Okunuyor…")

    # ---- fare
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position().toPoint()
        i = self.kelime_bul(pos)
        if i is not None and time.time() - self._cift_zaman < QGuiApplication.styleHints().mouseDoubleClickInterval() / 1000:
            satir = self.kelimeler[i].satir      # üçlü tık: satır
            self.secili = {j for j, k in enumerate(self.kelimeler) if k.satir == satir}
            self._mod = ""
            self.update()
            self.secim_degisti.emit()
            return
        self._bolge = None
        if i is not None:
            self._mod, self._capa = "metin", i
            self.secili = {i}
        else:
            self._mod = "bolge"
            self._bolge_bas = pos
            self.secili.clear()
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if not (e.buttons() & Qt.LeftButton):
            i = self.kelime_bul(pos)
            if i != self.uzerinde:
                self.uzerinde = i
                self.update()
            return
        if self._mod == "metin" and self._capa is not None:
            j = self.kelime_bul(pos)
            j = self._en_yakin(pos) if j is None else j
            if j is not None:
                a, b = sorted((self._capa, j))
                self.secili = set(range(a, b + 1))
                self.update()
        elif self._mod == "bolge" and self._bolge_bas is not None:
            x0, y0 = self._goruntu_noktasi(self._bolge_bas)
            x1, y1 = self._goruntu_noktasi(pos)
            self._bolge = QRect(QPoint(int(x0), int(y0)), QPoint(int(x1), int(y1))).normalized()
            self.secili = {i for i, k in enumerate(self.kelimeler)
                           if self._bolge.intersects(QRect(k.x, k.y, k.w, k.h))}
            self.update()

    def mouseReleaseEvent(self, e):
        if self._mod == "bolge" and self._bolge is not None and self._bolge.width() > 6 and self._bolge.height() > 6:
            self.bolge_secildi.emit(QRect(self._bolge))
        self._mod = ""
        self.secim_degisti.emit()

    def mouseDoubleClickEvent(self, e):
        i = self.kelime_bul(e.position().toPoint())
        if i is not None:
            self.secili = {i}
            self._cift_zaman = time.time()
            self.update()
            self.secim_degisti.emit()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.yakinlastir(self.yakinlik * (1.15 if e.angleDelta().y() > 0 else 1 / 1.15))
            e.accept()
        else:
            super().wheelEvent(e)


# ====================================================================== canlı metin penceresi

class CanliMetinPenceresi(QWidget):
    sor = Signal(str)
    yaziya = Signal(str)
    duzeltildi = Signal(str, str)        # (yanlış okunan, doğru) — öğrenme motoruna gider

    def __init__(self, img: QImage, ocr_hatti, maske_varsayilan: bool = True, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Hızlı Yakala — Akıl Hocası")
        self.setWindowIcon(ikon("yakala", R["ana"], 32))
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("Icerik")
        self.img = img
        self.dizi = qimage_to_numpy(img)
        self.ocr = ocr_hatti
        self.maske = maske_varsayilan
        self.sonuc: OcrSonuc | None = None
        self.bolge: QRect | None = None
        self.calisan: OcrCalisani | None = None

        ana = QVBoxLayout(self)
        ana.setContentsMargins(16, 14, 16, 14)
        ana.setSpacing(12)

        # ---- araç çubuğu
        arac = QHBoxLayout()
        arac.setSpacing(6)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(28))
        arac.addWidget(logo)
        baslik = QLabel("Hızlı Yakala")
        baslik.setStyleSheet("font-size:17px; font-weight:700;")
        arac.addWidget(baslik)
        arac.addSpacing(12)
        self.d_kopyala = self._dugme(arac, "kopyala", "Kopyala", self.kopyala, "Ctrl+C")
        self._dugme(arac, "tablo", "Tablo olarak kopyala", self.tablo_kopyala)
        self.d_yeniden = self._dugme(arac, "yenile", "Yeniden oku", self.yeniden_oku)
        arac.addSpacing(8)
        self._dugme(arac, "kucult", "", lambda: self.yakinlik(1 / 1.25))
        self.yakinlik_etiketi = QLabel("100%")
        self.yakinlik_etiketi.setObjectName("Soluk")
        arac.addWidget(self.yakinlik_etiketi)
        self._dugme(arac, "buyut", "", lambda: self.yakinlik(1.25))
        arac.addStretch(1)
        sor = QPushButton("  Akıl Hocası'na sor")
        sor.setObjectName("Birincil")
        sor.setIcon(ikon("danisma", "#FFFFFF", 16))
        sor.clicked.connect(lambda: self.sor.emit(self._metin(secili_oncelik=True)))
        arac.addWidget(sor)
        yazi = QPushButton("  Yazı Hazırlama'ya gönder")
        yazi.setIcon(ikon("yazi", R["metin"], 16))
        yazi.clicked.connect(lambda: self.yaziya.emit(self._metin(secili_oncelik=False)))
        arac.addWidget(yazi)
        ana.addLayout(arac)

        # ---- gövde: tuval + yan panel
        govde = QHBoxLayout()
        govde.setSpacing(14)
        tuval_kart = QFrame()
        tuval_kart.setObjectName("Kart")
        tk = QVBoxLayout(tuval_kart)
        tk.setContentsMargins(8, 8, 8, 8)
        self.kaydirma = QScrollArea()
        self.kaydirma.setAlignment(Qt.AlignCenter)
        self.tuval = GoruntuTuvali(img)
        self.tuval.secim_degisti.connect(self._secim_degisti)
        self.tuval.bolge_secildi.connect(self._bolge_secildi)
        self.kaydirma.setWidget(self.tuval)
        tk.addWidget(self.kaydirma)
        govde.addWidget(tuval_kart, 1)

        yan = QFrame()
        yan.setObjectName("Kart")
        yan.setFixedWidth(330)
        yl = QVBoxLayout(yan)
        yl.setContentsMargins(14, 14, 14, 14)
        yl.setSpacing(10)
        b1 = QLabel("ALGILANANLAR")
        b1.setObjectName("BolumBaslik")
        yl.addWidget(b1)
        self.algilananlar = QVBoxLayout()
        self.algilananlar.setSpacing(6)
        yl.addLayout(self.algilananlar)
        b2 = QLabel("EMİN OLUNAMAYAN KELİMELER")
        b2.setObjectName("BolumBaslik")
        yl.addWidget(b2)
        self.supheliler = QVBoxLayout()
        self.supheliler.setSpacing(4)
        yl.addLayout(self.supheliler)
        b3 = QLabel("OKUNAN METİN (düzeltebilirsiniz)")
        b3.setObjectName("BolumBaslik")
        yl.addWidget(b3)
        self.metin_kutusu = QPlainTextEdit()
        self.metin_kutusu.setObjectName("Duz")
        yl.addWidget(self.metin_kutusu, 1)
        self.durum = QLabel("Okunuyor…")
        self.durum.setObjectName("Soluk")
        self.durum.setWordWrap(True)
        yl.addWidget(self.durum)
        govde.addWidget(yan)
        ana.addLayout(govde, 1)

        QShortcut(QKeySequence(QKeySequence.SelectAll), self, activated=self.tuval.tumunu_sec)
        QShortcut(QKeySequence(QKeySequence.Copy), self, activated=self.kopyala)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.close)
        QShortcut(QKeySequence(QKeySequence.ZoomIn), self, activated=lambda: self.yakinlik(1.25))
        QShortcut(QKeySequence(QKeySequence.ZoomOut), self, activated=lambda: self.yakinlik(1 / 1.25))

        ekran = QGuiApplication.primaryScreen().availableGeometry()
        w = min(ekran.width() - 80, max(980, img.width() + 420))
        h = min(ekran.height() - 80, max(620, img.height() + 140))
        self.resize(w, h)
        # Küçük ekran görüntülerini okunaklı büyüt
        if img.width() < 500:
            self.tuval.yakinlastir(min(2.0, 700 / max(1, img.width())))
            self.yakinlik_etiketi.setText(f"{int(self.tuval.yakinlik * 100)}%")
        QTimer.singleShot(50, self.oku)

    def _dugme(self, yer, ikon_ad: str, metin: str, fn, kisayol: str = "") -> QPushButton:
        d = QPushButton(("  " + metin) if metin else "")
        d.setObjectName("Hayalet")
        d.setIcon(ikon(ikon_ad, R["metin2"], 18))
        d.setCursor(Qt.PointingHandCursor)
        if kisayol:
            d.setToolTip(f"{metin} ({kisayol})")
        d.clicked.connect(fn)
        yer.addWidget(d)
        return d

    # ---- OCR
    def oku(self, coklu: bool = False) -> None:
        if not self.ocr.hazir:
            self.durum.setText("Kurulu OCR motoru bulunamadı. Ayarlar > OCR bölümündeki adımları izleyin.")
            return
        self.tuval.okunuyor = True
        self.tuval.update()
        bolge = None
        onceki = None
        if self.bolge is not None and self.sonuc is not None:
            b = self.bolge
            bolge, onceki = (b.x(), b.y(), b.width(), b.height()), self.sonuc
        self.calisan = OcrCalisani(self.ocr, self.dizi, 1, bolge, onceki, coklu, self)
        self.calisan.bitti.connect(self._okundu)
        self.calisan.hata.connect(self._ocr_hatasi)
        self.calisan.start()

    def _ocr_hatasi(self, mesaj: str) -> None:
        self.tuval.okunuyor = False
        self.tuval.update()
        self.durum.setText("OCR hatası: " + mesaj[-200:])

    def yeniden_oku(self) -> None:
        self.oku(coklu=True)

    def _okundu(self, sonuc: OcrSonuc) -> None:
        self.sonuc = sonuc
        self.bolge = None
        self.tuval.sonucu_yukle(sonuc)
        self.metin_kutusu.setPlainText(sonuc.metin())
        supheli = sum(1 for k in sonuc.kelimeler if k.supheli)
        self.durum.setText(f"{sonuc.motor} · {len(sonuc.kelimeler)} kelime · {sonuc.sure_sn:.1f} sn · "
                           f"ortalama güven %{sonuc.ortalama_guven() * 100:.0f}"
                           + (f" · {supheli} şüpheli kelime" if supheli else ""))
        self._algilananlari_goster(sonuc.metin())
        self._suphelileri_goster(sonuc)

    def _algilananlari_goster(self, metin: str) -> None:
        _temizle(self.algilananlar)
        bulgular = algila(metin)
        if not bulgular:
            bos = QLabel("TC no, IBAN, tarih, E-sayı veya tutar bulunmadı.")
            bos.setObjectName("Soluk")
            bos.setWordWrap(True)
            self.algilananlar.addWidget(bos)
            return
        for b in bulgular[:12]:
            satir = QFrame()
            satir.setStyleSheet(f"background:{R['yuzey2']}; border-radius:10px;")
            s = QHBoxLayout(satir)
            s.setContentsMargins(10, 6, 6, 6)
            renk = R["yesil"] if b.gecerli else R["kirmizi"]
            s.addWidget(Cip(b.etiket, renk))
            deger = QLabel(b.maskeli() if self.maske else b.metin)
            deger.setToolTip(b.not_ or "Doğrulandı")
            deger.setStyleSheet("font-family: Consolas, 'DejaVu Sans Mono'; font-size:12px; background:transparent;")
            s.addWidget(deger, 1)
            kop = QPushButton()
            kop.setObjectName("Hayalet")
            kop.setIcon(ikon("kopyala", R["metin2"], 15))
            kop.setToolTip("Kopyala" + (" (maskeli)" if b.tur in ("tc", "iban") and self.maske else ""))
            kop.clicked.connect(lambda _=False, x=b: QGuiApplication.clipboard().setText(x.kopya_degeri(self.maske)))
            s.addWidget(kop)
            if b.tur in ("tc", "iban"):
                acik = QPushButton("Açık")
                acik.setObjectName("Hayalet")
                acik.setToolTip("Maskesiz kopyala (kişisel veri: dikkatli kullanın)")
                acik.clicked.connect(lambda _=False, x=b: QGuiApplication.clipboard().setText(x.kopya_degeri(False)))
                s.addWidget(acik)
            self.algilananlar.addWidget(satir)
            if not b.gecerli and b.not_:
                n = QLabel("⚠ " + b.not_)
                n.setWordWrap(True)
                n.setStyleSheet(f"color:{R['kirmizi']}; font-size:11.5px;")
                self.algilananlar.addWidget(n)

    def _suphelileri_goster(self, sonuc: OcrSonuc) -> None:
        _temizle(self.supheliler)
        supheli = [k for k in sonuc.kelimeler if k.supheli or k.oneri][:10]
        if not supheli:
            ok = QLabel("Tüm kelimeler yüksek güvenle okundu.")
            ok.setObjectName("Soluk")
            self.supheliler.addWidget(ok)
            return
        for k in supheli:
            secenekler = [o for o in ([k.oneri] if k.oneri else []) + k.alternatifler if o and o != k.metin]
            satir = QHBoxLayout()
            etiket = QLabel(f"<b>{k.metin}</b>")
            satir.addWidget(etiket)
            for o in secenekler[:3]:
                d = QPushButton(o)
                d.setObjectName("Hayalet")
                d.setToolTip("Bu okumayı uygula")
                d.clicked.connect(lambda _=False, kel=k, yeni=o: self._duzelt(kel, yeni))
                satir.addWidget(d)
            satir.addStretch(1)
            kap = QWidget()
            kap.setLayout(satir)
            self.supheliler.addWidget(kap)

    def _duzelt(self, kelime: OcrKelime, yeni: str) -> None:
        self.duzeltildi.emit(kelime.metin, yeni)
        kelime.metin, kelime.alternatifler, kelime.oneri, kelime.guven = yeni, [], "", 1.0
        if self.sonuc:
            self.metin_kutusu.setPlainText(self.sonuc.metin())
            self._suphelileri_goster(self.sonuc)
            self._algilananlari_goster(self.sonuc.metin())
        self.tuval.update()

    # ---- seçim ve kopyalama
    def _secim_degisti(self) -> None:
        n = len(self.tuval.secili)
        self.d_kopyala.setText(f"  Kopyala ({n} kelime)" if n else "  Kopyala")

    def _bolge_secildi(self, r: QRect) -> None:
        self.bolge = r
        self.d_yeniden.setText("  Bölgeyi yeniden oku")

    def _metin(self, secili_oncelik: bool = True) -> str:
        secili = self.tuval.secili_metin() if secili_oncelik else ""
        return secili or self.metin_kutusu.toPlainText()

    def kopyala(self) -> None:
        metin = self._metin(True)
        QGuiApplication.clipboard().setText(metni_maskele(metin) if self.maske else metin)
        self.durum.setText("Panoya kopyalandı" + (" (TC/IBAN maskeli)" if self.maske else ""))

    def tablo_kopyala(self) -> None:
        if self.sonuc:
            metin = self.sonuc.tablo_metni()
            QGuiApplication.clipboard().setText(metni_maskele(metin) if self.maske else metin)
            self.durum.setText("Tablo olarak kopyalandı; Excel'e yapıştırabilirsiniz")

    def yakinlik(self, kat: float) -> None:
        self.tuval.yakinlastir(self.tuval.yakinlik * kat)
        self.yakinlik_etiketi.setText(f"{int(self.tuval.yakinlik * 100)}%")


def _temizle(yer) -> None:
    while yer.count():
        oge = yer.takeAt(0)
        if oge.widget():
            oge.widget().deleteLater()
        elif oge.layout():
            _temizle(oge.layout())
