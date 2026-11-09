"""Diğer sayfalar: Belge Deposu, Neler Değişti, Ayarlar, Yazı Hazırlama ve yakında gelecek modüller."""

from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTime, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QTimeEdit,
                               QVBoxLayout, QWidget)

from .bilesenler import Cip, SegmentSecici
from .ikonlar import ikon
from .tema import R

TUR_RENK = {"pdf": R["kirmizi"], "docx": R["ana"], "docm": R["ana"], "doc": R["ana"], "odt": R["ana"],
            "xlsx": R["tasinir"], "xlsm": R["tasinir"], "xls": R["tasinir"], "ods": R["tasinir"]}


def _baslik(yer, metin: str, alt: str = "") -> None:
    b = QLabel(metin)
    b.setObjectName("SayfaBaslik")
    yer.addWidget(b)
    if alt:
        a = QLabel(alt)
        a.setObjectName("Ikincil")
        a.setWordWrap(True)
        yer.addWidget(a)


def _tarih(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return iso or ""


def klasorde_goster(yol: str) -> None:
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(yol)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(yol).parent)))


# ====================================================================== Belge Deposu

class BelgeDeposuSayfasi(QWidget):
    guncelle_istendi = Signal()

    def __init__(self, depo, parent=None):
        super().__init__(parent)
        self.depo = depo
        yer = QVBoxLayout(self)
        yer.setContentsMargins(32, 26, 32, 22)
        yer.setSpacing(12)
        _baslik(yer, "Belge Deposu", "Resmî sitelerden indirilen form, tablo ve örneklerin orijinal dosyaları. "
                                     "Açtığınız her dosya bir kopyadır; depodaki orijinal değişmez.")
        arac = QHBoxLayout()
        self.ara = QLineEdit()
        self.ara.setPlaceholderText("Kod, ad veya birim ile ara… (ör. FRM.396, izin, harcırah)")
        self.ara.textChanged.connect(self.yenile)
        arac.addWidget(self.ara, 1)
        self.tur = SegmentSecici([("", "Tümü"), ("doc", "Word"), ("xls", "Excel"), ("pdf", "PDF")], "")
        self.tur.degisti.connect(lambda _: self.yenile())
        arac.addWidget(self.tur)
        self.eski = QCheckBox("Eski sürümleri göster")
        self.eski.toggled.connect(self.yenile)
        arac.addWidget(self.eski)
        yer.addLayout(arac)

        self.tablo = QTableWidget(0, 7)
        self.tablo.setHorizontalHeaderLabels(["Kod", "Ad", "Tür", "Birim", "RV", "İndirme", "Durum"])
        self.tablo.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tablo.verticalHeader().setVisible(False)
        self.tablo.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tablo.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tablo.setAlternatingRowColors(True)
        self.tablo.setShowGrid(False)
        self.tablo.doubleClicked.connect(lambda _: self.ac())
        yer.addWidget(self.tablo, 1)

        self.bos = QLabel("Depo henüz boş. İlk güncellemeden sonra TOGÜ formları, yönergeler ve örnekler burada listelenir.")
        self.bos.setObjectName("Ikincil")
        self.bos.setAlignment(Qt.AlignCenter)
        yer.addWidget(self.bos)

        alt = QHBoxLayout()
        for ad, metin, fn in (("dosya", "Aç", self.ac), ("indir", "Kopyasını kaydet", self.kopya_kaydet),
                              ("klasor", "Klasörde göster", self.klasor), ("dis", "Kaynağa git", self.kaynak)):
            d = QPushButton("  " + metin)
            d.setIcon(ikon(ad, R["metin2"], 16))
            d.clicked.connect(fn)
            alt.addWidget(d)
        alt.addStretch(1)
        g = QPushButton("  Şimdi güncelle")
        g.setObjectName("Birincil")
        g.setIcon(ikon("yenile", "#FFFFFF", 16))
        g.clicked.connect(self.guncelle_istendi.emit)
        alt.addWidget(g)
        yer.addLayout(alt)
        self.kayitlar: list[dict] = []
        self.yenile()

    def yenile(self, *_):
        self.kayitlar = self.depo.ara(self.ara.text(), self.tur.secili, sadece_guncel=not self.eski.isChecked())
        self.tablo.setRowCount(len(self.kayitlar))
        for i, k in enumerate(self.kayitlar):
            degerler = [k["kod"] or "—", k["ad"], k["tur"].upper(), k["birim"], k["rv"], _tarih(k["indirme_tarihi"]),
                        {"guncel": "Güncel", "eski": "Eski sürüm", "kaldirildi": "Kaynaktan kaldırıldı"}.get(k["durum"], k["durum"])]
            for j, v in enumerate(degerler):
                self.tablo.setItem(i, j, QTableWidgetItem("" if j == 2 else str(v)))
            self.tablo.setCellWidget(i, 2, Cip(k["tur"].upper() + (" ⚠" if k["makrolu"] else ""),
                                              TUR_RENK.get(k["tur"], R["soluk"])))
        self.bos.setVisible(not self.kayitlar)
        self.tablo.setVisible(bool(self.kayitlar))

    def _secili(self) -> dict | None:
        satir = self.tablo.currentRow()
        return self.kayitlar[satir] if 0 <= satir < len(self.kayitlar) else None

    def ac(self):
        k = self._secili()
        if k:
            hedef = self.depo.kopya_ver(k, Path(tempfile.gettempdir()) / "AkilHocasi")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(hedef)))

    def kopya_kaydet(self):
        k = self._secili()
        if k:
            klasor = QFileDialog.getExistingDirectory(self, "Kopyanın kaydedileceği klasör")
            if klasor:
                hedef = self.depo.kopya_ver(k, klasor)
                klasorde_goster(str(hedef))

    def klasor(self):
        k = self._secili()
        if k:
            klasorde_goster(k["dosya_yolu"])

    def kaynak(self):
        k = self._secili()
        if k and k["url"]:
            QDesktopServices.openUrl(QUrl(k["url"]))


# ====================================================================== Neler Değişti

class NelerDegistiSayfasi(QWidget):
    soru_tekrar = Signal(str)
    ogren_istendi = Signal()

    def __init__(self, kutuphane, ogrenme=None, siralayici=None, parent=None):
        super().__init__(parent)
        self.kutuphane = kutuphane
        self.ogrenme = ogrenme
        self.siralayici = siralayici
        yer = QVBoxLayout(self)
        yer.setContentsMargins(32, 26, 32, 22)
        yer.setSpacing(12)
        _baslik(yer, "Neler Değişti", "Programın öğrendikleri, son 7 günde eklenen ve değişen belgeler, "
                                      "incelemeye düşen işlem kartları ve takipteki sorular.")
        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        self.icerik = QWidget()
        self.liste = QVBoxLayout(self.icerik)
        self.liste.setSpacing(8)
        kaydirma.setWidget(self.icerik)
        yer.addWidget(kaydirma, 1)
        self.yenile()

    def yenile(self):
        while self.liste.count():
            w = self.liste.takeAt(0).widget()
            if w:
                w.deleteLater()
        if self.ogrenme is not None:
            self.liste.addWidget(self._ogrenme_karti())
        takip = self.kutuphane.takipteki_sorular()
        if takip:
            b = QLabel(f"TAKİPTEKİ SORULAR ({len(takip)})")
            b.setObjectName("BolumBaslik")
            self.liste.addWidget(b)
            for t in takip:
                kart = QFrame()
                kart.setObjectName("Kart")
                k = QHBoxLayout(kart)
                k.setContentsMargins(14, 10, 10, 10)
                lbl = QLabel(f"<b>{html.escape(t['soru'])}</b><br><span style='color:{R['soluk']};'>"
                             f"Takipte: {_tarih(t['eklenme'])} · son arama {_tarih(t['son_arama']) or '—'}</span>")
                lbl.setWordWrap(True)
                k.addWidget(lbl, 1)
                d = QPushButton("Yeniden sor")
                d.clicked.connect(lambda _=False, s=t["soru"]: self.soru_tekrar.emit(s))
                k.addWidget(d)
                self.liste.addWidget(kart)
        b = QLabel("SON DEĞİŞİKLİKLER")
        b.setObjectName("BolumBaslik")
        self.liste.addWidget(b)
        degisiklikler = self.kutuphane.son_degisiklikler(7)
        if not degisiklikler:
            bos = QLabel("Son 7 günde değişiklik yok. Program her saat başı resmî kaynakları kontrol eder.")
            bos.setObjectName("Ikincil")
            self.liste.addWidget(bos)
        renkler = {"yeni": ("Yeni", R["yesil"]), "guncellendi": ("Güncellendi", R["ana"]),
                   "inceleme": ("İnceleme bekliyor", R["sari"]), "kaldirildi": ("Kaldırıldı", R["kirmizi"])}
        for d in degisiklikler:
            etiket, renk = renkler.get(d["tur"], (d["tur"], R["soluk"]))
            kart = QFrame()
            kart.setObjectName("Kart")
            k = QHBoxLayout(kart)
            k.setContentsMargins(14, 10, 10, 10)
            k.addWidget(Cip(etiket, renk))
            lbl = QLabel(f"{html.escape(d['ozet'])}<br><span style='color:{R['soluk']};'>{_tarih(d['zaman'])}</span>")
            lbl.setWordWrap(True)
            k.addWidget(lbl, 1)
            if d["kaynak_url"]:
                git = QPushButton()
                git.setObjectName("Hayalet")
                git.setIcon(ikon("dis", R["ana"], 16))
                git.setToolTip("Kaynağa git")
                git.clicked.connect(lambda _=False, u=d["kaynak_url"]: QDesktopServices.openUrl(QUrl(u)))
                k.addWidget(git)
            self.liste.addWidget(kart)
        self.liste.addStretch(1)


    def _ogrenme_karti(self) -> QWidget:
        d = self.ogrenme.durum()
        kart = QFrame()
        kart.setObjectName("Kart")
        k = QVBoxLayout(kart)
        k.setContentsMargins(18, 14, 18, 14)
        k.setSpacing(8)
        ust = QHBoxLayout()
        b = QLabel("Öğrenme durumu")
        b.setStyleSheet("font-size:16px; font-weight:700;")
        ust.addWidget(b)
        ust.addWidget(Cip("Kendi kendine gelişir", R["harcirah"]))
        ust.addStretch(1)
        simdi = QPushButton("  Şimdi öğren")
        simdi.setObjectName("Birincil")
        simdi.setIcon(ikon("yenile", "#FFFFFF", 16))
        simdi.setToolTip("Öz değerlendirme, sıralayıcı eğitimi ve paylaşım (normalde her gece kendiliğinden)")
        simdi.clicked.connect(self.ogren_istendi.emit)
        ust.addWidget(simdi)
        k.addLayout(ust)
        son = d["son_degerlendirme"]
        altin = (f"%{son['gecen'] * 100 // max(1, son['toplam'])} ({son['gecen']}/{son['toplam']}), kritik {son['kritik']}"
                 if son else "henüz ölçülmedi")
        sir = "yok"
        if self.siralayici is not None:
            g = self.siralayici.gecmis(1)
            sir = (f"v{self.siralayici.surum} etkin" if self.siralayici.aktif else "eğitiliyor (henüz etkin değil)") + \
                  (f" · son eğitim MRR {g[0]['mrr']:.2f} / taban {g[0]['taban_mrr']:.2f}" if g else "")
        izgara = QGridLayout()
        izgara.setHorizontalSpacing(24)
        for i, (ad, deger) in enumerate((
                ("Cevaplanan soru", d["olay"]), ("Faydalı işaretlenen", d["faydali"]),
                ("Öğrenilen terim karşılığı", d["es_anlam"]), ("Öğrenilen OCR düzeltmesi", d["ocr"]),
                ("Örnek hafıza", d["ornek"]), ("Paylaşan bilgisayar", d["paylasan_makine"]),
                ("Altın soru seti", f"{d['altin']} soru · {altin}"), ("Öğrenen sıralayıcı", sir))):
            lbl = QLabel(f"<span style='color:{R['metin2']};'>{ad}</span><br><b>{deger}</b>")
            izgara.addWidget(lbl, i // 4, i % 4)
        k.addLayout(izgara)
        bosluk = self.ogrenme.bilgi_bosluklari(adet=6)
        if bosluk:
            lbl = QLabel("<b>Bilgi boşlukları</b> (cevap bulunamayan konular; tarayıcı ve birim uzmanları için): " +
                         ", ".join(f"{html.escape(x['terim'])} ({x['sayi']})" for x in bosluk))
            lbl.setWordWrap(True)
            k.addWidget(lbl)
        alt = QHBoxLayout()
        for metin, fn in (("Öğrenme paketini dışa aktar", self._paket_disa), ("Paket içe aktar", self._paket_ice),
                          ("Eğitim verisini dışa aktar", self._egitim_disa), ("Altın soru setini yükle", self._altin_yukle)):
            dg = QPushButton(metin)
            dg.clicked.connect(fn)
            alt.addWidget(dg)
        alt.addStretch(1)
        k.addLayout(alt)
        return kart

    def _paket_disa(self) -> None:
        from ..ogrenme.paket import paket_olustur
        yol, _ = QFileDialog.getSaveFileName(self, "Öğrenme paketi", "AkilHocasi-ogrenme.ahp", "Öğrenme paketi (*.ahp)")
        if yol:
            paket_olustur(self.ogrenme, yol)

    def _paket_ice(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from ..ogrenme.paket import paket_ice_aktar
        yol, _ = QFileDialog.getOpenFileName(self, "Öğrenme paketi", "", "Öğrenme paketi (*.ahp)")
        if yol:
            try:
                sonuc = paket_ice_aktar(self.ogrenme, yol)
                QMessageBox.information(self, "Akıl Hocası", f"Paket alındı: {sonuc}")
            except Exception as e:
                QMessageBox.warning(self, "Akıl Hocası", f"Paket alınamadı: {e}")
            self.yenile()

    def _egitim_disa(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from ..ogrenme.egitim import egitim_verisi_disa_aktar
        yol, _ = QFileDialog.getSaveFileName(self, "Eğitim verisi", "egitim.jsonl", "JSON Lines (*.jsonl)")
        if yol:
            n = egitim_verisi_disa_aktar(self.ogrenme, yol)
            QMessageBox.information(self, "Akıl Hocası",
                                    f"{n} doğrulanmış örnek yazıldı. TC/IBAN maskelidir; paylaşmadan önce dosyayı "
                                    "kişi adı gibi bilgiler için gözden geçirin.")

    def _altin_yukle(self) -> None:
        import json as _json

        from PySide6.QtWidgets import QMessageBox
        yol, _ = QFileDialog.getOpenFileName(self, "Altın soru seti (JSON)", "", "JSON (*.json)")
        if yol:
            try:
                n = self.ogrenme.altin_set_yukle(_json.loads(Path(yol).read_text("utf-8")))
                QMessageBox.information(self, "Akıl Hocası", f"{n} soru yüklendi; her gece başarı ölçülecek.")
            except Exception as e:
                QMessageBox.warning(self, "Akıl Hocası", f"Dosya okunamadı: {e}")
            self.yenile()


# ====================================================================== Yazı Hazırlama (Faz 3)

class YaziHazirlamaSayfasi(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        yer = QVBoxLayout(self)
        yer.setContentsMargins(32, 26, 32, 22)
        yer.setSpacing(12)
        _baslik(yer, "Yazı Hazırlama", "Gelen yazıya cevap veya yeni yazı taslağı: 2020 Resmî Yazışma Yönetmeliği "
                                       "ve birim şablonu. Sayı, tarih ve imzayı enVision EBYS verir.")
        yer.addWidget(Cip("Faz 3'te tamamlanacak", R["yazisma"]))
        b = QLabel("GELEN METİN")
        b.setObjectName("BolumBaslik")
        yer.addWidget(b)
        self.metin = QPlainTextEdit()
        self.metin.setObjectName("Duz")
        self.metin.setPlaceholderText("Hızlı Yakala'dan veya bir cevaptan gönderilen metin burada görünür. "
                                      "Faz 3'te bu metinden birim adına TASLAK yazı hazırlanacak.")
        yer.addWidget(self.metin, 1)

    def metin_al(self, metin: str) -> None:
        self.metin.setPlainText(metin)


class YakindaSayfasi(QWidget):
    def __init__(self, baslik: str, aciklama: str, faz: str, maddeler: list[str], renk: str, parent=None):
        super().__init__(parent)
        yer = QVBoxLayout(self)
        yer.setContentsMargins(32, 26, 32, 22)
        yer.setSpacing(12)
        _baslik(yer, baslik, aciklama)
        yer.addWidget(Cip(faz, renk))
        kart = QFrame()
        kart.setObjectName("Kart")
        k = QVBoxLayout(kart)
        k.setContentsMargins(20, 16, 20, 16)
        for m in maddeler:
            lbl = QLabel(f"<span style='color:{renk};'>●</span>&nbsp;&nbsp;{html.escape(m)}")
            k.addWidget(lbl)
        yer.addWidget(kart)
        yer.addStretch(1)


# ====================================================================== Ayarlar

class AyarlarSayfasi(QWidget):
    kaydedildi = Signal()
    guncelle_istendi = Signal()
    aday_model_istendi = Signal(str)

    def __init__(self, ayarlar, yollar, durum_bilgisi: dict, parent=None):
        super().__init__(parent)
        self.ayarlar, self.yollar = ayarlar, yollar
        dis = QVBoxLayout(self)
        dis.setContentsMargins(0, 0, 0, 0)
        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        ic = QWidget()
        yer = QVBoxLayout(ic)
        yer.setContentsMargins(32, 26, 32, 22)
        yer.setSpacing(14)
        _baslik(yer, "Ayarlar")
        izgara = QGridLayout()
        izgara.setSpacing(14)

        # Profil
        k, f = self._kart("Profil")
        self.ad = QLineEdit(ayarlar.al("profil.ad", ""))
        self.rol = QComboBox()
        self.rol.addItems(["Genel", "Personel işleri", "Mutemet / tahakkuk", "Ön mali kontrol / muhasebe",
                           "Satın alma", "Taşınır kayıt", "Yazı işleri / sekreterlik"])
        self.rol.setCurrentText(ayarlar.al("profil.rol", "Genel"))
        self.birim = QLineEdit(ayarlar.al("profil.birim", ""))
        f.addRow("Adınız", self.ad)
        f.addRow("Rolünüz", self.rol)
        f.addRow("Biriminiz", self.birim)
        izgara.addWidget(k, 0, 0)

        # Güncelleme
        k, f = self._kart("Güncelleme saatleri")
        self.g_acik = QCheckBox("Otomatik güncelleme açık")
        self.g_acik.setChecked(ayarlar.al("guncelleme.acik", True))
        self.aralik = QComboBox()
        for dk, ad in ((30, "30 dakikada bir"), (60, "Saat başı"), (180, "3 saatte bir")):
            self.aralik.addItem(ad, dk)
        self.aralik.setCurrentIndex(max(0, self.aralik.findData(ayarlar.al("guncelleme.aralik_dk", 60))))
        self.gece = QTimeEdit(QTime.fromString(ayarlar.al("guncelleme.gece_saati", "00:30"), "HH:mm"))
        self.gece.setDisplayFormat("HH:mm")
        self.sabah = QTimeEdit(QTime.fromString(ayarlar.al("guncelleme.sabah_saati", "08:30"), "HH:mm"))
        self.sabah.setDisplayFormat("HH:mm")
        self.olculu = QCheckBox("Ölçülü bağlantıda yalnızca hafif kontrol")
        self.olculu.setChecked(ayarlar.al("guncelleme.olculu_baglantida_hafif", True))
        f.addRow(self.g_acik)
        f.addRow("Hafif kontrol", self.aralik)
        f.addRow("Resmî Gazete tam tarama", self.gece)
        f.addRow("Günlük özet", self.sabah)
        f.addRow(self.olculu)
        simdi = QPushButton("  Şimdi güncelle")
        simdi.setIcon(ikon("yenile", R["metin"], 16))
        simdi.clicked.connect(self.guncelle_istendi.emit)
        f.addRow(simdi)
        izgara.addWidget(k, 0, 1)

        # Hızlı Yakala ve OCR
        k, f = self._kart("Hızlı Yakala ve OCR")
        self.kisayol = QLineEdit(ayarlar.al("kisayol.hizli_yakala", "Win+Shift+Y"))
        self.kisayol.setToolTip("Örnek: Win+Shift+Y, Ctrl+Alt+Shift+Y, Win+Shift+F9")
        self.pano = QCheckBox("Print Screen sonrası \"metni al?\" bildirimi göster")
        self.pano.setChecked(ayarlar.al("ocr.pano_izleme", True))
        self.tess = QLineEdit(ayarlar.al("ocr.tesseract_yolu", ""))
        self.tess.setPlaceholderText(r"C:\Program Files\Tesseract-OCR\tesseract.exe (isteğe bağlı)")
        f.addRow("Kısayol", self.kisayol)
        f.addRow(self.pano)
        f.addRow("Tesseract yolu", self.tess)
        motorlar = durum_bilgisi.get("ocr_motorlari", [])
        f.addRow("Etkin motorlar", QLabel(", ".join(motorlar) if motorlar else
                                          "<span style='color:#DC2626;'>Motor bulunamadı (README: OCR kurulumu)</span>"))
        izgara.addWidget(k, 1, 0)

        # Yapay zekâ modeli
        k, f = self._kart("Yapay zekâ modeli (yerel)")
        satir = QHBoxLayout()
        self.model = QLineEdit(ayarlar.al("llm.model_yolu", ""))
        self.model.setPlaceholderText("Model dosyası (.gguf) — boşsa alıntıya dayalı mod")
        satir.addWidget(self.model, 1)
        gozat = QPushButton("Gözat")
        gozat.clicked.connect(self._model_sec)
        satir.addWidget(gozat)
        kap = QWidget()
        kap.setLayout(satir)
        f.addRow("Model", kap)
        f.addRow("Durum", QLabel(durum_bilgisi.get("model", "—")))
        bulut = QCheckBox("Bulut model (maskeli metinle) — kurum izni gerekir")
        bulut.setChecked(False)
        bulut.setEnabled(False)
        f.addRow(bulut)
        izgara.addWidget(k, 1, 1)

        # Gizlilik
        k, f = self._kart("Gizlilik")
        self.maske = QCheckBox("TC kimlik no ve IBAN'ı maskeli kopyala")
        self.maske.setChecked(ayarlar.al("gizlilik.maske_varsayilan", True))
        self.gecmis = QSpinBox()
        self.gecmis.setRange(0, 365)
        self.gecmis.setSuffix(" gün")
        self.gecmis.setValue(ayarlar.al("gizlilik.gecmis_gun", 30))
        f.addRow(self.maske)
        f.addRow("Soru geçmişini sakla", self.gecmis)
        izgara.addWidget(k, 2, 0)

        # Öğrenme
        k, f = self._kart("Öğrenme ve kendini geliştirme")
        self.ogr_acik = QCheckBox("Kullanımdan öğren (terimler, kaynaklar, örnekler, OCR düzeltmeleri)")
        self.ogr_acik.setChecked(ayarlar.al("ogrenme.acik", True))
        f.addRow(self.ogr_acik)
        satir2 = QHBoxLayout()
        self.paylasim = QLineEdit(ayarlar.al("ogrenme.paylasim_klasoru", ""))
        self.paylasim.setPlaceholderText(r"\\sunucu\ortak\AkilHocasi (isteğe bağlı)")
        satir2.addWidget(self.paylasim, 1)
        pg = QPushButton("Gözat")
        pg.clicked.connect(lambda: self.paylasim.setText(QFileDialog.getExistingDirectory(self, "Paylaşım klasörü")
                                                         or self.paylasim.text()))
        satir2.addWidget(pg)
        kap2 = QWidget()
        kap2.setLayout(satir2)
        f.addRow("Paylaşım klasörü", kap2)
        self.egitim_komutu = QLineEdit(ayarlar.al("ogrenme.yerel_egitim_komutu", ""))
        self.egitim_komutu.setPlaceholderText("Yerel ek katman eğitim komutu: {veri} {temel_model} {cikti}")
        self.egitim_komutu.setToolTip("Boşsa dil modeli yerelde eğitilmez; sıralayıcı ve hafıza yine her gece öğrenir.")
        f.addRow("Yerel eğitim", self.egitim_komutu)
        aday = QPushButton("  Aday modeli dene ve karşılaştır")
        aday.setIcon(ikon("onay", R["metin"], 16))
        aday.setToolTip("Yeni bir .gguf modelini altın soru setinde mevcut modelle karşılaştırır; yalnızca daha "
                        "başarılıysa devreye alır")
        aday.clicked.connect(self._aday_sec)
        f.addRow(aday)
        izgara.addWidget(k, 2, 1)

        # Hakkında
        k, f = self._kart("Hakkında")
        from .. import __version__
        f.addRow("Sürüm", QLabel(__version__))
        f.addRow("Kütüphane", QLabel(durum_bilgisi.get("kutuphane", "—")))
        veri = QPushButton("Veri klasörünü aç")
        veri.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(yollar.kok))))
        f.addRow(veri)
        f.addRow(QLabel("Program kamu sistemlerine (KBS, MYS, HYS, EBYS, e-Devlet) bağlanmaz;\n"
                        "yalnızca resmî siteleri okur ve kaynak gösterir."))
        izgara.addWidget(k, 3, 0, 1, 2)
        yer.addLayout(izgara)

        alt = QHBoxLayout()
        alt.addStretch(1)
        kaydet = QPushButton("  Kaydet")
        kaydet.setObjectName("Birincil")
        kaydet.setIcon(ikon("onay", "#FFFFFF", 16))
        kaydet.clicked.connect(self.kaydet)
        alt.addWidget(kaydet)
        yer.addLayout(alt)
        yer.addStretch(1)
        kaydirma.setWidget(ic)
        dis.addWidget(kaydirma)

    def _kart(self, baslik: str):
        kart = QFrame()
        kart.setObjectName("AyarKart")
        yer = QVBoxLayout(kart)
        yer.setContentsMargins(18, 14, 18, 16)
        b = QLabel(baslik)
        b.setStyleSheet("font-size:15px; font-weight:700;")
        yer.addWidget(b)
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignLeft)
        f.setHorizontalSpacing(14)
        f.setVerticalSpacing(10)
        yer.addLayout(f)
        return kart, f

    def _model_sec(self):
        yol, _ = QFileDialog.getOpenFileName(self, "Model dosyası seç", str(self.yollar.modeller), "GGUF model (*.gguf)")
        if yol:
            self.model.setText(yol)

    def _aday_sec(self):
        yol, _ = QFileDialog.getOpenFileName(self, "Aday model (.gguf)", str(self.yollar.modeller), "GGUF model (*.gguf)")
        if yol:
            self.aday_model_istendi.emit(yol)

    def kaydet(self):
        a = self.ayarlar
        a.ayarla("ogrenme.acik", self.ogr_acik.isChecked())
        a.ayarla("ogrenme.paylasim_klasoru", self.paylasim.text().strip())
        a.ayarla("ogrenme.yerel_egitim_komutu", self.egitim_komutu.text().strip())
        a.ayarla("profil.ad", self.ad.text().strip())
        a.ayarla("profil.rol", self.rol.currentText())
        a.ayarla("profil.birim", self.birim.text().strip())
        a.ayarla("guncelleme.acik", self.g_acik.isChecked())
        a.ayarla("guncelleme.aralik_dk", self.aralik.currentData())
        a.ayarla("guncelleme.gece_saati", self.gece.time().toString("HH:mm"))
        a.ayarla("guncelleme.sabah_saati", self.sabah.time().toString("HH:mm"))
        a.ayarla("guncelleme.olculu_baglantida_hafif", self.olculu.isChecked())
        a.ayarla("kisayol.hizli_yakala", self.kisayol.text().strip() or "Win+Shift+Y")
        a.ayarla("ocr.pano_izleme", self.pano.isChecked())
        a.ayarla("ocr.tesseract_yolu", self.tess.text().strip())
        a.ayarla("llm.model_yolu", self.model.text().strip())
        a.ayarla("gizlilik.maske_varsayilan", self.maske.isChecked())
        a.ayarla("gizlilik.gecmis_gun", self.gecmis.value())
        a.kaydet()
        self.kaydedildi.emit()


class KaynakHavuzuSayfasi(QWidget):
    """Kaynak havuzunun tek yönetim ekranı: gömülü tarayıcı motoru, tarayıcı eklentisi ve gözlem günlüğü."""

    tara_istendi = Signal(str)
    durdur_istendi = Signal()
    ayarlar_degisti = Signal()

    KARAR = {"kabul": ("Eklendi", R["yesil"]), "ayni": ("Güncel", R["gri"]), "tekrar": ("Tekrar", R["gri"]),
             "liste": ("Dosya listesi", R["ana"]), "ipucu": ("İpucu", R["harcirah"]), "ret": ("Atlandı", R["sari"])}
    MOD = {"pasif": "Eklenti (gezinti)", "aktif": "Eklenti (tarama)", "motor": "Gömülü tarayıcı"}

    def __init__(self, s, parent=None):
        super().__init__(parent)
        self.s = s
        self.son_temas = 0.0
        dis = QVBoxLayout(self)
        dis.setContentsMargins(0, 0, 0, 0)
        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        ic = QWidget()
        yer = QVBoxLayout(ic)
        yer.setContentsMargins(32, 26, 32, 22)
        yer.setSpacing(14)
        _baslik(yer, "Kaynak Havuzu", "Program resmî siteleri kendi görünmez tarayıcısıyla arka planda tarar; gezdiğiniz "
                                      "resmî sayfalar da tarayıcı eklentisiyle eklenir. Her sayfa denetlenir, sürümlenir "
                                      "ve kaynağıyla birlikte kütüphaneye girer; resmî dosyalar Belge Deposu'na iner.")

        # --- özet sayıları
        sayilar = QHBoxLayout()
        sayilar.setSpacing(12)
        self.sayi: dict[str, QLabel] = {}
        for anahtar, etiket, renk in (("belge", "kütüphanedeki belge", R["ana"]), ("bugun", "bugün eklenen sayfa", R["yesil"]),
                                      ("dosya", "indirilmeyi bekleyen dosya", R["maas"]), ("ipucu", "ikincil site ipucu", R["harcirah"])):
            kart = QFrame()
            kart.setObjectName("Kart")
            k = QVBoxLayout(kart)
            k.setContentsMargins(16, 12, 16, 12)
            sayi = QLabel("0")
            sayi.setStyleSheet(f"font-size:24px; font-weight:700; color:{renk};")
            k.addWidget(sayi)
            e = QLabel(etiket)
            e.setObjectName("Ikincil")
            k.addWidget(e)
            self.sayi[anahtar] = sayi
            sayilar.addWidget(kart, 1)
        yer.addLayout(sayilar)

        izgara = QGridLayout()
        izgara.setSpacing(14)
        izgara.addWidget(self._motor_karti(), 0, 0)
        izgara.addWidget(self._eklenti_karti(), 0, 1)
        izgara.setColumnStretch(0, 3)
        izgara.setColumnStretch(1, 2)
        yer.addLayout(izgara)
        yer.addWidget(self._gunluk_karti())
        yer.addStretch(1)
        kaydirma.setWidget(ic)
        dis.addWidget(kaydirma)
        self.yenile()

    # ------------------------------------------------------------------ kartlar
    def _kart(self, baslik: str, alt: str = ""):
        kart = QFrame()
        kart.setObjectName("AyarKart")
        yer = QVBoxLayout(kart)
        yer.setContentsMargins(18, 14, 18, 16)
        yer.setSpacing(10)
        b = QLabel(baslik)
        b.setStyleSheet("font-size:15px; font-weight:700;")
        yer.addWidget(b)
        if alt:
            a = QLabel(alt)
            a.setWordWrap(True)
            a.setStyleSheet(f"color:{R['metin2']};")
            yer.addWidget(a)
        return kart, yer

    def _motor_karti(self) -> QWidget:
        from PySide6.QtWidgets import QProgressBar
        kart, yer = self._kart("Gömülü tarayıcı", "Bilgisayardaki Edge ya da Chrome görünmez çalışır; her tarama çerezsiz, "
                                                  "oturumsuz, geçici bir profille yapılır ve hiçbir düğmeye tıklanmaz. "
                                                  "Listedeki siteler haftada bir, bilgisayar boştayken kendiliğinden taranır.")
        self.motor_durum = QLabel()
        self.motor_durum.setWordWrap(True)
        yer.addWidget(self.motor_durum)
        self.ilerleme = QProgressBar()
        self.ilerleme.setRange(0, 100)
        self.ilerleme.setTextVisible(False)
        self.ilerleme.setFixedHeight(8)
        yer.addWidget(self.ilerleme)
        self.ilerleme_metni = QLabel()
        self.ilerleme_metni.setObjectName("Ikincil")
        self.ilerleme_metni.setWordWrap(True)
        yer.addWidget(self.ilerleme_metni)

        self.site_tablosu = QTableWidget(0, 3)
        self.site_tablosu.setHorizontalHeaderLabels(["Site", "Son tarama", "Sonuç"])
        self.site_tablosu.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.site_tablosu.verticalHeader().setVisible(False)
        self.site_tablosu.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.site_tablosu.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.site_tablosu.setShowGrid(False)
        self.site_tablosu.setAlternatingRowColors(True)
        self.site_tablosu.setMinimumHeight(190)
        yer.addWidget(self.site_tablosu)

        ekle = QHBoxLayout()
        self.yeni_site = QLineEdit()
        self.yeni_site.setPlaceholderText("https://birim.gop.edu.tr/ (yalnız beyaz listedeki resmî siteler)")
        self.yeni_site.returnPressed.connect(self._site_ekle)
        ekle.addWidget(self.yeni_site, 1)
        d = QPushButton("  Ekle")
        d.setIcon(ikon("arti", R["metin"], 16))
        d.clicked.connect(self._site_ekle)
        ekle.addWidget(d)
        yer.addLayout(ekle)

        dugmeler = QHBoxLayout()
        tumu = QPushButton("  Tümünü şimdi tara")
        tumu.setObjectName("Birincil")
        tumu.setIcon(ikon("yenile", "#FFFFFF", 16))
        tumu.clicked.connect(self._tumunu_tara)
        secili = QPushButton("Seçiliyi tara")
        secili.clicked.connect(self._secili_tara)
        kaldir = QPushButton("Kaldır")
        kaldir.clicked.connect(self._site_kaldir)
        self.durdur = QPushButton("  Durdur")
        self.durdur.setIcon(ikon("dur", R["kirmizi"], 16))
        self.durdur.setToolTip("Taramayı duraklatır; yeniden başlatınca kaldığı yerden sürer")
        self.durdur.clicked.connect(self.durdur_istendi.emit)
        for w in (tumu, secili, kaldir):
            dugmeler.addWidget(w)
        dugmeler.addStretch(1)
        dugmeler.addWidget(self.durdur)
        yer.addLayout(dugmeler)

        f = QFormLayout()
        f.setHorizontalSpacing(14)
        a = self.s.ayarlar
        self.hiz = QComboBox()
        for anahtar, metin in (("yavas", "Yavaş (~6 sn/sayfa, siteyi en az yorar)"), ("normal", "Normal (~3 sn/sayfa)"),
                               ("hizli", "Hızlı (~1,5 sn/sayfa)")):
            self.hiz.addItem(metin, anahtar)
        self.hiz.setCurrentIndex(max(0, ["yavas", "normal", "hizli"].index(a.al("gozlem.motor.hiz", "normal"))
                                     if a.al("gozlem.motor.hiz", "normal") in ("yavas", "normal", "hizli") else 1))
        self.en_cok = QSpinBox()
        self.en_cok.setRange(10, 5000)
        self.en_cok.setValue(int(a.al("gozlem.motor.en_cok_sayfa", 200)))
        self.derinlik = QSpinBox()
        self.derinlik.setRange(0, 10)
        self.derinlik.setValue(int(a.al("gozlem.motor.derinlik", 4)))
        self.tarayici_yolu = QLineEdit(a.al("gozlem.motor.tarayici_yolu", ""))
        self.tarayici_yolu.setPlaceholderText("Boş bırakın: Edge, yoksa Chrome kendiliğinden bulunur")
        f.addRow("Hız", self.hiz)
        f.addRow("Site başına en çok sayfa", self.en_cok)
        f.addRow("Bağlantı derinliği", self.derinlik)
        f.addRow("Tarayıcı yolu", self.tarayici_yolu)
        yer.addLayout(f)
        kaydet = QPushButton("  Tarama ayarlarını kaydet")
        kaydet.setIcon(ikon("onay", R["metin"], 16))
        kaydet.clicked.connect(self._ayarlari_kaydet)
        yer.addWidget(kaydet, 0, Qt.AlignLeft)
        return kart

    def _eklenti_karti(self) -> QWidget:
        kart, yer = self._kart("Tarayıcı eklentisi (isteğe bağlı)", "Gezdiğiniz resmî sayfaları da havuza ekler. Kurulum "
                                                                     "eklentiyi programla kendiliğinden eşleştirir; anahtar "
                                                                     "kopyalamanız gerekmez.")
        self.eklenti_durum = QLabel()
        self.eklenti_durum.setWordWrap(True)
        yer.addWidget(self.eklenti_durum)
        self.gozlem_acik = QCheckBox("Eklentiden gelen resmî sayfaları değerlendir")
        self.gozlem_acik.setChecked(self.s.ayarlar.al("gozlem.acik", True))
        self.gozlem_acik.toggled.connect(self._ayarlari_kaydet)
        yer.addWidget(self.gozlem_acik)
        satir = QHBoxLayout()
        klasor = QPushButton("  Eklenti klasörü")
        klasor.setIcon(ikon("klasor", R["metin"], 16))
        klasor.clicked.connect(self._eklenti_klasoru)
        nasil = QPushButton("Nasıl kurulur?")
        nasil.clicked.connect(self._kurulum_yonergesi)
        satir.addWidget(klasor)
        satir.addWidget(nasil)
        satir.addStretch(1)
        yer.addLayout(satir)

        b = QLabel("Elle eşleştirme (köprü kurulu değilse)")
        b.setObjectName("Ikincil")
        yer.addWidget(b)
        anahtar = QHBoxLayout()
        self.gozlem_anahtar = QLineEdit(self.s.ayarlar.al("gozlem.anahtar", ""))
        self.gozlem_anahtar.setReadOnly(True)
        self.gozlem_anahtar.setEchoMode(QLineEdit.Password)
        anahtar.addWidget(self.gozlem_anahtar, 1)
        kopyala = QPushButton("Kopyala")
        kopyala.clicked.connect(self._anahtari_kopyala)
        yenile = QPushButton("Yenile")
        yenile.setToolTip("Yeni anahtar üretir; eklenti köprüyle yenisini kendiliğinden alır")
        yenile.clicked.connect(self._anahtari_yenile)
        anahtar.addWidget(kopyala)
        anahtar.addWidget(yenile)
        yer.addLayout(anahtar)
        f = QFormLayout()
        self.gozlem_port = QSpinBox()
        self.gozlem_port.setRange(1024, 65535)
        self.gozlem_port.setValue(int(self.s.ayarlar.al("gozlem.port", 47231)))
        self.gozlem_port.setToolTip("Yalnız bu bilgisayar (127.0.0.1) üzerinden dinlenir")
        f.addRow("Yerel bağlantı noktası", self.gozlem_port)
        yer.addLayout(f)
        self.gozlem_bilgi = QLabel()
        self.gozlem_bilgi.setWordWrap(True)
        self.gozlem_bilgi.setObjectName("Ikincil")
        yer.addWidget(self.gozlem_bilgi)
        yer.addStretch(1)
        return kart

    def _gunluk_karti(self) -> QWidget:
        kart, yer = self._kart("Son gözlemler")
        self.gunluk_turu = SegmentSecici([("kayit", "Gözlem günlüğü"), ("ipucu", "İkincil site ipuçları")], "kayit")
        self.gunluk_turu.degisti.connect(lambda _: self.gunlugu_yenile())
        yer.addWidget(self.gunluk_turu, 0, Qt.AlignLeft)
        self.gunluk = QTableWidget(0, 5)
        self.gunluk.verticalHeader().setVisible(False)
        self.gunluk.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.gunluk.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.gunluk.setShowGrid(False)
        self.gunluk.setAlternatingRowColors(True)
        self.gunluk.setMinimumHeight(260)
        self.gunluk.doubleClicked.connect(self._gunluk_ac)
        yer.addWidget(self.gunluk)
        return kart

    # ------------------------------------------------------------------ yenileme
    def yenile(self) -> None:
        k = self.s.kutuphane
        ist = k.istatistik()
        g = self.s.gozlem.istatistik()
        self.sayi["belge"].setText(f"{ist['belge']:,}".replace(",", "."))
        self.sayi["bugun"].setText(str(g["bugun"].get("kabul", 0)))
        self.sayi["dosya"].setText(str(self.s.dosya_kuyrugu.bekleyen() if self.s.dosya_kuyrugu else 0))
        self.sayi["ipucu"].setText(str(g["ipucu"]))
        self.motor_durumu(self.s.motor.durum() if self.s.motor else {})
        self._siteleri_yenile()
        self._eklenti_durumunu_yenile()
        self.gunlugu_yenile()

    def motor_durumu(self, d: dict) -> None:
        motor = self.s.motor
        yol = motor.tarayici_yolu() if motor else ""
        if not yol:
            self.motor_durum.setText(f"<span style='color:{R['kirmizi']};'>Bilgisayarda Edge ya da Chrome bulunamadı.</span> "
                                     "Aşağıdan tarayıcı yolunu belirtebilirsiniz; eklenti yine çalışır.")
        else:
            ad = "Microsoft Edge" if "msedge" in yol.lower() or "edge" in yol.lower() else "Google Chrome"
            surum = d.get("tarayici") or ""
            self.motor_durum.setText(f"<b>Hazır</b> · {ad}" + (f" ({html.escape(surum)})" if surum else "")
                                     + (f"<br><span style='color:{R['kirmizi']};'>{html.escape(d['son_hata'])}</span>"
                                        if d.get("son_hata") else ""))
        e = d.get("etkin")
        sirada = d.get("sirada") or []
        if e and e.get("durum") == "calisiyor":
            sc = e.get("sayac", {})
            self.ilerleme.setValue(min(100, int(100 * e["sayfa"] / max(1, e["en_cok"]))))
            self.ilerleme_metni.setText(
                f"<b>{html.escape(e['kok'])}</b> taranıyor: {e['sayfa']}/{e['en_cok']} sayfa · sırada {e['kuyruk']} bağlantı · "
                f"eklenen {sc.get('kabul', 0)} · güncel {sc.get('ayni', 0) + sc.get('tekrar', 0)} · dosya {sc.get('dosya', 0)}"
                + (f" · {len(sirada)} site daha bekliyor" if sirada else ""))
            self.durdur.setEnabled(True)
        else:
            self.ilerleme.setValue(0)
            if e:
                sc = e.get("sayac", {})
                self.ilerleme_metni.setText(f"Son tarama: {html.escape(e['kok'])} · {e['sayfa']} sayfa, {sc.get('kabul', 0)} "
                                            f"yeni kaynak · {html.escape(e.get('neden', ''))}")
            else:
                self.ilerleme_metni.setText("Şu an tarama yok. Listedeki siteler boştayken kendiliğinden taranır.")
            self.durdur.setEnabled(bool(sirada))

    def _siteleri_yenile(self) -> None:
        siteler = list(self.s.ayarlar.al("gozlem.motor.siteler", []) or [])
        gecmis = {g["kok"]: g for g in (self.s.motor.gecmis(200) if self.s.motor else [])}
        self.site_tablosu.setRowCount(len(siteler))
        for i, site in enumerate(siteler):
            g = gecmis.get(site)
            son = _tarih(g["bitis"] or g["baslangic"]) if g else "—"
            if g and g["durum"] == "calisiyor":
                sonuc = "Taranıyor…"
            elif g:
                sc = g.get("sayac", {})
                sonuc = f"{g['sayfa']} sayfa · {sc.get('kabul', 0)} yeni" + (" · duraklatıldı" if g["durum"] == "duraklatildi" else "")
            else:
                sonuc = "Henüz taranmadı"
            for j, metin in enumerate((site, son, sonuc)):
                self.site_tablosu.setItem(i, j, QTableWidgetItem(metin))

    def _eklenti_durumunu_yenile(self) -> None:
        from ..gozlem.eslestirme import yerel_mesajlasma_durumu
        kayit = yerel_mesajlasma_durumu()
        parcalar = []
        if kayit:
            hazir = [t for t, v in kayit.items() if v and t != "Chromium"]
            parcalar.append("Köprü: " + (", ".join(hazir) + " için kayıtlı" if hazir else
                                         f"<span style='color:{R['sari']};'>kayıtlı değil (programı yeniden kurun)</span>"))
        if self.son_temas and time.time() - self.son_temas < 600:
            parcalar.append(f"<span style='color:{R['yesil']};'>Eklenti bağlı</span> · son temas "
                            f"{datetime.fromtimestamp(self.son_temas):%H:%M}")
        else:
            parcalar.append("Eklenti son 10 dakikada bağlanmadı (kurulu değilse \"Nasıl kurulur?\")")
        self.eklenti_durum.setText("<br>".join(parcalar))

    def gunlugu_yenile(self) -> None:
        db = self.s.kutuphane.db
        if self.gunluk_turu.secili == "ipucu":
            satirlar = db.execute("SELECT zaman, baslik, sorular, url FROM gozlem_ipucu ORDER BY zaman DESC LIMIT 200").fetchall()
            self.gunluk.setColumnCount(4)
            self.gunluk.setHorizontalHeaderLabels(["Zaman", "Başlık", "Soru ipuçları", "Adres"])
            self.gunluk.setRowCount(len(satirlar))
            for i, r in enumerate(satirlar):
                sorular = json.loads(r["sorular"] or "[]")
                for j, metin in enumerate((_tarih(r["zaman"]), r["baslik"], " · ".join(sorular[:3]), r["url"])):
                    self.gunluk.setItem(i, j, QTableWidgetItem(metin))
            self.gunluk.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            return
        satirlar = db.execute("SELECT zaman, mod, url, karar, neden FROM gozlem_kayit ORDER BY id DESC LIMIT 200").fetchall()
        self.gunluk.setColumnCount(5)
        self.gunluk.setHorizontalHeaderLabels(["Zaman", "Kaynak", "Adres", "Karar", "Açıklama"])
        self.gunluk.setRowCount(len(satirlar))
        for i, r in enumerate(satirlar):
            etiket, renk = self.KARAR.get(r["karar"], (r["karar"], R["soluk"]))
            ogeler = (_tarih(r["zaman"]), self.MOD.get(r["mod"], r["mod"] or "—"), r["url"], etiket, r["neden"])
            for j, metin in enumerate(ogeler):
                oge = QTableWidgetItem(metin)
                if j == 3:
                    oge.setForeground(QColor(renk))
                self.gunluk.setItem(i, j, oge)
        self.gunluk.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

    def eklenti_temas(self, zaman: float) -> None:
        self.son_temas = zaman
        self._eklenti_durumunu_yenile()

    def gozlem_durumu_yaz(self, metin: str) -> None:
        self.gozlem_bilgi.setText(metin)

    # ------------------------------------------------------------------ eylemler
    def _siteler(self) -> list[str]:
        return list(self.s.ayarlar.al("gozlem.motor.siteler", []) or [])

    def _site_ekle(self) -> None:
        from ..crawler import beyaz_liste
        from ..gozlem.degerlendirici import sistem_mi
        from ..gozlem.motor import kok_adres
        kok = kok_adres(self.yeni_site.text())
        if not kok or not beyaz_liste.birincil_mi(kok) or sistem_mi(kok):
            self.gozlem_durumu_yaz("Bu adres eklenemez: yalnız beyaz listedeki herkese açık resmî siteler taranır; "
                                   "kamu sistemleri ve giriş sayfaları taranmaz.")
            return
        siteler = self._siteler()
        if kok not in siteler:
            siteler.append(kok)
            self.s.ayarlar.ayarla("gozlem.motor.siteler", siteler)
            self.s.ayarlar.kaydet()
        self.yeni_site.clear()
        self._siteleri_yenile()

    def _secili_siteler(self) -> list[str]:
        siteler = self._siteler()
        satirlar = sorted({i.row() for i in self.site_tablosu.selectedIndexes()})
        return [siteler[r] for r in satirlar if 0 <= r < len(siteler)]

    def _site_kaldir(self) -> None:
        secili = set(self._secili_siteler())
        if not secili:
            return
        self.s.ayarlar.ayarla("gozlem.motor.siteler", [x for x in self._siteler() if x not in secili])
        self.s.ayarlar.kaydet()
        self._siteleri_yenile()

    def _secili_tara(self) -> None:
        for site in self._secili_siteler():
            self.tara_istendi.emit(site)

    def _tumunu_tara(self) -> None:
        for site in self._siteler():
            self.tara_istendi.emit(site)

    def _ayarlari_kaydet(self, *_) -> None:
        a = self.s.ayarlar
        a.ayarla("gozlem.motor.hiz", self.hiz.currentData() or "normal")
        a.ayarla("gozlem.motor.en_cok_sayfa", self.en_cok.value())
        a.ayarla("gozlem.motor.derinlik", self.derinlik.value())
        a.ayarla("gozlem.motor.tarayici_yolu", self.tarayici_yolu.text().strip())
        a.ayarla("gozlem.acik", self.gozlem_acik.isChecked())
        a.ayarla("gozlem.port", self.gozlem_port.value())
        a.kaydet()
        self.ayarlar_degisti.emit()

    def _anahtari_kopyala(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.gozlem_anahtar.text())
        self.gozlem_durumu_yaz("Anahtar panoya kopyalandı (yalnız köprü kurulu değilse eklentiye elle girilir).")

    def _anahtari_yenile(self) -> None:
        from ..gozlem.eslestirme import yeni_anahtar
        anahtar = yeni_anahtar()
        self.s.ayarlar.ayarla("gozlem.anahtar", anahtar)
        self.s.ayarlar.kaydet()
        self.gozlem_anahtar.setText(anahtar)
        self.ayarlar_degisti.emit()
        self.gozlem_durumu_yaz("Yeni anahtar üretildi. Eklenti köprüyle yenisini kendiliğinden alır.")

    def _eklenti_klasoru(self) -> None:
        from ..gozlem.kurulum import eklentiyi_hazirla
        hedef = eklentiyi_hazirla(self.s.yollar.kok)
        if hedef is None:
            self.gozlem_durumu_yaz("Eklenti dosyaları program paketinde bulunamadı.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(hedef)))

    def _kurulum_yonergesi(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from ..gozlem.kurulum import YONERGE
        QMessageBox.information(self, "Akıl Hocası Gözlemci", YONERGE)

    def _gunluk_ac(self, indeks) -> None:
        sutun = 3 if self.gunluk.columnCount() == 4 else 2
        oge = self.gunluk.item(indeks.row(), sutun)
        if oge and oge.text().startswith("http"):
            QDesktopServices.openUrl(QUrl(oge.text()))


class ZekaSayfasi(QWidget):
    """Yapay zekâ ve çekirdek: modeller, ilkeler, Yordam Kitabı, ilke karnesi, dersler, ayarlar, gelişim geçmişi."""

    kur_istendi = Signal(list)
    kullan_istendi = Signal(str)
    sil_istendi = Signal(str)
    durdur_istendi = Signal()
    gelistir_istendi = Signal()

    def __init__(self, s, parent=None):
        super().__init__(parent)
        self.s = s
        dis = QVBoxLayout(self)
        dis.setContentsMargins(0, 0, 0, 0)
        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        ic = QWidget()
        yer = QVBoxLayout(ic)
        yer.setContentsMargins(32, 26, 32, 22)
        yer.setSpacing(14)
        _baslik(yer, "Yapay Zekâ ve Çekirdek", "Akıl Hocası'nın yerel dil modeli, temel çalışma ilkeleri, iş akışı "
                                               "yordamları ve kendini geliştirme kaydı. Modeller bu bilgisayarda çalışır; "
                                               "sorular ve belgeler dışarı gönderilmez.")
        yer.addWidget(self._model_karti())
        izgara = QGridLayout()
        izgara.setSpacing(14)
        izgara.addWidget(self._cekirdek_karti(), 0, 0)
        izgara.addWidget(self._karne_karti(), 0, 1)
        izgara.setColumnStretch(0, 1)
        izgara.setColumnStretch(1, 1)
        yer.addLayout(izgara)
        yer.addWidget(self._gelisim_karti())
        yer.addStretch(1)
        kaydirma.setWidget(ic)
        dis.addWidget(kaydirma)
        self.yenile()

    # ------------------------------------------------------------------ kartlar
    def _kart(self, baslik: str, alt: str = ""):
        kart = QFrame()
        kart.setObjectName("AyarKart")
        yer = QVBoxLayout(kart)
        yer.setContentsMargins(18, 14, 18, 16)
        yer.setSpacing(10)
        b = QLabel(baslik)
        b.setStyleSheet("font-size:15px; font-weight:700;")
        yer.addWidget(b)
        if alt:
            a = QLabel(alt)
            a.setWordWrap(True)
            a.setStyleSheet(f"color:{R['metin2']};")
            yer.addWidget(a)
        return kart, yer

    @staticmethod
    def _tablo(sutunlar: list[str], germe: int = 0, yukseklik: int = 180) -> QTableWidget:
        t = QTableWidget(0, len(sutunlar))
        t.setHorizontalHeaderLabels(sutunlar)
        t.horizontalHeader().setSectionResizeMode(germe, QHeaderView.Stretch)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setShowGrid(False)
        t.setAlternatingRowColors(True)
        t.setMinimumHeight(yukseklik)
        return t

    def _model_karti(self) -> QWidget:
        from PySide6.QtWidgets import QProgressBar
        kart, yer = self._kart("Yerel dil modeli")
        self.model_durum = QLabel()
        self.model_durum.setWordWrap(True)
        yer.addWidget(self.model_durum)
        self.model_tablosu = self._tablo(["Model", "Görev", "Boyut", "Bu bilgisayar", "Durum"], 0, 200)
        yer.addWidget(self.model_tablosu)
        satir = QHBoxLayout()
        onerilen = QPushButton("  Önerilenleri kur")
        onerilen.setObjectName("Birincil")
        onerilen.setIcon(ikon("indir", "#FFFFFF", 16))
        onerilen.clicked.connect(self._onerilenleri_kur)
        kur = QPushButton("Seçiliyi kur")
        kur.clicked.connect(lambda: self.kur_istendi.emit(self._secili_kimlikler()))
        kullan = QPushButton("Kullan")
        kullan.clicked.connect(lambda: [self.kullan_istendi.emit(k) for k in self._secili_kimlikler()[:1]])
        sil = QPushButton("Sil")
        sil.clicked.connect(lambda: [self.sil_istendi.emit(k) for k in self._secili_kimlikler()[:1]])
        for d in (onerilen, kur, kullan, sil):
            satir.addWidget(d)
        satir.addStretch(1)
        yer.addLayout(satir)
        self.indirme_cubugu = QProgressBar()
        self.indirme_cubugu.setRange(0, 1000)
        self.indirme_cubugu.setTextVisible(False)
        self.indirme_cubugu.setFixedHeight(8)
        self.indirme_cubugu.hide()
        yer.addWidget(self.indirme_cubugu)
        alt = QHBoxLayout()
        self.indirme_metni = QLabel()
        self.indirme_metni.setObjectName("Ikincil")
        alt.addWidget(self.indirme_metni, 1)
        self.indirme_durdur = QPushButton("Durdur")
        self.indirme_durdur.hide()
        self.indirme_durdur.clicked.connect(self.durdur_istendi.emit)
        alt.addWidget(self.indirme_durdur)
        yer.addLayout(alt)
        f = QFormLayout()
        self.ortak = QLineEdit(self.s.ayarlar.al("yz.ortak_klasor", ""))
        self.ortak.setPlaceholderText(r"\\sunucu\ortak\AkilHocasi\modeller (internet yoksa model dosyaları buradan alınır)")
        self.ayna = QLineEdit(self.s.ayarlar.al("yz.ayna", ""))
        self.ayna.setPlaceholderText("https://... (kurum içi model aynası; boşsa Hugging Face)")
        f.addRow("Ortak model klasörü", self.ortak)
        f.addRow("Model aynası", self.ayna)
        yer.addLayout(f)
        kaydet = QPushButton("Kaynak ayarlarını kaydet")
        kaydet.clicked.connect(self._kaynaklari_kaydet)
        yer.addWidget(kaydet, 0, Qt.AlignLeft)
        return kart

    def _cekirdek_karti(self) -> QWidget:
        from ..cekirdek.ilkeler import CEKIRDEK_SURUMU, ILKELER
        from ..cekirdek.yordamlar import YORDAMLAR
        kart, yer = self._kart(f"Çekirdek (sürüm {CEKIRDEK_SURUMU})",
                               f"{len(ILKELER)} temel ilke ve {len(YORDAMLAR)} yordam. İlkeler öğrenmeyle değişmez; "
                               "yordamların ayarları yalnızca izinli aralıkta ve gelişim kapısından geçerek değişir.")
        liste = QLabel("<br>".join(f"<b>{n}. {html.escape(i.ad)}:</b> {html.escape(i.ilke)}"
                                   for n, i in enumerate(ILKELER, 1)))
        liste.setWordWrap(True)
        liste.setTextFormat(Qt.RichText)
        yer.addWidget(liste)
        d = QPushButton("  Çekirdek El Kitabı (ilkeler, iş akışları, yordamlar)")
        d.setIcon(ikon("dosya", R["metin"], 16))
        d.clicked.connect(self._el_kitabi)
        yer.addWidget(d, 0, Qt.AlignLeft)
        return kart

    def _karne_karti(self) -> QWidget:
        kart, yer = self._kart("İlke karnesi", "Son sınavda her ilkenin notu (1,00 en iyi). Hiçbir ilkenin notunu "
                                               "düşüren değişiklik benimsenmez.")
        self.karne_ozet = QLabel()
        self.karne_ozet.setWordWrap(True)
        yer.addWidget(self.karne_ozet)
        self.karne_tablosu = self._tablo(["İlke", "Not", "Ölçülen"], 0, 260)
        yer.addWidget(self.karne_tablosu)
        return kart

    def _gelisim_karti(self) -> QWidget:
        kart, yer = self._kart("Kendini geliştirme", "Bilgisayar boştayken: anlam dizini, kendi çalışma soruları, "
                                                     "hatalardan dersler, yordam ayarı denemeleri ve model yarışı.")
        satir = QHBoxLayout()
        self.gelisim_durum = QLabel()
        self.gelisim_durum.setWordWrap(True)
        satir.addWidget(self.gelisim_durum, 1)
        g = QPushButton("  Şimdi kendini geliştir")
        g.setObjectName("Birincil")
        g.setIcon(ikon("yenile", "#FFFFFF", 16))
        g.clicked.connect(self.gelistir_istendi.emit)
        satir.addWidget(g)
        yer.addLayout(satir)
        self.gelisim_turu = SegmentSecici([("gecmis", "Gelişim geçmişi"), ("dersler", "Dersler"),
                                           ("ayarlar", "Yordam ayarları")], "gecmis")
        self.gelisim_turu.degisti.connect(lambda _: self._gelisim_tablosu_yenile())
        yer.addWidget(self.gelisim_turu, 0, Qt.AlignLeft)
        self.gelisim_tablosu = self._tablo(["Zaman", "Tür", "Konu", "Karar", "Gerekçe"], 2, 240)
        yer.addWidget(self.gelisim_tablosu)
        return kart

    # ------------------------------------------------------------------ yenileme
    def yenile(self) -> None:
        self.model_durumu_yaz(self.s.yz.durum())
        self._karne_yenile()
        self._gelisim_tablosu_yenile()

    def model_durumu_yaz(self, d: dict) -> None:
        don = d.get("donanim", {})
        satirlar = []
        if d.get("hazir"):
            olcum = d.get("olcum") or {}
            satirlar.append(f"<span style='color:{R['yesil']};'><b>Hazır:</b></span> {html.escape(d.get('model_adi', ''))}"
                            + (f" · kısa cevap süresi {olcum['sure_sn']} sn" if olcum.get("sure_sn") else ""))
        elif not d.get("sunucu_var"):
            satirlar.append(f"<span style='color:{R['sari']};'>Model sunucusu (llama-server) bulunamadı; "
                            "program alıntıya dayalı modda çalışıyor.</span>")
        elif not d.get("sohbet"):
            satirlar.append(f"<span style='color:{R['sari']};'><b>Dil modeli kurulu değil.</b></span> "
                            "\"Önerilenleri kur\" ile bu bilgisayara uygun model indirilir.")
        else:
            satirlar.append("Model başlatılıyor…")
        a_hazir, a_toplam = d.get("anlam_ilerleme", (0, 0))
        if d.get("anlam_calisiyor"):
            satirlar.append(f"Anlam araması: {a_hazir:,}/{a_toplam:,} madde dizinlendi".replace(",", "."))
        satirlar.append(f"Bilgisayar: {don.get('bellek_gb', '?')} GB bellek, {don.get('cekirdek', '?')} mantıksal çekirdek"
                        + (" · pilde" if don.get("prizde") is False else ""))
        if d.get("son_hata"):
            satirlar.append(f"<span style='color:{R['kirmizi']};'>{html.escape(d['son_hata'])}</span>")
        self.model_durum.setText("<br>".join(satirlar))
        kurulu = {m["kimlik"]: m for m in self.s.yz.kurulu()}
        secili = {t: (d.get(t) or {}).get("kimlik") for t in ("sohbet", "anlam")}
        bellek = don.get("bellek_gb", 0) or 0
        modeller = sorted(self.s.yz.katalog.modeller.values(), key=lambda m: (m.tur != "sohbet", -m.oncelik))
        self._model_kimlikleri = [m.kimlik for m in modeller]
        self.model_tablosu.setRowCount(len(modeller))
        for i, m in enumerate(modeller):
            uygun = "Uygun" if m.en_az_bellek_gb <= bellek else f"En az {m.en_az_bellek_gb:g} GB bellek"
            if d.get("onerilen", {}).get(m.tur) == m.kimlik:
                uygun = "Önerilen"
            durum = ("Kullanılıyor" if secili.get(m.tur) == m.kimlik else "Kurulu" if m.kimlik in kurulu else
                     "Aday (yarışta denenir)" if m.aday else "—")
            for j, metin in enumerate((m.ad + (f" — {m.aciklama}" if m.aciklama else ""),
                                       "Danışma" if m.tur == "sohbet" else "Anlam araması",
                                       f"{m.yaklasik_gb:g} GB", uygun, durum)):
                self.model_tablosu.setItem(i, j, QTableWidgetItem(metin))

    def indirme_durumu(self, alinan_mb: float, toplam_mb: float, metin: str) -> None:
        self.indirme_cubugu.show()
        self.indirme_durdur.show()
        if toplam_mb:
            self.indirme_cubugu.setValue(int(1000 * alinan_mb / toplam_mb))
        self.indirme_metni.setText(f"{metin} — {alinan_mb / 1024:.2f} / {toplam_mb / 1024:.2f} GB" if toplam_mb else metin)

    def indirme_bitti(self, mesaj: str) -> None:
        self.indirme_cubugu.hide()
        self.indirme_durdur.hide()
        self.indirme_metni.setText(mesaj)

    def _karne_yenile(self) -> None:
        from ..cekirdek.ilkeler import ILKELER
        gecmis = self.s.strateji.karne_gecmisi(2)
        if not gecmis:
            self.karne_ozet.setText("Henüz sınav yapılmadı. Altın soru seti yüklendiğinde ya da program kendi "
                                    "çalışma sorularını ürettiğinde ilk karne çıkar.")
            self.karne_tablosu.setRowCount(0)
            return
        son = gecmis[0]
        onceki = gecmis[1] if len(gecmis) > 1 else None
        self.karne_ozet.setText(f"{_tarih(son['zaman'])} · {son.get('toplam', 0)} soru · başarı "
                                f"<b>%{round(100 * son.get('basari', 0))}</b> · kritik hata {son.get('kritik', 0)} · "
                                f"ilke ortalaması {son.get('ortalama', 0):.2f}")
        self.karne_tablosu.setRowCount(len(ILKELER))
        for i, ilke in enumerate(ILKELER):
            notu = son.get("notlar", {}).get(ilke.kod)
            olculen = son.get("ornek", {}).get(ilke.kod, 0)
            fark = ""
            if onceki and notu is not None and onceki.get("notlar", {}).get(ilke.kod) is not None:
                d = notu - onceki["notlar"][ilke.kod]
                fark = f" ({'+' if d >= 0 else ''}{d:.2f})" if abs(d) >= 0.005 else ""
            for j, metin in enumerate((ilke.ad, f"{notu:.2f}{fark}" if notu is not None and olculen else "—",
                                       str(olculen))):
                self.karne_tablosu.setItem(i, j, QTableWidgetItem(metin))

    def _gelisim_tablosu_yenile(self) -> None:
        tur = self.gelisim_turu.secili
        t = self.gelisim_tablosu
        if tur == "dersler":
            satirlar = [(_tarih(d["olusturma"]), d["yordam"], d["metin"], d["durum"], d["gerekce"] or "")
                        for d in self.s.dersler.tumu()[:200]]
            basliklar = ["Zaman", "Yordam", "Ders", "Durum", "Gerekçe"]
        elif tur == "ayarlar":
            satirlar = [("", a["yordam_adi"], a["aciklama"], str(a["deger"]),
                         {"varsayilan": "varsayılan", "ogrenme": "öğrenildi", "kullanici": "kullanıcı"}.get(a["kaynak"], a["kaynak"]))
                        for a in self.s.strateji.tumu()]
            basliklar = ["", "Yordam", "Ayar", "Değer", "Kaynak"]
        else:
            turler = {"strateji": "Yordam ayarı", "ders": "Ders", "model": "Model", "geri_alma": "Geri alma"}
            satirlar = [(_tarih(g["zaman"]), turler.get(g["tur"], g["tur"]), g["konu"], g["karar"], g["gerekce"])
                        for g in self.s.strateji.gelisim_gecmisi(200)]
            basliklar = ["Zaman", "Tür", "Konu", "Karar", "Gerekçe"]
        t.setHorizontalHeaderLabels(basliklar)
        t.setRowCount(len(satirlar))
        for i, satir in enumerate(satirlar):
            for j, metin in enumerate(satir):
                t.setItem(i, j, QTableWidgetItem(str(metin)))

    def gelisim_durumu_yaz(self, metin: str) -> None:
        self.gelisim_durum.setText(metin)

    # ------------------------------------------------------------------ eylemler
    def _secili_kimlikler(self) -> list[str]:
        satirlar = sorted({i.row() for i in self.model_tablosu.selectedIndexes()})
        return [self._model_kimlikleri[r] for r in satirlar if 0 <= r < len(getattr(self, "_model_kimlikleri", []))]

    def _onerilenleri_kur(self) -> None:
        self.kur_istendi.emit([m.kimlik for m in self.s.yz.eksik_kurulum()])

    def _kaynaklari_kaydet(self) -> None:
        self.s.ayarlar.ayarla("yz.ortak_klasor", self.ortak.text().strip())
        self.s.ayarlar.ayarla("yz.ayna", self.ayna.text().strip())
        self.s.ayarlar.kaydet()
        from ..yz.indirici import ModelIndirici
        self.s.yz.indirici = ModelIndirici(self.s.yz.model_klasoru(), self.ayna.text().strip(), self.ortak.text().strip())
        self.indirme_metni.setText("Model kaynak ayarları kaydedildi.")

    def _el_kitabi(self) -> None:
        from PySide6.QtWidgets import QDialog, QTextBrowser

        from ..cekirdek.yordamlar import el_kitabi_md
        p = QDialog(self)
        p.setWindowTitle("Akıl Hocası — Çekirdek El Kitabı")
        p.resize(860, 760)
        v = QVBoxLayout(p)
        t = QTextBrowser()
        t.setMarkdown(el_kitabi_md())
        v.addWidget(t)
        p.exec()
