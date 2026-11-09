"""Diğer sayfalar: Belge Deposu, Neler Değişti, Ayarlar, Yazı Hazırlama ve yakında gelecek modüller."""

from __future__ import annotations

import html
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTime, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
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
    gozlem_degisti = Signal()

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

        # Tarayıcı gözlemcisi
        izgara.addWidget(self._gozlem_karti(ayarlar, yollar), 3, 0, 1, 2)

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
        izgara.addWidget(k, 4, 0, 1, 2)
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

    def _gozlem_karti(self, ayarlar, yollar) -> QWidget:
        k, f = self._kart("Tarayıcı gözlemcisi (Chrome / Edge eklentisi)")
        aciklama = QLabel("Eklenti, gezdiğiniz ya da taramasını istediğiniz herkese açık resmî sayfaları (Resmî Gazete, "
                          "mevzuat.gov.tr, TOGÜ, YÖK, HMB, SGK...) bu programa iletir; program her sayfayı denetleyip "
                          "sürümlü kaynak olarak kütüphaneye ekler, resmî dosyaları depoya indirir. Kamu sistemlerine "
                          "ve giriş gerektiren sayfalara girilmez, hiçbir düğmeye tıklanmaz.")
        aciklama.setWordWrap(True)
        aciklama.setStyleSheet(f"color:{R['metin2']};")
        f.addRow(aciklama)
        self.gozlem_acik = QCheckBox("Eklentiden gelen resmî sayfaları değerlendir ve kütüphaneye ekle")
        self.gozlem_acik.setChecked(ayarlar.al("gozlem.acik", True))
        f.addRow(self.gozlem_acik)
        self.gozlem_port = QSpinBox()
        self.gozlem_port.setRange(1024, 65535)
        self.gozlem_port.setValue(int(ayarlar.al("gozlem.port", 47231)))
        self.gozlem_port.setToolTip("Yalnız bu bilgisayar (127.0.0.1) üzerinden dinlenir")
        f.addRow("Yerel bağlantı noktası", self.gozlem_port)

        satir = QHBoxLayout()
        self.gozlem_anahtar = QLineEdit(ayarlar.al("gozlem.anahtar", ""))
        self.gozlem_anahtar.setReadOnly(True)
        self.gozlem_anahtar.setEchoMode(QLineEdit.Password)
        satir.addWidget(self.gozlem_anahtar, 1)
        goster = QPushButton("Göster")
        goster.setCheckable(True)
        goster.toggled.connect(lambda a: (self.gozlem_anahtar.setEchoMode(QLineEdit.Normal if a else QLineEdit.Password),
                                          goster.setText("Gizle" if a else "Göster")))
        kopyala = QPushButton("Kopyala")
        kopyala.clicked.connect(self._anahtari_kopyala)
        yenile = QPushButton("Yenile")
        yenile.setToolTip("Yeni anahtar üretir; eklentiye yeniden girilmesi gerekir")
        yenile.clicked.connect(self._anahtari_yenile)
        for d in (goster, kopyala, yenile):
            satir.addWidget(d)
        kap = QWidget()
        kap.setLayout(satir)
        f.addRow("Eşleştirme anahtarı", kap)

        dugmeler = QHBoxLayout()
        klasor = QPushButton("  Eklenti klasörünü aç")
        klasor.setIcon(ikon("klasor", R["metin"], 16))
        klasor.clicked.connect(lambda: self._eklenti_klasoru(yollar))
        nasil = QPushButton("Nasıl kurulur?")
        nasil.clicked.connect(self._kurulum_yonergesi)
        dugmeler.addWidget(klasor)
        dugmeler.addWidget(nasil)
        dugmeler.addStretch(1)
        kap2 = QWidget()
        kap2.setLayout(dugmeler)
        f.addRow(kap2)
        self.gozlem_durum = QLabel("Gözlemci durumu: başlatılıyor…")
        self.gozlem_durum.setWordWrap(True)
        f.addRow(self.gozlem_durum)
        return k

    def gozlem_durumu_yaz(self, metin: str) -> None:
        self.gozlem_durum.setText(metin)

    def _anahtari_kopyala(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.gozlem_anahtar.text())
        self.gozlem_durum.setText("Eşleştirme anahtarı panoya kopyalandı. Eklentinin Ayarlar sayfasına yapıştırın.")

    def _anahtari_yenile(self) -> None:
        from ..gozlem.sunucu import yeni_anahtar
        anahtar = yeni_anahtar()
        self.ayarlar.ayarla("gozlem.anahtar", anahtar)
        self.ayarlar.kaydet()
        self.gozlem_anahtar.setText(anahtar)
        self.gozlem_degisti.emit()
        self.gozlem_durum.setText("Yeni anahtar üretildi. Eklentideki eski anahtar artık geçersiz; yenisini girin.")

    def _eklenti_klasoru(self, yollar) -> None:
        from ..gozlem.kurulum import eklentiyi_hazirla
        hedef = eklentiyi_hazirla(yollar.kok)
        if hedef is None:
            self.gozlem_durum.setText("Eklenti dosyaları program paketinde bulunamadı.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(hedef)))

    def _kurulum_yonergesi(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from ..gozlem.kurulum import YONERGE
        QMessageBox.information(self, "Akıl Hocası Gözlemci", YONERGE)

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
        a.ayarla("gozlem.acik", self.gozlem_acik.isChecked())
        a.ayarla("gozlem.port", self.gozlem_port.value())
        a.kaydet()
        self.kaydedildi.emit()
