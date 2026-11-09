"""Resmî Yazı Hazırlama ekranı.

Sol: yazı türü, gelen yazı (yapıştır / Word / PDF / görüntü), talimat, muhatap ve makam, ekler, dağıtım, ivedilik.
Sağ: önizleme, metni düzenleme, EBYS metni, kontrol listesi ve "Nasıl düşündüm". Taslak Word'e kaydedilir ya da
EBYS'ye alan alan kopyalanır; sayı, tarih ve e-imzayı EBYS verir.
"""

from __future__ import annotations

import html
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..yazi.cikti import docx_kaydet, ebys_metni, html_onizleme
from ..yazi.gelen import GelenYazi, cozumle
from ..yazi.hazirlayici import YaziHazirlayici, YaziIstegi, YaziSonucu
from ..yazi.kontrol import duzelt, kontrol_et
from ..yazi.model import MAKAM_ILISKILERI, YAZI_TURLERI, Imza, Paragraf
from .ikonlar import ikon
from .tema import R

PROFIL_ALANLARI = [
    ("idare", "İdare adı (başlık 2. satır)", "TOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ"),
    ("birim", "Birim adı (başlık 3. satır)", "ör. Personel Daire Başkanlığı"),
    ("imza_on_unvan", "İmza: akademik unvan", "ör. Prof. Dr. (yoksa boş)"),
    ("imza_ad", "İmza: ad", ""),
    ("imza_soyad", "İmza: soyad", ""),
    ("imza_unvan", "İmza: unvan", "ör. Daire Başkanı"),
    ("yetki", "Yetki devri / vekâlet", "ör. Rektör a.  (yoksa boş)"),
    ("dosya_kodu", "Standart dosya planı kodu", "ör. 903.02 (bilinmiyorsa boş)"),
    ("adres", "Adres", ""),
    ("telefon", "Telefon", ""),
    ("eposta", "E-posta", ""),
    ("kep", "KEP adresi", ""),
    ("internet", "İnternet adresi", ""),
    ("bilgi_ad", "Bilgi için: ad soyad", ""),
    ("bilgi_unvan", "Bilgi için: unvan", ""),
    ("bilgi_telefon", "Bilgi için: telefon", ""),
]
DURUM_RENK = {"tamam": R["yesil"], "uyari": R["sari"], "hata": R["kirmizi"], "bilgi": R["metin2"]}
DURUM_AD = {"tamam": "Tamam", "uyari": "Uyarı", "hata": "Hata", "bilgi": "Bilgi"}


class YaziCalisani(QThread):
    ilerleme = Signal(int, int, str)
    bitti = Signal(object)
    hata = Signal(str)

    def __init__(self, hazirlayici: YaziHazirlayici, istek: YaziIstegi, parent=None):
        super().__init__(parent)
        self.h, self.istek = hazirlayici, istek

    def run(self) -> None:
        try:
            self.bitti.emit(self.h.hazirla(self.istek, lambda a, t, m: self.ilerleme.emit(a, t, m)))
        except Exception:  # noqa: BLE001
            self.hata.emit(traceback.format_exc(limit=4))


class ProfilPenceresi(QDialog):
    """Birim profili: başlık, imza ve iletişim bilgileri (bir kez girilir, her yazıda kullanılır)."""

    def __init__(self, profil: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Birim profili — resmî yazı")
        self.resize(560, 640)
        v = QVBoxLayout(self)
        a = QLabel("Bu bilgiler yazının başlığına, imza bölümüne ve sayfa altındaki iletişim alanına girer "
                   "(Yönetmelik md. 10, 17, 24). Program bunları kendisi uydurmaz.")
        a.setWordWrap(True)
        a.setObjectName("Ikincil")
        v.addWidget(a)
        kay = QScrollArea()
        kay.setWidgetResizable(True)
        ic = QWidget()
        f = QFormLayout(ic)
        self.alanlar: dict[str, QLineEdit] = {}
        for anahtar, etiket, ipucu in PROFIL_ALANLARI:
            e = QLineEdit(profil.get(anahtar, ""))
            e.setPlaceholderText(ipucu)
            self.alanlar[anahtar] = e
            f.addRow(etiket, e)
        self.yazi_tipi = QComboBox()
        self.yazi_tipi.addItems(["Times New Roman", "Arial"])
        self.yazi_tipi.setCurrentText(profil.get("yazi_tipi", "Times New Roman"))
        f.addRow("Yazı tipi (md. 7)", self.yazi_tipi)
        self.logo = QCheckBox("Kurum logosu kullanılıyor (üst boşluk 0,5 cm)")
        self.logo.setChecked(bool(profil.get("logo", False)))
        f.addRow("", self.logo)
        kay.setWidget(ic)
        v.addWidget(kay, 1)
        b = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        v.addWidget(b)

    def profil(self) -> dict:
        p = {k: e.text().strip() for k, e in self.alanlar.items()}
        p["yazi_tipi"] = self.yazi_tipi.currentText()
        p["logo"] = self.logo.isChecked()
        return p


class YaziHazirlamaSayfasi(QWidget):
    def __init__(self, s, parent=None):
        super().__init__(parent)
        self.s = s
        self.hazirlayici = YaziHazirlayici(s.hat, getattr(s, "dersler", None))
        self.sonuc: YaziSonucu | None = None
        self.gelen: GelenYazi | None = None
        self.dayanak_cevabi = None
        self.calisan: YaziCalisani | None = None

        dis = QVBoxLayout(self)
        dis.setContentsMargins(28, 22, 28, 16)
        dis.setSpacing(10)
        ust = QHBoxLayout()
        b = QLabel("Resmî Yazı Hazırlama")
        b.setObjectName("SayfaBaslik")
        ust.addWidget(b)
        ust.addStretch(1)
        profil = QPushButton("  Birim profili")
        profil.setIcon(ikon("kisi", R["metin"], 16))
        profil.clicked.connect(self.profil_duzenle)
        ust.addWidget(profil)
        dis.addLayout(ust)
        a = QLabel("Gelen yazıya cevap ya da yeni yazı: 2020 Resmî Yazışma Yönetmeliğine göre TASLAK hazırlanır. "
                   "Metindeki her tarih, sayı ve atıf gelen yazıda, talimatınızda ya da doğrulanmış mevzuatta olmalıdır; "
                   "olmayan cümle çıkarılır. Sayı, tarih ve e-imzayı EBYS verir.")
        a.setObjectName("Ikincil")
        a.setWordWrap(True)
        dis.addWidget(a)

        bolucu = QSplitter(Qt.Horizontal)
        bolucu.addWidget(self._form_kur())
        bolucu.addWidget(self._sonuc_kur())
        bolucu.setStretchFactor(0, 0)
        bolucu.setStretchFactor(1, 1)
        bolucu.setSizes([430, 820])
        dis.addWidget(bolucu, 1)
        self._tur_degisti()

    # ------------------------------------------------------------------ form
    def _form_kur(self) -> QWidget:
        kay = QScrollArea()
        kay.setWidgetResizable(True)
        kay.setMinimumWidth(380)
        ic = QWidget()
        v = QVBoxLayout(ic)
        v.setContentsMargins(0, 4, 10, 4)
        v.setSpacing(8)

        def baslik(metin: str) -> None:
            lb = QLabel(metin.upper())
            lb.setObjectName("BolumBaslik")
            v.addWidget(lb)

        baslik("Yazı türü")
        self.tur = QComboBox()
        for k, t in YAZI_TURLERI.items():
            self.tur.addItem(t["ad"], k)
        self.tur.currentIndexChanged.connect(self._tur_degisti)
        v.addWidget(self.tur)

        baslik("Gelen yazı")
        self.gelen_metin = QPlainTextEdit()
        self.gelen_metin.setObjectName("Duz")
        self.gelen_metin.setPlaceholderText("Gelen yazının metnini yapıştırın ya da dosyadan açın "
                                            "(Word, PDF ya da ekran görüntüsü). Yeni yazı için boş bırakın.")
        self.gelen_metin.setMinimumHeight(130)
        v.addWidget(self.gelen_metin)
        satir = QHBoxLayout()
        ac = QPushButton("  Dosyadan aç")
        ac.setIcon(ikon("ek", R["metin"], 16))
        ac.clicked.connect(self.dosyadan_ac)
        coz = QPushButton("Çözümle")
        coz.clicked.connect(self.gelen_cozumle)
        satir.addWidget(ac)
        satir.addWidget(coz)
        satir.addStretch(1)
        v.addLayout(satir)
        self.gelen_ozet = QLabel()
        self.gelen_ozet.setWordWrap(True)
        self.gelen_ozet.setStyleSheet(f"background:{R['ana_acik']}; border-radius:10px; padding:8px; font-size:12px;")
        self.gelen_ozet.hide()
        v.addWidget(self.gelen_ozet)

        baslik("Ne yazılsın?")
        self.talimat = QPlainTextEdit()
        self.talimat.setObjectName("Duz")
        self.talimat.setPlaceholderText("Birimin cevabı, görüşü ya da istenen husus. Ör. \"Başkanlığımızda aylıksız "
                                        "izin kullanan 2 personel bulunmaktadır; izin süreleri ekteki listededir.\"")
        self.talimat.setMinimumHeight(90)
        v.addWidget(self.talimat)
        self.dayanak_etiketi = QLabel()
        self.dayanak_etiketi.setWordWrap(True)
        self.dayanak_etiketi.setObjectName("Ikincil")
        self.dayanak_etiketi.hide()
        v.addWidget(self.dayanak_etiketi)

        baslik("Muhatap")
        f = QFormLayout()
        self.muhatap = QLineEdit()
        self.muhatap.setPlaceholderText("Gelen yazıdan alınır; ör. Strateji Geliştirme Daire Başkanlığı / Sayın Ad SOYAD")
        self.muhatap_birim = QLineEdit()
        self.muhatap_birim.setPlaceholderText("Başka idareye yazılırken birim (parantez içinde)")
        self.makam = QComboBox()
        self.makam.addItem("Otomatik (muhataba göre)", "")
        for k, ad in MAKAM_ILISKILERI.items():
            self.makam.addItem(ad, k)
        self.makam.setToolTip("Bitiş ifadesini belirler: üst ve aynı düzey makama “arz ederim”, alt makama “rica "
                              "ederim” (md. 16)")
        f.addRow("Muhatap", self.muhatap)
        f.addRow("Birim", self.muhatap_birim)
        f.addRow("Makam", self.makam)
        v.addLayout(f)
        self.dagitimli = QCheckBox("Dağıtımlı yazı (DAĞITIM YERLERİNE)")
        v.addWidget(self.dagitimli)
        d = QHBoxLayout()
        self.gerek = QPlainTextEdit()
        self.gerek.setObjectName("Duz")
        self.gerek.setPlaceholderText("Gereği (her satıra bir makam)")
        self.gerek.setFixedHeight(64)
        self.bilgi = QPlainTextEdit()
        self.bilgi.setObjectName("Duz")
        self.bilgi.setPlaceholderText("Bilgi (her satıra bir makam)")
        self.bilgi.setFixedHeight(64)
        d.addWidget(self.gerek)
        d.addWidget(self.bilgi)
        self.dagitim_kutusu = QWidget()
        self.dagitim_kutusu.setLayout(d)
        self.dagitim_kutusu.hide()
        self.dagitimli.toggled.connect(self.dagitim_kutusu.setVisible)
        v.addWidget(self.dagitim_kutusu)

        baslik("Ekler ve süre")
        self.ekler = QPlainTextEdit()
        self.ekler.setObjectName("Duz")
        self.ekler.setPlaceholderText("Her satıra bir ek, sayfa/adet bilgisiyle: Personel listesi (2 sayfa)")
        self.ekler.setFixedHeight(64)
        v.addWidget(self.ekler)
        f2 = QFormLayout()
        self.ivedilik = QComboBox()
        self.ivedilik.addItems(["", "ACELE", "GÜNLÜDÜR"])
        self.sure = QLineEdit()
        self.sure.setPlaceholderText("GÜNLÜDÜR ise: ör. 20.11.2026 tarihine kadar")
        f2.addRow("İvedilik (md. 26)", self.ivedilik)
        f2.addRow("Cevap süresi", self.sure)
        v.addLayout(f2)
        self.olur_kutusu = QWidget()
        fo = QFormLayout(self.olur_kutusu)
        fo.setContentsMargins(0, 0, 0, 0)
        self.olur_ad = QLineEdit()
        self.olur_ad.setPlaceholderText("Oluru verecek: Ad SOYAD")
        self.olur_unvan = QLineEdit()
        self.olur_unvan.setPlaceholderText("ör. Rektör")
        fo.addRow("Olur makamı", self.olur_ad)
        fo.addRow("Unvan", self.olur_unvan)
        v.addWidget(self.olur_kutusu)
        self.arastir = QCheckBox("Mevzuat dayanağını araştır (danışma hattı)")
        self.arastir.setChecked(True)
        v.addWidget(self.arastir)

        self.hazirla_dugme = QPushButton("  Taslağı hazırla")
        self.hazirla_dugme.setObjectName("Birincil")
        self.hazirla_dugme.setIcon(ikon("yazi", "#FFFFFF", 16))
        self.hazirla_dugme.clicked.connect(self.hazirla)
        v.addWidget(self.hazirla_dugme)
        self.cubuk = QProgressBar()
        self.cubuk.setRange(0, 6)
        self.cubuk.setTextVisible(False)
        self.cubuk.hide()
        v.addWidget(self.cubuk)
        self.durum = QLabel()
        self.durum.setWordWrap(True)
        self.durum.setObjectName("Ikincil")
        v.addWidget(self.durum)
        v.addStretch(1)
        kay.setWidget(ic)
        return kay

    # ------------------------------------------------------------------ sonuç
    def _sonuc_kur(self) -> QWidget:
        kap = QFrame()
        kap.setObjectName("Kart")
        v = QVBoxLayout(kap)
        v.setContentsMargins(14, 10, 14, 12)
        self.ozet = QLabel("Taslak burada görünecek.")
        self.ozet.setWordWrap(True)
        self.ozet.setTextFormat(Qt.RichText)
        v.addWidget(self.ozet)
        self.sekmeler = QTabWidget()
        self.onizleme = QTextBrowser()
        self.onizleme.setStyleSheet("background:white; padding:18px;")
        self.sekmeler.addTab(self.onizleme, "Önizleme")
        duzen = QWidget()
        dv = QVBoxLayout(duzen)
        fk = QFormLayout()
        self.konu = QLineEdit()
        fk.addRow("Konu", self.konu)
        dv.addLayout(fk)
        self.metin_duzen = QPlainTextEdit()
        self.metin_duzen.setObjectName("Duz")
        self.metin_duzen.setPlaceholderText("Paragrafları boş satırla ayırın.")
        dv.addWidget(self.metin_duzen, 1)
        yd = QPushButton("  Yeniden denetle")
        yd.setIcon(ikon("kontrol", R["metin"], 16))
        yd.clicked.connect(self.yeniden_denetle)
        dv.addWidget(yd, 0, Qt.AlignLeft)
        self.sekmeler.addTab(duzen, "Metni düzenle")
        self.ebys = QPlainTextEdit()
        self.ebys.setObjectName("Duz")
        self.ebys.setReadOnly(True)
        self.sekmeler.addTab(self.ebys, "EBYS metni")
        self.kontrol_tablosu = QTableWidget(0, 4)
        self.kontrol_tablosu.setHorizontalHeaderLabels(["Durum", "Dayanak", "Başlık", "Açıklama"])
        self.kontrol_tablosu.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.kontrol_tablosu.verticalHeader().setVisible(False)
        self.kontrol_tablosu.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.kontrol_tablosu.setWordWrap(True)
        self.kontrol_tablosu.setToolTip("Bir maddeye çift tıklayın: Yönetmeliğin o maddesinin metni gösterilir")
        self.kontrol_tablosu.cellDoubleClicked.connect(self._madde_goster)
        self.sekmeler.addTab(self.kontrol_tablosu, "Kontrol listesi")
        self.dusunce = QTextBrowser()
        self.dusunce.setOpenExternalLinks(True)
        self.sekmeler.addTab(self.dusunce, "Nasıl düşündüm")
        v.addWidget(self.sekmeler, 1)
        alt = QHBoxLayout()
        self.kaydet_dugme = QPushButton("  Word olarak kaydet")
        self.kaydet_dugme.setObjectName("Birincil")
        self.kaydet_dugme.setIcon(ikon("indir", "#FFFFFF", 16))
        self.kaydet_dugme.clicked.connect(self.word_kaydet)
        kop = QPushButton("  EBYS metnini kopyala")
        kop.setIcon(ikon("kopyala", R["metin"], 16))
        kop.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.ebys.toPlainText()))
        kop2 = QPushButton("Yalnız metni kopyala")
        kop2.clicked.connect(self._metni_kopyala)
        for d in (self.kaydet_dugme, kop, kop2):
            d.setEnabled(False)
            alt.addWidget(d)
        self._sonuc_dugmeleri = (self.kaydet_dugme, kop, kop2)
        alt.addStretch(1)
        v.addLayout(alt)
        return kap

    # ------------------------------------------------------------------ eylemler
    def profil(self) -> dict:
        p = dict(self.s.ayarlar.al("yazi.profil", {}) or {})
        if not p.get("idare"):
            p["idare"] = "TOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ"
        if not p.get("birim"):
            p["birim"] = self.s.ayarlar.al("profil.birim", "")
        return p

    def profil_duzenle(self) -> None:
        d = ProfilPenceresi(self.profil(), self)
        if d.exec() == QDialog.Accepted:
            self.s.ayarlar.ayarla("yazi.profil", d.profil())
            self.s.ayarlar.kaydet()
            if self.sonuc:
                from ..yazi.hazirlayici import profil_uygula
                profil_uygula(self.sonuc.yazi, d.profil())
                self._goster()

    def _tur_degisti(self) -> None:
        self.olur_kutusu.setVisible(self.tur.currentData() == "olur")

    def dosyadan_ac(self) -> None:
        yol, _ = QFileDialog.getOpenFileName(self, "Gelen yazıyı aç", "",
                                             "Yazılar (*.docx *.pdf *.png *.jpg *.jpeg *.bmp *.txt)")
        if not yol:
            return
        uzanti = Path(yol).suffix.lower()
        if uzanti in (".png", ".jpg", ".jpeg", ".bmp"):
            from PySide6.QtGui import QImage

            from .bilesenler import qimage_to_numpy
            from .calisanlar import OcrCalisani
            self.durum.setText("Görüntüden metin okunuyor…")
            self._ocr = OcrCalisani(self.s.ocr, qimage_to_numpy(QImage(yol)), 2, parent=self)
            self._ocr.bitti.connect(lambda sonuc: self.gelen_metin_al(sonuc.metin()))
            self._ocr.hata.connect(lambda h: self.durum.setText("Görüntü okunamadı: " + h[-200:]))
            self._ocr.start()
            return
        if uzanti == ".txt":
            metin = Path(yol).read_text("utf-8", errors="replace")
        else:
            from ..crawler.depo import metin_cikar
            metin = metin_cikar(Path(yol).read_bytes())
        if not metin.strip():
            self.durum.setText("Dosyadan metin çıkarılamadı (taranmış PDF ise sayfanın görüntüsünü açın).")
            return
        self.gelen_metin_al(metin)

    def gelen_metin_al(self, metin: str) -> None:
        self.gelen_metin.setPlainText(metin)
        self.tur.setCurrentIndex(max(0, self.tur.findData("cevap")))
        self.gelen_cozumle()

    def gelen_cozumle(self) -> GelenYazi | None:
        metin = self.gelen_metin.toPlainText().strip()
        if not metin:
            self.gelen, _ = None, self.gelen_ozet.hide()
            return None
        self.gelen = cozumle(metin)
        ozet = self.gelen.ozet() or "Başlık, sayı, tarih ve konu bulunamadı; metin olduğu gibi kullanılacak."
        self.gelen_ozet.setText(html.escape(ozet).replace("\n", "<br>"))
        self.gelen_ozet.show()
        if self.gelen.ivedilik == "GÜNLÜDÜR" and self.gelen.sure:
            self.durum.setText(f"Gelen yazı GÜNLÜDÜR: cevap süresi {self.gelen.sure}.")
        return self.gelen

    def metin_al(self, metin: str) -> None:
        """Hızlı Yakala ya da belge penceresinden gelen metin: gelen yazı kabul edilir."""
        self.gelen_metin_al(metin)

    def cevaptan(self, cevap) -> None:
        """Danışma cevabı → yazı: doğrulanmış cevap dayanak olur, soru talimata gelir."""
        self.dayanak_cevabi = cevap
        self.tur.setCurrentIndex(max(0, self.tur.findData("gorus")))
        if not self.talimat.toPlainText().strip():
            self.talimat.setPlainText(cevap.soru)
        etiketler = ", ".join(k.etiket for k in cevap.kaynaklar[:4]) or "kaynak yok"
        self.dayanak_etiketi.setText(f"Dayanak: danışma cevabı ({cevap.durum.value}) — {etiketler}. "
                                     "Yalnızca doğrulanmış cümleleri yazıya taşınır.")
        self.dayanak_etiketi.show()

    def _satirlar(self, w: QPlainTextEdit) -> list[str]:
        return [x.strip() for x in w.toPlainText().splitlines() if x.strip()]

    def hazirla(self) -> None:
        if self.calisan and self.calisan.isRunning():
            return
        gelen = self.gelen_cozumle()
        olur = None
        if self.tur.currentData() == "olur" and self.olur_ad.text().strip():
            parca = self.olur_ad.text().split()
            olur = Imza(" ".join(parca[:-1]), parca[-1] if len(parca) > 1 else "", self.olur_unvan.text().strip())
        istek = YaziIstegi(
            tur=self.tur.currentData(), talimat=self.talimat.toPlainText(), gelen=gelen,
            muhatap=self.muhatap.text(), muhatap_birim=self.muhatap_birim.text(), makam=self.makam.currentData(),
            kisiye=self.muhatap.text().strip().lower().startswith("sayın"), dagitimli=self.dagitimli.isChecked(),
            gereği=self._satirlar(self.gerek) if self.dagitimli.isChecked() else [],
            bilgi=self._satirlar(self.bilgi) if self.dagitimli.isChecked() else [],
            ekler=self._satirlar(self.ekler), ivedilik=self.ivedilik.currentText(), cevap_suresi=self.sure.text().strip(),
            olur=olur, profil=self.profil(), dayanak_cevabi=self.dayanak_cevabi, arastir=self.arastir.isChecked())
        self.hazirla_dugme.setEnabled(False)
        self.cubuk.setValue(0)
        self.cubuk.show()
        self.durum.setText("Hazırlanıyor…")
        self.calisan = YaziCalisani(self.hazirlayici, istek, self)
        self.calisan.ilerleme.connect(lambda a, _t, m: (self.cubuk.setValue(a), self.durum.setText(m)))
        self.calisan.bitti.connect(self._bitti)
        self.calisan.hata.connect(self._hata)
        self.calisan.start()

    def _bitti(self, sonuc: YaziSonucu) -> None:
        self.sonuc = sonuc
        self.hazirla_dugme.setEnabled(True)
        self.cubuk.hide()
        y = sonuc.yazi
        if not self.muhatap.text().strip() and y.muhatap:
            self.muhatap.setText(y.muhatap)
        self.durum.setText(f"Taslak {sonuc.sure_sn:.0f} sn'de hazırlandı" + (" (dil modeliyle)." if sonuc.model_kullanildi
                                                                           else " (şablonla; dil modeli yok)."))
        self._goster()
        self.sekmeler.setCurrentIndex(0)

    def _hata(self, metin: str) -> None:
        self.hazirla_dugme.setEnabled(True)
        self.cubuk.hide()
        self.durum.setText("Taslak hazırlanamadı. Ayrıntı: " + metin[-300:])

    def _goster(self) -> None:
        s = self.sonuc
        if s is None:
            return
        y = s.yazi
        self.onizleme.setHtml(html_onizleme(y))
        self.ebys.setPlainText(ebys_metni(y))
        self.konu.setText(y.konu)
        self.metin_duzen.setPlainText("\n\n".join(p.metin for p in y.paragraflar))
        self.kontrol_tablosu.setRowCount(len(s.kontrol))
        for i, k in enumerate(s.kontrol):
            durum = QTableWidgetItem(DURUM_AD.get(k.durum, k.durum))
            from PySide6.QtGui import QColor
            durum.setForeground(QColor(DURUM_RENK.get(k.durum, R["metin"])))
            self.kontrol_tablosu.setItem(i, 0, durum)
            for j, metin in enumerate((k.madde, k.baslik, k.mesaj), 1):
                self.kontrol_tablosu.setItem(i, j, QTableWidgetItem(metin))
        self.kontrol_tablosu.resizeRowsToContents()
        hata = s.hata_sayisi
        uyari = sum(1 for k in s.kontrol if k.durum == "uyari")
        renk = R["kirmizi"] if hata else R["sari"] if uyari else R["yesil"]
        eksik = ("<br>Tamamlanacak: " + "; ".join(html.escape(e) for e in y.eksikler[:5])) if y.eksikler else ""
        self.ozet.setText(f"<span style='color:{renk}; font-weight:700;'>"
                          f"{'Hata var: ' + str(hata) if hata else 'Hata yok'} · {uyari} uyarı</span> — "
                          f"{html.escape(YAZI_TURLERI[y.tur]['ad'])}, muhatap: {html.escape(y.muhatap or 'DAĞITIM YERLERİNE')}"
                          + eksik + ("<br><span style='color:#7A7F99;'>Hatalar giderilmeden taslak EBYS'ye "
                                     "aktarılmamalı (Kontrol listesi sekmesi).</span>" if hata else ""))
        satirlar = ["<b>Nasıl düşündüm</b>"] + [html.escape(d) for d in s.dusunce]
        if y.dayanaklar:
            satirlar.append("<br><b>Dayanaklar</b>")
            for d in y.dayanaklar:
                bag = f" <a href='{html.escape(d['url'])}'>kaynağa git</a>" if d.get("url") else ""
                satirlar.append(f"[{html.escape(d['kid'].lstrip('K'))}] {html.escape(d['etiket'])}{bag}")
        if s.cikarilanlar:
            satirlar.append("<br><b>Sınamada çıkarılan cümleler</b> (kaynakta karşılığı yok; doğruysa talimata yazıp "
                            "yeniden hazırlayın)")
            satirlar += [f"<span style='color:{R['kirmizi']};'>✕</span> {html.escape(c['metin'])} — "
                         f"<i>{html.escape(c['neden'])}</i>" for c in s.cikarilanlar]
        if s.duzeltmeler:
            satirlar.append("<br><b>Biçim düzeltmeleri</b>")
            satirlar += [html.escape(d) for d in s.duzeltmeler]
        self.dusunce.setHtml("<br>".join(satirlar))
        for d in self._sonuc_dugmeleri:
            d.setEnabled(True)

    def yeniden_denetle(self) -> None:
        """Elle düzenlenen metni yeniden biçimlendirir ve sınar."""
        if self.sonuc is None:
            return
        y = self.sonuc.yazi
        y.konu = self.konu.text()
        eski = {p.metin: p for p in y.paragraflar}
        yeni = []
        for parca in [x.strip() for x in self.metin_duzen.toPlainText().split("\n\n") if x.strip()]:
            parca = " ".join(parca.split())
            onceki = eski.get(parca)
            yeni.append(onceki if onceki else Paragraf(parca, tur="metin"))
        if yeni:
            yeni[-1].tur = "bitis" if yeni[-1].tur == "bitis" or "ederim" in yeni[-1].metin else yeni[-1].tur
        y.paragraflar = yeni
        kaynaklar = list(self.sonuc.kaynak_metinler)
        talimat = self.talimat.toPlainText()
        if talimat and talimat not in kaynaklar:
            kaynaklar.append(talimat)
        # Kullanıcının elle yazdığı ya da değiştirdiği paragraf onun beyanıdır (kaynağı kullanıcıdır);
        # programın yazdığı ve değişmeden kalan paragraflar sınanmaya devam eder.
        elle = [p.metin for p in yeni if p.metin not in eski]
        kaynaklar += elle
        self.sonuc.duzeltmeler = duzelt(y)
        self.sonuc.kontrol = kontrol_et(y, kaynaklar)
        if elle:
            from ..yazi.kontrol import KontrolSonucu
            self.sonuc.kontrol.append(KontrolSonucu("İlke: Doğruluk", "Elle düzenleme", "bilgi",
                                                    f"Elle yazılan/değiştirilen {len(elle)} paragraf kullanıcı beyanı "
                                                    "olarak kabul edildi; içindeki bilgiler sizin sorumluluğunuzdadır"))
        self._goster()
        self.sekmeler.setCurrentIndex(3)

    def _madde_goster(self, satir: int, _sutun: int = 0) -> None:
        """Kontrol listesindeki dayanağın (md. N) Yönetmelik metnini kütüphaneden gösterir."""
        import re

        from ..crawler.kaynaklar import RESMI_YAZISMA_KIMLIGI
        oge = self.kontrol_tablosu.item(satir, 1)
        m = re.search(r"md\.\s*(\d+)", oge.text() if oge else "")
        if not m:
            return
        madde = self.s.kutuphane.madde_getir(RESMI_YAZISMA_KIMLIGI, m.group(1))
        if madde is None:
            QMessageBox.information(self, "Resmî Yazışma Yönetmeliği",
                                    f"Yönetmeliğin {m.group(1)}. maddesi kütüphanede henüz yok. Program mevzuatı "
                                    "güncellediğinde (ya da çekirdek bilgi paketiyle) burada görüntülenir.")
            return
        d = QDialog(self)
        d.setWindowTitle(f"Resmî Yazışma Yönetmeliği — Madde {m.group(1)}")
        d.resize(640, 480)
        v = QVBoxLayout(d)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        kaynak = (f"<p style='color:#7A7F99;'>Kaynak: <a href='{html.escape(madde.kaynak_url)}'>"
                  f"{html.escape(madde.belge_baslik)}</a></p>") if madde.kaynak_url else ""
        tb.setHtml(f"<h3>Madde {html.escape(madde.madde_no)}"
                   + (f" — {html.escape(madde.baslik)}" if madde.baslik else "") + "</h3>"
                   + "<p>" + html.escape(madde.metin).replace("\n", "<br>") + "</p>" + kaynak)
        v.addWidget(tb)
        b = QDialogButtonBox(QDialogButtonBox.Close)
        b.rejected.connect(d.reject)
        v.addWidget(b)
        d.exec()

    def word_kaydet(self) -> None:
        if self.sonuc is None:
            return
        if self.sonuc.hata_sayisi and QMessageBox.question(
                self, "Resmî yazı", f"Kontrol listesinde {self.sonuc.hata_sayisi} hata var. Yine de TASLAK olarak "
                                    "kaydedilsin mi?") != QMessageBox.Yes:
            return
        from ..yazi.dil import konu_bicimi
        ad = (konu_bicimi(self.sonuc.yazi.konu) or "Resmi yazi taslagi")[:60].replace("/", "-")
        varsayilan = str(Path(self.s.yollar.kok) / "Taslaklar" / f"{ad} - TASLAK.docx")
        yol, _ = QFileDialog.getSaveFileName(self, "Word taslağını kaydet", varsayilan, "Word (*.docx)")
        if not yol:
            return
        try:
            docx_kaydet(self.sonuc.yazi, yol)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Resmî yazı", f"Kaydedilemedi: {e}")
            return
        self.durum.setText(f"Kaydedildi: {yol}")
        from .sayfalar import klasorde_goster
        klasorde_goster(yol)

    def _metni_kopyala(self) -> None:
        if self.sonuc:
            QGuiApplication.clipboard().setText("\n".join(p.metin for p in self.sonuc.yazi.paragraflar))
