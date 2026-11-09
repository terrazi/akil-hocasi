"""Danışma ekranı: programın ana ekseni. Sohbet + cevap kartları + kaynak paneli."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ..answer.modeller import Cevap
from ..cekirdek.muhakeme import SohbetBaglami
from .bilesenler import OtomatikMetin, SegmentSecici, _alfali, golge, ikon_dugme
from .calisanlar import CevapCalisani
from .cevap_karti import CevapKarti
from .ikonlar import ikon, logo_pixmap
from .kaynak_paneli import KaynakPaneli
from .tema import R

ICERIK_GENISLIGI = 880

ONERILER = [
    ("Personel", "personel", "kisi", "Akademisyenin 10 günlük yurt içi görevlendirmesinde hangi form ve kimin oluru gerekir?"),
    ("Maaş", "maas", "para", "Ay ortasında naklen gelen personelin kıst maaşı nasıl hesaplanır?"),
    ("Harcırah", "harcirah", "yol", "Yurt içi geçici görev yolluğunda ödeme emrine hangi belgeler eklenir?"),
    ("Satın alma", "satinalma", "sepet", "Doğrudan teminde yaklaşık maliyet cetveli hazırlamak zorunlu mu?"),
    ("Yazışma", "yazisma", "zarf", "Yurt dışına gidecek resmî yazıyı kim imzalar, ıslak imza gerekir mi?"),
    ("Taşınır", "tasinir", "kutu", "Birimler arası taşınır devrinde hangi belge düzenlenir?"),
]


def _ortala(w: QWidget, genislik: int = ICERIK_GENISLIGI) -> QWidget:
    """İçeriği en fazla 'genislik' piksel genişlikte ortalar."""
    kap = QWidget()
    yer = QHBoxLayout(kap)
    yer.setContentsMargins(0, 0, 0, 0)
    yer.addStretch(1)
    w.setMaximumWidth(genislik)
    w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    yer.addWidget(w, 100)
    yer.addStretch(1)
    return kap


class OneriKarti(QPushButton):
    def __init__(self, kategori: str, renk_ad: str, ikon_ad: str, soru: str, parent=None):
        super().__init__(parent)
        self.soru = soru
        self.setObjectName("OneriKarti")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(108)
        renk = R[renk_ad]
        yer = QVBoxLayout(self)
        yer.setContentsMargins(16, 14, 16, 14)
        yer.setSpacing(8)
        ust = QHBoxLayout()
        simge = QLabel()
        simge.setFixedSize(34, 34)
        simge.setAlignment(Qt.AlignCenter)
        simge.setPixmap(ikon(ikon_ad, renk, 18, 2.0).pixmap(18, 18))
        simge.setStyleSheet(f"background:{_alfali(renk, 0.13)}; border-radius:10px;")
        ust.addWidget(simge)
        kat = QLabel(kategori)
        kat.setStyleSheet(f"color:{renk}; font-weight:700; font-size:12.5px; background:transparent;")
        ust.addWidget(kat)
        ust.addStretch(1)
        yer.addLayout(ust)
        metin = QLabel(soru)
        metin.setWordWrap(True)
        metin.setStyleSheet(f"font-size:13px; color:{R['metin']}; background:transparent;")
        metin.setAttribute(Qt.WA_TransparentForMouseEvents)
        simge.setAttribute(Qt.WA_TransparentForMouseEvents)
        kat.setAttribute(Qt.WA_TransparentForMouseEvents)
        yer.addWidget(metin)


class KarsilamaEkrani(QWidget):
    soru_secildi = Signal(str)
    guncelle_istendi = Signal()

    def __init__(self, ad: str = "", kutuphane_bos: bool = False, parent=None):
        super().__init__(parent)
        yer = QVBoxLayout(self)
        yer.setContentsMargins(0, 36, 0, 12)
        yer.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(56))
        yer.addWidget(logo, 0, Qt.AlignHCenter)
        selam = QLabel(f"Merhaba{', ' + ad if ad else ''}! "
                       f"<span style='color:{R['ana']};'>Bugün neye bakalım?</span>")
        selam.setObjectName("Selam")
        selam.setAlignment(Qt.AlignCenter)
        yer.addWidget(selam)
        alt = QLabel("Mevzuata dayanan, kaynağını gösteren cevaplar. Sorunuzu yazın, ekran görüntüsü "
                     "yapıştırın ya da belge ekleyin.")
        alt.setObjectName("AltSelam")
        alt.setAlignment(Qt.AlignCenter)
        alt.setWordWrap(True)
        yer.addWidget(alt)
        if kutuphane_bos:
            uyari = QFrame()
            uyari.setStyleSheet(f"background:{R['sari_zemin']}; border-radius:12px;")
            u = QHBoxLayout(uyari)
            u.setContentsMargins(14, 10, 10, 10)
            lbl = QLabel("Kütüphane henüz boş. İlk güncelleme resmî kaynaklardan mevzuatı ve TOGÜ belgelerini indirecek.")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color:{R['sari']}; font-weight:600; background:transparent;")
            u.addWidget(lbl, 1)
            d = QPushButton("Şimdi güncelle")
            d.setObjectName("Birincil")
            d.clicked.connect(self.guncelle_istendi.emit)
            u.addWidget(d)
            yer.addSpacing(6)
            yer.addWidget(uyari)
        yer.addSpacing(18)
        izgara = QGridLayout()
        izgara.setSpacing(12)
        for i, (kat, renk, ik, soru) in enumerate(ONERILER):
            kart = OneriKarti(kat, renk, ik, soru)
            kart.clicked.connect(lambda _=False, s=soru: self.soru_secildi.emit(s))
            izgara.addWidget(kart, i // 3, i % 3)
        yer.addLayout(izgara)
        yer.addStretch(1)


class KullaniciBalonu(QWidget):
    def __init__(self, metin: str, parent=None):
        super().__init__(parent)
        yer = QHBoxLayout(self)
        yer.setContentsMargins(80, 0, 0, 0)
        yer.addStretch(1)
        balon = QFrame()
        balon.setObjectName("KullaniciBalonu")
        b = QVBoxLayout(balon)
        b.setContentsMargins(16, 11, 16, 11)
        lbl = QLabel(metin)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        b.addWidget(lbl)
        balon.setMaximumWidth(620)
        yer.addWidget(balon)


class IlerlemeKarti(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Kart")
        yer = QVBoxLayout(self)
        yer.setContentsMargins(18, 14, 18, 14)
        yer.setSpacing(8)
        ust = QHBoxLayout()
        self.baslik = QLabel("Araştırılıyor")
        self.baslik.setStyleSheet(f"font-weight:700; color:{R['ana']};")
        ust.addWidget(self.baslik)
        ust.addStretch(1)
        self.sayac = QLabel("0/7")
        self.sayac.setObjectName("Soluk")
        ust.addWidget(self.sayac)
        yer.addLayout(ust)
        self.mesaj = QLabel("Başlıyor…")
        self.mesaj.setObjectName("Ikincil")
        yer.addWidget(self.mesaj)
        self.cubuk = QProgressBar()
        self.cubuk.setRange(0, 7)
        self.cubuk.setTextVisible(False)
        yer.addWidget(self.cubuk)
        self._nokta = 0
        self._zaman = QTimer(self)
        self._zaman.timeout.connect(self._canlandir)
        self._zaman.start(400)

    def _canlandir(self) -> None:
        self._nokta = (self._nokta + 1) % 4
        self.baslik.setText("Araştırılıyor" + "." * self._nokta)

    def guncelle(self, adim: int, toplam: int, mesaj: str) -> None:
        self.cubuk.setMaximum(toplam)
        self.cubuk.setValue(adim)
        self.sayac.setText(f"{adim}/{toplam}")
        self.mesaj.setText(mesaj)


class Besteci(QFrame):
    gonder = Signal(str, str)              # soru, mod
    hizli_yakala = Signal()
    yeni_konu = Signal()
    goruntu = Signal(QImage)
    belge = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Besteci")
        golge(self, 34, 8, 30)
        yer = QVBoxLayout(self)
        yer.setContentsMargins(16, 12, 12, 10)
        yer.setSpacing(6)
        self.giris = OtomatikMetin()
        self.giris.setPlaceholderText("Sorunuzu yazın… ör. \"Aylıksız izin dönüşü kıst maaş nasıl hesaplanır?\"")
        self.giris.gonder.connect(self._gonder)
        self.giris.goruntu_yapistirildi.connect(self.goruntu.emit)
        yer.addWidget(self.giris)
        alt = QHBoxLayout()
        alt.setSpacing(4)
        ek = ikon_dugme(ikon("ek", R["metin2"]), "Belge veya görüntü ekle (JPG, PNG, PDF, Word)")
        ek.clicked.connect(self._belge_sec)
        alt.addWidget(ek)
        yakala = ikon_dugme(ikon("yakala", R["metin2"]), "Hızlı Yakala: ekrandan metin al")
        yakala.clicked.connect(self.hizli_yakala.emit)
        alt.addWidget(yakala)
        alt.addSpacing(6)
        self.mod = SegmentSecici([("hizli", "Hızlı"), ("derin", "Derin araştırma")], "derin")
        self.mod.setToolTip("Derin araştırma: atıf zinciri, canlı resmî arama ve emsaller dahil yedi basamak")
        alt.addWidget(self.mod)
        self.yeni_konu_dugme = QPushButton("Yeni konu")
        self.yeni_konu_dugme.setObjectName("Hayalet")
        self.yeni_konu_dugme.setIcon(ikon("arti", R["metin2"], 16))
        self.yeni_konu_dugme.setToolTip("Konuşmayı yeni konu olarak başlat: önceki sorular yeni cevabı etkilemez")
        self.yeni_konu_dugme.setCursor(Qt.PointingHandCursor)
        self.yeni_konu_dugme.clicked.connect(self.yeni_konu.emit)
        self.yeni_konu_dugme.hide()
        alt.addWidget(self.yeni_konu_dugme)
        alt.addStretch(1)
        ipucu = QLabel("Enter gönderir · Shift+Enter yeni satır · Ctrl+V ile görüntü yapıştırın")
        ipucu.setObjectName("Soluk")
        alt.addWidget(ipucu)
        alt.addSpacing(8)
        self.gonder_dugme = QPushButton()
        self.gonder_dugme.setObjectName("Gonder")
        self.gonder_dugme.setIcon(ikon("gonder", "#FFFFFF", 20, 2.4))
        self.gonder_dugme.setIconSize(QSize(20, 20))
        self.gonder_dugme.setCursor(Qt.PointingHandCursor)
        self.gonder_dugme.setToolTip("Gönder")
        self.gonder_dugme.clicked.connect(self._gonder)
        alt.addWidget(self.gonder_dugme)
        yer.addLayout(alt)

    def _gonder(self) -> None:
        metin = self.giris.toPlainText().strip()
        if metin and self.gonder_dugme.isEnabled():
            self.giris.clear()
            self.gonder.emit(metin, self.mod.secili)

    def _belge_sec(self) -> None:
        yol, _ = QFileDialog.getOpenFileName(self, "Belge veya görüntü seç", "",
                                             "Desteklenen dosyalar (*.png *.jpg *.jpeg *.bmp *.pdf *.docx)")
        if yol:
            self.belge.emit(yol)

    def mesgul(self, durum: bool) -> None:
        self.gonder_dugme.setEnabled(not durum)


class DanismaSayfasi(QWidget):
    hizli_yakala_istendi = Signal()
    goruntu_geldi = Signal(QImage)
    belge_geldi = Signal(str)
    yaziya_gonder = Signal(object)
    belge_ac = Signal(object)
    geri_bildirim = Signal(object)
    guncelle_istendi = Signal()
    cevap_hazir = Signal(object)
    faydali = Signal(object)
    kaynak_tiklandi = Signal(object, str)

    def __init__(self, hat, profil_adi: str = "", kutuphane_bos: bool = False, parent=None):
        super().__init__(parent)
        self.hat = hat
        self.calisan: CevapCalisani | None = None
        self.ilerleme_karti: IlerlemeKarti | None = None
        self.son_cevap: Cevap | None = None
        self.baglam = SohbetBaglami()          # aynı konuşmadaki önceki turlar: devam soruları doğru anlaşılır

        yatay = QHBoxLayout(self)
        yatay.setContentsMargins(0, 0, 0, 0)
        yatay.setSpacing(0)

        orta = QWidget()
        dikey = QVBoxLayout(orta)
        dikey.setContentsMargins(24, 0, 24, 18)
        dikey.setSpacing(12)

        self.kaydirma = QScrollArea()
        self.kaydirma.setWidgetResizable(True)
        self.kaydirma.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        akis_kap = QWidget()
        self.akis = QVBoxLayout(akis_kap)
        self.akis.setContentsMargins(0, 12, 0, 12)
        self.akis.setSpacing(16)
        self.karsilama = KarsilamaEkrani(profil_adi, kutuphane_bos)
        self.karsilama.soru_secildi.connect(lambda s: self.sor(s, "derin"))
        self.karsilama.guncelle_istendi.connect(self.guncelle_istendi.emit)
        self.akis.addWidget(_ortala(self.karsilama))
        self.akis.addStretch(1)
        self.kaydirma.setWidget(akis_kap)
        self.kaydirma.verticalScrollBar().rangeChanged.connect(self._asagi_kaydir)
        dikey.addWidget(self.kaydirma, 1)

        self.besteci = Besteci()
        self.besteci.gonder.connect(self.sor)
        self.besteci.hizli_yakala.connect(self.hizli_yakala_istendi.emit)
        self.besteci.goruntu.connect(self.goruntu_geldi.emit)
        self.besteci.belge.connect(self.belge_geldi.emit)
        self.besteci.yeni_konu.connect(self.yeni_konu)
        dikey.addWidget(_ortala(self.besteci))
        yatay.addWidget(orta, 1)

        self.panel = KaynakPaneli()
        self.panel.kapat_istendi.connect(lambda: self.panel.setVisible(False))
        self.panel.setVisible(False)
        yatay.addWidget(self.panel)
        self._kaydir_bekliyor = False

    # ------------------------------------------------------------------ akış
    def _ekle(self, w: QWidget) -> None:
        self.akis.insertWidget(self.akis.count() - 1, _ortala(w))
        self._kaydir_bekliyor = True

    def _asagi_kaydir(self, _min: int, en_cok: int) -> None:
        if self._kaydir_bekliyor:
            self.kaydirma.verticalScrollBar().setValue(en_cok)
            self._kaydir_bekliyor = False

    def sor(self, soru: str, mod: str = "derin") -> None:
        if self.calisan and self.calisan.isRunning():
            return
        if self.karsilama.isVisible():
            self.karsilama.parentWidget().setVisible(False)
        self._ekle(KullaniciBalonu(soru))
        self.ilerleme_karti = IlerlemeKarti()
        self._ekle(self.ilerleme_karti)
        self.besteci.mesgul(True)
        self.calisan = CevapCalisani(self.hat, soru, mod, self, baglam=SohbetBaglami(list(self.baglam.turlar)))
        self.calisan.ilerleme.connect(self.ilerleme_karti.guncelle)
        self.calisan.bitti.connect(self._cevap_geldi)
        self.calisan.hata.connect(self._hata)
        self.calisan.start()

    def soruyu_doldur(self, metin: str) -> None:
        self.besteci.giris.setPlainText(metin)
        self.besteci.giris.setFocus()
        imlec = self.besteci.giris.textCursor()
        imlec.movePosition(imlec.MoveOperation.End)
        self.besteci.giris.setTextCursor(imlec)

    def yeni_konu(self) -> None:
        self.baglam = SohbetBaglami()
        self.besteci.yeni_konu_dugme.hide()
        cizgi = QLabel("— Yeni konu —")
        cizgi.setAlignment(Qt.AlignCenter)
        cizgi.setObjectName("Soluk")
        self._ekle(cizgi)

    def _netlestir(self, cevap: Cevap, soru: str) -> None:
        """Netleştirme sorusuna tıklandı: önceki soru + ek bilgi alanı besteciye gelir, kullanıcı yalnız cevabı yazar."""
        self.soruyu_doldur(f"{cevap.soru}\nEk bilgi — {soru} ")

    def _ilerlemeyi_kaldir(self) -> None:
        if self.ilerleme_karti:
            kap = self.ilerleme_karti.parentWidget()
            kap.setVisible(False)
            kap.deleteLater()
            self.ilerleme_karti = None

    def _cevap_geldi(self, cevap: Cevap) -> None:
        self._ilerlemeyi_kaldir()
        self.son_cevap = cevap
        kart = CevapKarti(cevap)
        kart.kaynak_secildi.connect(lambda kid, c=cevap: self._kaynak_goster(c, kid))
        kart.netlestir.connect(lambda q, c=cevap: self._netlestir(c, q))
        kart.belge_acildi.connect(self.belge_ac.emit)
        kart.yaziya_donustur.connect(self.yaziya_gonder.emit)
        kart.geri_bildirim.connect(self.geri_bildirim.emit)
        kart.faydali.connect(self.faydali.emit)
        self._ekle(kart)
        self.besteci.mesgul(False)
        ozet = " ".join(c.metin for c in (cevap.kisa_cevap or cevap.dikkat)[:3]) or cevap.durum.value
        self.baglam.ekle(cevap.soru, ozet, cevap.cozumleme)
        self.besteci.yeni_konu_dugme.show()
        if cevap.kaynaklar:
            self.panel.goster(cevap)
            self.panel.setVisible(True)
        self.cevap_hazir.emit(cevap)

    def _hata(self, metin: str) -> None:
        self._ilerlemeyi_kaldir()
        kart = QLabel("Cevap hazırlanırken beklenmeyen bir hata oluştu. Ayrıntı günlüğe yazıldı.\n\n" + metin[-400:])
        kart.setWordWrap(True)
        kart.setStyleSheet(f"background:{R['kirmizi_zemin']}; color:{R['kirmizi']}; border-radius:14px; padding:14px;")
        self._ekle(kart)
        self.besteci.mesgul(False)

    def _kaynak_goster(self, cevap: Cevap, kid: str) -> None:
        self.panel.goster(cevap, kid)
        self.panel.setVisible(True)
        if kid:
            self.kaynak_tiklandi.emit(cevap, kid)
