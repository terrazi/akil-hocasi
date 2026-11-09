"""Sağ panel: cevabın dayandığı kaynaklar, alıntılanan madde vurgulu."""

from __future__ import annotations

import html
import re

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..answer.modeller import Cevap, Kaynak
from ..core.turkce import katla
from .bilesenler import Cip
from .ikonlar import ikon
from .tema import KAYNAK_TURU_RENK, R


def _vurgula(metin: str, soru: str, sinir: int = 900) -> str:
    kisa = metin if len(metin) <= sinir else metin[:sinir].rsplit(" ", 1)[0] + " …"
    terimler = {t for t in re.findall(r"[a-z0-9]+", katla(soru)) if len(t) >= 4}
    parcalar = []
    for kelime in re.split(r"(\s+)", kisa):
        k = katla(kelime)
        esc = html.escape(kelime)
        if any(t[:5] in k for t in terimler) and kelime.strip():
            parcalar.append(f"<span style='background:#FDE68A; border-radius:3px;'>{esc}</span>")
        else:
            parcalar.append(esc)
    return "".join(parcalar).replace("\n", "<br>")


class KaynakKarti(QFrame):
    def __init__(self, k: Kaynak, soru: str, parent=None):
        super().__init__(parent)
        self.kid = k.kid
        self.setObjectName("KaynakKarti")
        yer = QVBoxLayout(self)
        yer.setContentsMargins(14, 12, 14, 12)
        yer.setSpacing(6)
        ust = QHBoxLayout()
        no = QLabel(k.kid.lstrip("K"))
        no.setFixedSize(24, 24)
        no.setAlignment(Qt.AlignCenter)
        no.setStyleSheet(f"background:{R['ana']}; color:white; border-radius:12px; font-weight:700; font-size:12px;")
        ust.addWidget(no)
        ust.addWidget(Cip(k.pasaj.kaynak_turu, KAYNAK_TURU_RENK.get(k.pasaj.kaynak_turu, R["ana"])))
        if not k.pasaj.yururlukte:
            ust.addWidget(Cip("Eski sürüm", R["sari"], R["sari_zemin"]))
        ust.addStretch(1)
        yer.addLayout(ust)
        baslik = QLabel(f"<b>{html.escape(k.etiket)}</b>" +
                        (f"<br><span style='color:{R['metin2']};'>{html.escape(k.pasaj.baslik)}</span>"
                         if k.pasaj.baslik else ""))
        baslik.setWordWrap(True)
        yer.addWidget(baslik)
        metin = QLabel(_vurgula(k.pasaj.metin, soru))
        metin.setWordWrap(True)
        metin.setTextFormat(Qt.RichText)
        metin.setTextInteractionFlags(Qt.TextSelectableByMouse)
        metin.setStyleSheet(f"font-size:12.5px; color:{R['metin2']};")
        yer.addWidget(metin)
        alt = QHBoxLayout()
        if k.pasaj.rv:
            alt.addWidget(QLabel(f"RV {k.pasaj.rv}"))
        alt.addStretch(1)
        if k.pasaj.kaynak_url:
            git = QPushButton("Kaynağa git")
            git.setObjectName("Hayalet")
            git.setIcon(ikon("dis", R["ana"], 15))
            git.setCursor(Qt.PointingHandCursor)
            git.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(k.pasaj.kaynak_url)))
            alt.addWidget(git)
        yer.addLayout(alt)

    def vurgula(self, acik: bool) -> None:
        self.setProperty("vurgulu", "true" if acik else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class KaynakPaneli(QFrame):
    kapat_istendi = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(360)
        self.setObjectName("KaynakPaneliKap")
        self.setStyleSheet(f"#KaynakPaneliKap {{ background:{R['yuzey2']}; border-left:1px solid {R['cizgi']}; }}")
        yer = QVBoxLayout(self)
        yer.setContentsMargins(16, 16, 12, 12)
        yer.setSpacing(10)
        ust = QHBoxLayout()
        self.baslik = QLabel("Kaynaklar")
        self.baslik.setStyleSheet("font-size:16px; font-weight:700;")
        ust.addWidget(self.baslik)
        ust.addStretch(1)
        kapat = QPushButton()
        kapat.setObjectName("Hayalet")
        kapat.setIcon(ikon("carpi", R["metin2"], 16))
        kapat.setToolTip("Paneli gizle")
        kapat.clicked.connect(self.kapat_istendi.emit)
        ust.addWidget(kapat)
        yer.addLayout(ust)
        self.kaydirma = QScrollArea()
        self.kaydirma.setWidgetResizable(True)
        self.icerik = QWidget()
        self.liste = QVBoxLayout(self.icerik)
        self.liste.setContentsMargins(0, 0, 4, 0)
        self.liste.setSpacing(10)
        self.liste.addStretch(1)
        self.kaydirma.setWidget(self.icerik)
        yer.addWidget(self.kaydirma, 1)
        self.kartlar: dict[str, KaynakKarti] = {}
        self._bos_goster()

    def _temizle(self) -> None:
        while self.liste.count() > 1:
            w = self.liste.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.kartlar.clear()

    def _bos_goster(self) -> None:
        self._temizle()
        bos = QLabel("Bir cevaptaki [1], [2] atıflarına tıkladığınızda dayandığı madde burada vurgulu açılır.")
        bos.setWordWrap(True)
        bos.setObjectName("Soluk")
        self.liste.insertWidget(0, bos)

    def goster(self, cevap: Cevap, secili: str = "") -> None:
        self._temizle()
        self.baslik.setText(f"Kaynaklar ({len(cevap.kaynaklar)})")
        if not cevap.kaynaklar:
            self._bos_goster()
            return
        for i, k in enumerate(cevap.kaynaklar):
            kart = KaynakKarti(k, cevap.soru)
            self.kartlar[k.kid] = kart
            self.liste.insertWidget(i, kart)
        if secili:
            self.sec(secili)

    def sec(self, kid: str) -> None:
        for k, kart in self.kartlar.items():
            kart.vurgula(k == kid)
        if kid in self.kartlar:
            self.kaydirma.ensureWidgetVisible(self.kartlar[kid], 0, 20)
