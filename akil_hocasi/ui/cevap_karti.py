"""Cevap kartı: durum rozeti, kısa cevap (atıflı), adımlar, belgeler, dikkat, dayanak, eylemler."""

from __future__ import annotations

import html
from datetime import datetime

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..answer.modeller import Cevap, Cumle, Durum
from .bilesenler import Ayrac, Cip, golge
from .ikonlar import ikon
from .tema import DURUM_RENK, KAYNAK_TURU_RENK, R

DURUM_IKON = {Durum.DOGRULANDI: "onay", Durum.CELISKILI: "uyari", Durum.HUKUM_YOK: "bilgi"}


def _tarih(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return iso or "—"


def _atif_html(c: Cumle) -> str:
    parcalar = []
    for kid in c.kaynaklar:
        no = kid.lstrip("K")
        parcalar.append(
            f"<a href='kaynak:{kid}' style='text-decoration:none; color:{R['ana']}; font-weight:700;"
            f" font-size:11px;'>&nbsp;[{no}]</a>")
    return "".join(parcalar)


def _cumle_html(c: Cumle) -> str:
    metin = html.escape(c.metin)
    if c.tur == "alinti":
        metin = f"<span style='color:{R['metin2']}; font-style:italic;'>{metin}</span>"
    return metin + _atif_html(c)


class _Bolum(QWidget):
    def __init__(self, baslik: str, icerik_html: str, renk: str | None = None, zemin: str | None = None,
                 link_fn=None, parent=None):
        super().__init__(parent)
        yer = QVBoxLayout(self)
        yer.setContentsMargins(0, 0, 0, 0)
        yer.setSpacing(6)
        if baslik:
            b = QLabel(baslik.upper())
            b.setObjectName("BolumBaslik")
            if renk:
                b.setStyleSheet(f"color:{renk};")
            yer.addWidget(b)
        etiket = QLabel(icerik_html)
        etiket.setWordWrap(True)
        etiket.setTextFormat(Qt.RichText)
        etiket.setTextInteractionFlags(Qt.TextBrowserInteraction)
        etiket.setOpenExternalLinks(False)
        if link_fn:
            etiket.linkActivated.connect(link_fn)
        stil = "font-size:14px;"
        if zemin:
            stil += f"background:{zemin}; border-radius:12px; padding:10px 12px;"
        etiket.setStyleSheet(stil)
        yer.addWidget(etiket)


class CevapKarti(QFrame):
    kaynak_secildi = Signal(str)
    belge_acildi = Signal(object)
    yaziya_donustur = Signal(object)
    geri_bildirim = Signal(object)
    faydali = Signal(object)

    def __init__(self, cevap: Cevap, parent=None):
        super().__init__(parent)
        self.cevap = cevap
        self.setObjectName("CevapKarti")
        golge(self, 30, 6, 22)
        yer = QVBoxLayout(self)
        yer.setContentsMargins(22, 18, 22, 16)
        yer.setSpacing(14)

        # ---- başlık satırı
        ust = QHBoxLayout()
        ust.setSpacing(8)
        renk, zemin = DURUM_RENK[cevap.durum.value]
        rozet = QPushButton(cevap.durum.value)
        rozet.setIcon(ikon(DURUM_IKON[cevap.durum], renk, 16, 2.2))
        rozet.setStyleSheet(f"background:{zemin}; color:{renk}; border:none; border-radius:10px;"
                            f"padding:5px 12px; font-weight:700;")
        rozet.setToolTip({
            Durum.DOGRULANDI: "Tüm doğrulama testlerini geçti",
            Durum.CELISKILI: "Kaynaklar arasında çelişki veya dayanak uyarısı var",
            Durum.HUKUM_YOK: "Konuyu doğrudan düzenleyen hüküm bulunamadı; en yakın bilgiler ve çözüm yolu verildi",
        }[cevap.durum])
        ust.addWidget(rozet)
        for tur in dict.fromkeys(k.pasaj.kaynak_turu for k in cevap.kaynaklar):
            ust.addWidget(Cip(tur, KAYNAK_TURU_RENK.get(tur, R["ana"])))
        ust.addStretch(1)
        mod = "Derin araştırma" if cevap.mod == "derin" else "Hızlı cevap"
        bilgi = QLabel(f"{mod} · {cevap.sure_sn:.1f} sn" + (f" · Son kontrol {_tarih(cevap.son_kontrol)}"
                                                           if cevap.son_kontrol else ""))
        bilgi.setObjectName("Soluk")
        ust.addWidget(bilgi)
        yer.addLayout(ust)
        if cevap.cevrimdisi:
            uy = QLabel("Çevrimdışı: cevap yerel kütüphaneden; son kontrol tarihine dikkat ediniz.")
            uy.setStyleSheet(f"background:{R['sari_zemin']}; color:{R['sari']}; border-radius:10px; padding:7px 10px;"
                             "font-weight:600;")
            yer.addWidget(uy)

        # ---- kısa cevap
        if cevap.kisa_cevap:
            yer.addWidget(_Bolum("Kısa cevap", "<br>".join(_cumle_html(c) for c in cevap.kisa_cevap),
                                 link_fn=self._link))
        if cevap.acik_nokta:
            yer.addWidget(_Bolum("Açık kalan nokta", html.escape(cevap.acik_nokta), R["gri"], R["gri_zemin"]))

        # ---- adımlar
        if cevap.adimlar:
            maddeler = "".join(f"<li style='margin-bottom:4px;'>{_cumle_html(c)}</li>" for c in cevap.adimlar)
            yer.addWidget(_Bolum("Adımlar", f"<ol style='margin-left:-18px;'>{maddeler}</ol>", link_fn=self._link))

        # ---- belgeler
        if cevap.belgeler:
            b = QLabel("BELGELER VE FORMLAR")
            b.setObjectName("BolumBaslik")
            yer.addWidget(b)
            satir = QHBoxLayout()
            satir.setSpacing(8)
            for ref in cevap.belgeler[:6]:
                d = QPushButton(f"  {ref.kod}" + (f" · {ref.ad}" if ref.ad and ref.ad != ref.kod else ""))
                d.setObjectName("BelgeCipi")
                d.setIcon(ikon("dosya", R["tasinir"], 16))
                d.setCursor(Qt.PointingHandCursor)
                d.setToolTip("Depodaki kopyasını aç" if ref.dosya_yolu else "Depoda henüz yok; kaynağı açar")
                d.clicked.connect(lambda _=False, r=ref: self.belge_acildi.emit(r))
                satir.addWidget(d)
            satir.addStretch(1)
            yer.addLayout(satir)

        # ---- dikkat ve önerilen yol
        if cevap.dikkat:
            baslik = "En yakın hükümler" if cevap.durum == Durum.HUKUM_YOK else "Dikkat"
            yer.addWidget(_Bolum(baslik, "<br>".join("• " + _cumle_html(c) for c in cevap.dikkat),
                                 R["sari"], R["sari_zemin"], link_fn=self._link))
        if cevap.somut_yol:
            yer.addWidget(_Bolum("Önerilen yol", "<br>".join("→ " + html.escape(c.metin) for c in cevap.somut_yol),
                                 R["ana"], R["ana_acik"]))

        # ---- dayanak
        if cevap.kaynaklar:
            yer.addWidget(Ayrac())
            satirlar = []
            for k in cevap.kaynaklar:
                url = k.pasaj.kaynak_url
                git = (f" &nbsp;<a href='url:{html.escape(url)}' style='color:{R['ana']}; text-decoration:none;'>"
                       f"Kaynağa git ↗</a>") if url else ""
                eski = "" if k.pasaj.yururlukte else f" <span style='color:{R['sari']};'>(eski sürüm)</span>"
                satirlar.append(
                    f"<a href='kaynak:{k.kid}' style='color:{R['metin']}; text-decoration:none;'>"
                    f"<b style='color:{R['ana']};'>[{k.kid.lstrip('K')}]</b> {html.escape(k.etiket)}</a>{eski}{git}")
            yer.addWidget(_Bolum("Dayanak", "<br>".join(satirlar), link_fn=self._link))

        # ---- ayrıntılar (doğrulama günlüğü)
        self.ayrinti = QLabel(self._ayrinti_html())
        self.ayrinti.setWordWrap(True)
        self.ayrinti.setTextFormat(Qt.RichText)
        self.ayrinti.setStyleSheet(f"background:{R['yuzey2']}; border-radius:10px; padding:10px; font-size:12px;"
                                   f"color:{R['metin2']};")
        self.ayrinti.setVisible(False)
        yer.addWidget(self.ayrinti)

        # ---- eylemler
        alt = QHBoxLayout()
        alt.setSpacing(4)
        for ad, metin, fn in (
            ("kopyala", "Kopyala", self._kopyala),
            ("yazi", "Yazıya dönüştür", lambda: self.yaziya_donustur.emit(self.cevap)),
            ("panel", "Kaynakları göster", lambda: self.kaynak_secildi.emit(
                self.cevap.kaynaklar[0].kid if self.cevap.kaynaklar else "")),
            ("bilgi", "Doğrulama ayrıntıları", lambda: self.ayrinti.setVisible(not self.ayrinti.isVisible())),
        ):
            d = QPushButton(metin)
            d.setObjectName("Hayalet")
            d.setIcon(ikon(ad, R["metin2"], 16))
            d.setCursor(Qt.PointingHandCursor)
            d.clicked.connect(fn)
            alt.addWidget(d)
        alt.addStretch(1)
        self.faydali_dugme = QPushButton("Faydalı")
        self.faydali_dugme.setObjectName("Hayalet")
        self.faydali_dugme.setIcon(ikon("onay", R["yesil"], 16))
        self.faydali_dugme.setCursor(Qt.PointingHandCursor)
        self.faydali_dugme.setToolTip("Doğru ve işe yaradı: program bu cevaptan öğrenir")
        self.faydali_dugme.clicked.connect(self._faydali)
        self.faydali_dugme.setVisible(cevap.durum == Durum.DOGRULANDI)
        alt.addWidget(self.faydali_dugme)
        bayrak = QPushButton("Yanlış / eksik bildir")
        bayrak.setObjectName("Hayalet")
        bayrak.setIcon(ikon("bayrak", R["kirmizi"], 16))
        bayrak.setCursor(Qt.PointingHandCursor)
        bayrak.clicked.connect(lambda: self.geri_bildirim.emit(self.cevap))
        alt.addWidget(bayrak)
        yer.addLayout(alt)

    def _ayrinti_html(self) -> str:
        satirlar = ["<b>Araştırma adımları</b>"] + [html.escape(s) for s in self.cevap.ilerleme]
        if self.cevap.uyarilar:
            satirlar.append("<br><b>Doğrulama motoru notları</b>")
            for u in self.cevap.uyarilar:
                renk = {"hata": R["kirmizi"], "uyari": R["sari"]}.get(u.seviye, R["metin2"])
                satirlar.append(f"<span style='color:{renk};'>● {html.escape(u.test)}:</span> {html.escape(u.mesaj)}")
        satirlar.append("<br>" + ("Dil modeli kullanıldı; tüm cümleler kural tabanlı testlerden geçti."
                                  if self.cevap.model_kullanildi else
                                  "Alıntıya dayalı mod: cümleler doğrudan kaynak metinden alındı."))
        return "<br>".join(satirlar)

    def _link(self, href: str) -> None:
        if href.startswith("kaynak:"):
            self.kaynak_secildi.emit(href.split(":", 1)[1])
        elif href.startswith("url:"):
            QDesktopServices.openUrl(QUrl(href[4:]))

    def _faydali(self) -> None:
        self.faydali_dugme.setEnabled(False)
        self.faydali_dugme.setText("Teşekkürler, öğrenildi")
        self.faydali.emit(self.cevap)

    def _kopyala(self) -> None:
        QGuiApplication.clipboard().setText(self.cevap.duz_metin())
