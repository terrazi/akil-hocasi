"""Ana pencere: sol menü şeridi + sayfalar + canlı durum çubuğu + sistem tepsisi + zamanlayıcı."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QIcon, QImage
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QStackedWidget, QSystemTrayIcon, QToolButton,
                               QVBoxLayout, QWidget)

from .. import UYGULAMA_ADI
from ..answer.modeller import Cevap, Durum
from ..crawler.zamanlayici import GOREVLER
from .calisanlar import (AdayModelCalisani, AnlamCalisani, ModelIndirmeCalisani, OgrenmeCalisani, TaramaCalisani,
                         YZBaslatici, ZekaCalisani)
from .danisma import DanismaSayfasi
from .hizli_yakala import CanliMetinPenceresi, YakalamaKatmani
from .ikonlar import ikon, logo_pixmap
from .kisayol import GenelKisayol, bosta_kalma_sn
from .sayfalar import (AyarlarSayfasi, BelgeDeposuSayfasi, KaynakHavuzuSayfasi, NelerDegistiSayfasi,
                       YakindaSayfasi, ZekaSayfasi)
from .tema import R
from .yazi_sayfasi import YaziHazirlamaSayfasi

log = logging.getLogger("akilhocasi")


class TakipCalisani(QThread):
    """Takipteki soruları yeniden arar; cevap bulunanları bildirir."""
    bulundu = Signal(str)

    def __init__(self, hat, kutuphane, parent=None):
        super().__init__(parent)
        self.hat, self.kutuphane = hat, kutuphane

    def run(self) -> None:
        for t in self.kutuphane.takipteki_sorular():
            try:
                c = self.hat.cevapla(t["soru"], "hizli")
            except Exception:
                continue
            if c.durum != Durum.HUKUM_YOK:
                self.kutuphane.takip_guncelle(t["id"], "bulundu")
                self.bulundu.emit(t["soru"])
            else:
                self.kutuphane.takip_guncelle(t["id"])


class BelgeMetniPenceresi(QWidget):
    """PDF/Word belgesinden çıkarılan metni gösterir; seçili metin sorulabilir."""
    sor = Signal(str)
    yaziya = Signal(str)

    def __init__(self, baslik: str, metin: str, parent=None):
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(f"{baslik} — {UYGULAMA_ADI}")
        self.setObjectName("Icerik")
        self.resize(820, 680)
        yer = QVBoxLayout(self)
        yer.setContentsMargins(16, 14, 16, 14)
        b = QLabel(baslik)
        b.setStyleSheet("font-size:17px; font-weight:700;")
        yer.addWidget(b)
        self.metin = QPlainTextEdit(metin)
        self.metin.setObjectName("Duz")
        yer.addWidget(self.metin, 1)
        alt = QHBoxLayout()
        alt.addStretch(1)
        sor = QPushButton("  Seçili metni sor")
        sor.setObjectName("Birincil")
        sor.setIcon(ikon("danisma", "#FFFFFF", 16))
        sor.clicked.connect(lambda: self.sor.emit(self.metin.textCursor().selectedText().replace(" ", "\n")
                                                  or self.metin.toPlainText()[:2000]))
        alt.addWidget(sor)
        yazi = QPushButton("  Yazı Hazırlama'ya gönder")
        yazi.setIcon(ikon("yazi", R["metin"], 16))
        yazi.clicked.connect(lambda: self.yaziya.emit(self.metin.toPlainText()))
        alt.addWidget(yazi)
        yer.addLayout(alt)


class GozlemKoprusu(QObject):
    """Gözlem sunucusunun ve tarama motorunun iş parçacıklarından arayüze güvenli geçiş (kuyruklu sinyal)."""
    geldi = Signal(object)
    motor = Signal(object)


class DurumCubugu(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DurumCubugu")
        self.setFixedHeight(34)
        yer = QHBoxLayout(self)
        yer.setContentsMargins(16, 0, 16, 0)
        yer.setSpacing(18)
        self.nokta = QLabel()
        self.nokta.setFixedSize(10, 10)
        yer.addWidget(self.nokta)
        self.canli = QLabel("Canlı")
        yer.addWidget(self.canli)
        self.kontrol = QLabel()
        self.kutuphane = QLabel()
        self.takip = QLabel()
        self.etkinlik = QLabel()
        for w in (self.kontrol, self.kutuphane, self.takip, self.etkinlik):
            yer.addWidget(w)
        yer.addStretch(1)
        self.gozlem = QLabel()
        self.gozlem.setToolTip("Akıl Hocası Gözlemci eklentisi: tarayıcıda görülen resmî sayfalar")
        yer.addWidget(self.gozlem)
        self.model = QLabel()
        yer.addWidget(self.model)
        self._yanip = False
        self._zaman = QTimer(self)
        self._zaman.timeout.connect(self._nabiz)
        self._zaman.start(900)
        self.calisiyor(False)

    def _nabiz(self) -> None:
        self._yanip = not self._yanip
        renk = R["camgobegi"] if self._calisiyor else R["yesil"]
        alfa = "1.0" if self._yanip else "0.45"
        c = renk.lstrip("#")
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        self.nokta.setStyleSheet(f"background: rgba({r},{g},{b},{alfa}); border-radius:5px;")

    def etkinlik_yaz(self, mesaj: str) -> None:
        self.calisiyor(True, mesaj)

    def calisiyor(self, durum: bool, mesaj: str = "") -> None:
        self._calisiyor = durum
        self.canli.setText("Güncelleniyor" if durum else "Canlı")
        self.etkinlik.setText(mesaj)


class AnaPencere(QMainWindow):
    def __init__(self, s):
        super().__init__()
        self.s = s
        self.setWindowTitle(f"{UYGULAMA_ADI}")
        self.setWindowIcon(QIcon(logo_pixmap(64)))
        self.resize(1360, 880)
        self.setMinimumSize(1080, 700)
        self._cikiliyor = False
        self._tarama: TaramaCalisani | None = None
        self._takip: TakipCalisani | None = None
        self._ogrenme: OgrenmeCalisani | None = None
        self._aday: AdayModelCalisani | None = None
        self._yz_baslatici: YZBaslatici | None = None
        self._indirme: ModelIndirmeCalisani | None = None
        self._anlam_calisani: AnlamCalisani | None = None
        self._zeka: ZekaCalisani | None = None
        self._pencereler: list[QWidget] = []
        self._son_pano_bildirim = 0.0
        self._gozlem_sunucusu = None
        self._gozlem_koprusu = GozlemKoprusu(self)
        self._gozlem_koprusu.geldi.connect(self._gozlem_geldi)
        self._gozlem_koprusu.motor.connect(self._motor_durumu)
        self._havuz_yenileme = QTimer(self)
        self._havuz_yenileme.setSingleShot(True)
        self._havuz_yenileme.timeout.connect(self._havuzu_yenile)
        self._gozlem_sayac: dict[str, int] = {}
        self._zamanlayici_acik = True                # öz test kapatır: arka plan görevleri başlamasın

        kok = QWidget()
        kok.setObjectName("Icerik")
        yatay = QHBoxLayout(kok)
        yatay.setContentsMargins(0, 0, 0, 0)
        yatay.setSpacing(0)
        yatay.addWidget(self._serit_kur())
        sag = QVBoxLayout()
        sag.setContentsMargins(0, 0, 0, 0)
        sag.setSpacing(0)
        self.yigin = QStackedWidget()
        sag.addWidget(self.yigin, 1)
        self.durum = DurumCubugu()
        sag.addWidget(self.durum)
        yatay.addLayout(sag, 1)
        self.setCentralWidget(kok)

        self._sayfalari_kur()
        self._tepsi_kur()
        self._kisayol_kur()
        self._pano_izle()
        self._model_yukle()
        self._gozlem_kur()

        self.zaman = QTimer(self)
        self.zaman.timeout.connect(self._zamanlayici_tik)
        self.zaman.start(60_000)
        QTimer.singleShot(4_000, self._zamanlayici_tik)
        self._durumu_guncelle()

    # ================================================================== kurulum
    def _serit_kur(self) -> QWidget:
        serit = QFrame()
        serit.setObjectName("Serit")
        serit.setFixedWidth(84)
        yer = QVBoxLayout(serit)
        yer.setContentsMargins(10, 16, 10, 14)
        yer.setSpacing(4)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(44))
        logo.setAlignment(Qt.AlignCenter)
        yer.addWidget(logo)
        ad = QLabel("Akıl Hocası")
        ad.setObjectName("Logo")
        ad.setAlignment(Qt.AlignCenter)
        yer.addWidget(ad)
        yer.addSpacing(14)
        self.grup = QButtonGroup(self)
        self.grup.setExclusive(True)
        self.dugmeler: dict[str, QToolButton] = {}

        def dugme(anahtar: str, ikon_ad: str, metin: str, ipucu: str, sayfa: bool = True) -> QToolButton:
            d = QToolButton()
            d.setObjectName("SeritDugme")
            d.setIcon(ikon(ikon_ad, "#FFFFFF", 22, 1.9))
            d.setIconSize(QSize(22, 22))
            d.setText(metin)
            d.setToolTip(ipucu)
            d.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            d.setFixedSize(64, 54)
            d.setCursor(Qt.PointingHandCursor)
            if sayfa:
                d.setCheckable(True)
                self.grup.addButton(d)
            self.dugmeler[anahtar] = d
            return d

        for anahtar, ik, metin, ipucu in (
            ("danisma", "danisma", "Danışma", "Yapay zekâ ile danışma (ana ekran)"),
            ("yakala", "yakala", "Yakala", "Hızlı Yakala: ekrandan metin al"),
            ("yazi", "yazi", "Yazı", "Yazı Hazırlama"),
            ("hesap", "hesap", "Hesapla", "Hesaplama"),
            ("kontrol", "kontrol", "Kontrol", "Ödeme / evrak ön kontrolü"),
            ("depo", "depo", "Depo", "Belge Deposu"),
            ("havuz", "havuz", "Kaynaklar", "Kaynak Havuzu: gömülü tarayıcı ve tarayıcı eklentisi"),
            ("degisti", "degisti", "Değişenler", "Neler değişti"),
            ("zeka", "isik", "Zekâ", "Yapay zekâ ve çekirdek: model, ilkeler, kendini geliştirme"),
        ):
            d = dugme(anahtar, ik, metin, ipucu, sayfa=(anahtar != "yakala"))
            yer.addWidget(d, 0, Qt.AlignHCenter)
        yer.addStretch(1)
        yer.addWidget(dugme("ayarlar", "ayarlar", "Ayarlar", "Ayarlar"), 0, Qt.AlignHCenter)
        self.dugmeler["yakala"].clicked.connect(self.hizli_yakala)
        self.rozet = QLabel(self.dugmeler["degisti"])
        self.rozet.setStyleSheet(f"background:{R['kirmizi']}; color:white; border-radius:8px; font-size:10px;"
                                 "font-weight:700; padding:0 5px;")
        self.rozet.move(40, 4)
        self.rozet.hide()
        return serit

    def _sayfalari_kur(self) -> None:
        s = self.s
        ist = s.kutuphane.istatistik()
        self.danisma = DanismaSayfasi(s.hat, s.ayarlar.al("profil.ad", ""), kutuphane_bos=ist["madde"] == 0)
        self.danisma.hizli_yakala_istendi.connect(self.hizli_yakala)
        self.danisma.goruntu_geldi.connect(self.goruntu_ac)
        self.danisma.belge_geldi.connect(self.belge_ice_aktar)
        self.danisma.yaziya_gonder.connect(self.yaziya_gonder)
        self.danisma.belge_ac.connect(self.belge_ac)
        self.danisma.geri_bildirim.connect(self.geri_bildirim)
        self.danisma.guncelle_istendi.connect(lambda: self.guncelle(["gece", "hafif", "derin"]))
        self.danisma.faydali.connect(self._faydali)
        self.danisma.kaynak_tiklandi.connect(self._kaynak_tiklandi)
        self.yazi = YaziHazirlamaSayfasi(s)
        hesap = YakindaSayfasi("Hesaplama", "Tutarlar dil modeliyle değil, tarihli ve kaynaklı parametrelerle "
                               "kural tabanlı motorla hesaplanır; her satırın dayanağı gösterilir.", "Faz 4",
                               ["Kıst maaş ve maaş farkı", "Yurt içi / yurt dışı harcırah", "Ek ders ve fazla çalışma",
                                "Terfi farkı, aile yardımı, jüri ücreti", "Her parametre: değer, geçerlilik tarihi, kaynak"],
                               R["maas"])
        kontrol = YakindaSayfasi("Ödeme / Evrak Ön Kontrolü", "Ödeme emri ve eklerini MYHBY, TOGÜ ön mali "
                                 "kontrol listeleri ve Sayıştay bulgularına göre denetler.", "Faz 5",
                                 ["Eksik belge listesi", "Tutar ve ekonomik kod biçim kontrolü",
                                  "TC / IBAN sağlama kontrolü", "Olası Sayıştay bulgusu uyarısı"], R["satinalma"])
        self.depo_sayfa = BelgeDeposuSayfasi(s.depo)
        self.depo_sayfa.guncelle_istendi.connect(lambda: self.guncelle(["derin"]))
        self.degisti = NelerDegistiSayfasi(s.kutuphane, s.ogrenme, s.siralayici)
        self.degisti.ogren_istendi.connect(self.ogren)
        self.degisti.soru_tekrar.connect(lambda soru: (self._sayfa("danisma"), self.danisma.sor(soru, "derin")))
        self.ayarlar_sayfa = AyarlarSayfasi(s.ayarlar, s.yollar, self._durum_bilgisi())
        self.ayarlar_sayfa.kaydedildi.connect(self._ayarlar_kaydedildi)
        self.ayarlar_sayfa.guncelle_istendi.connect(lambda: self.guncelle(["hafif", "gece"]))
        self.ayarlar_sayfa.aday_model_istendi.connect(self._aday_model_dene)
        self.havuz = KaynakHavuzuSayfasi(s)
        self.havuz.tara_istendi.connect(self._site_tara)
        self.havuz.durdur_istendi.connect(lambda: s.motor.durdur())
        self.havuz.ayarlar_degisti.connect(self._gozlem_kur)
        s.motor.bildir = self._gozlem_koprusu.motor.emit
        self.zeka = ZekaSayfasi(s)
        self.zeka.kur_istendi.connect(self._model_kur)
        self.zeka.kullan_istendi.connect(self._model_kullan)
        self.zeka.sil_istendi.connect(self._model_sil)
        self.zeka.durdur_istendi.connect(lambda: self._indirme and self._indirme.durdur.set())
        self.zeka.gelistir_istendi.connect(lambda: self.kendini_gelistir(elle=True))
        self.sayfalar = {"danisma": self.danisma, "yazi": self.yazi, "hesap": hesap, "kontrol": kontrol,
                         "depo": self.depo_sayfa, "havuz": self.havuz, "degisti": self.degisti, "zeka": self.zeka,
                         "ayarlar": self.ayarlar_sayfa}
        for anahtar, sayfa in self.sayfalar.items():
            self.yigin.addWidget(sayfa)
            self.dugmeler[anahtar].clicked.connect(lambda _=False, a=anahtar: self._sayfa(a))
        self._sayfa("danisma")

    def _sayfa(self, anahtar: str) -> None:
        self.dugmeler[anahtar].setChecked(True)
        self.yigin.setCurrentWidget(self.sayfalar[anahtar])
        if anahtar == "depo":
            self.depo_sayfa.yenile()
        elif anahtar == "zeka":
            self.zeka.yenile()
        elif anahtar == "degisti":
            self.degisti.yenile()
            self.rozet.hide()

    def _tepsi_kur(self) -> None:
        self.tepsi = QSystemTrayIcon(QIcon(logo_pixmap(32)), self)
        self.tepsi.setToolTip(UYGULAMA_ADI)
        menu = QMenu()
        for metin, fn in (("Aç", self.goster), ("Hızlı Yakala", self.hizli_yakala),
                          ("Şimdi güncelle", lambda: self.guncelle(["hafif", "gece"])), (None, None),
                          ("Çıkış", self.cik)):
            if metin is None:
                menu.addSeparator()
                continue
            a = QAction(metin, self)
            a.triggered.connect(fn)
            menu.addAction(a)
        self.tepsi.setContextMenu(menu)
        self.tepsi.activated.connect(lambda neden: self.goster() if neden == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tepsi.messageClicked.connect(self._bildirim_tiklandi)
        self._bildirim_eylemi = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tepsi.show()

    def _bildirim(self, baslik: str, metin: str, eylem=None) -> None:
        self._bildirim_eylemi = eylem
        if self.tepsi.isVisible():
            self.tepsi.showMessage(baslik, metin, QIcon(logo_pixmap(32)), 6000)

    def _bildirim_tiklandi(self) -> None:
        if self._bildirim_eylemi:
            self._bildirim_eylemi()
        self._bildirim_eylemi = None

    def _kisayol_kur(self) -> None:
        self.kisayol = GenelKisayol()
        self.kisayol.tetiklendi.connect(self.hizli_yakala)
        etkin = self.kisayol.kaydet(self.s.ayarlar.al("kisayol.hizli_yakala", "Win+Shift+Y"),
                                    self.s.ayarlar.al("kisayol.yedek", "Ctrl+Alt+Shift+Y"))
        self.dugmeler["yakala"].setToolTip(f"Hızlı Yakala ({etkin})" if etkin else "Hızlı Yakala")
        log.info("Kısayol: %s", etkin or "kaydedilemedi")

    def _pano_izle(self) -> None:
        QGuiApplication.clipboard().dataChanged.connect(self._pano_degisti)

    def _pano_degisti(self) -> None:
        if not self.s.ayarlar.al("ocr.pano_izleme", True) or self.isActiveWindow():
            return
        veri = QGuiApplication.clipboard().mimeData()
        simdi = datetime.now().timestamp()
        if veri and veri.hasImage() and simdi - self._son_pano_bildirim > 5:
            self._son_pano_bildirim = simdi
            self._bildirim("Panoda ekran görüntüsü var", "Metnini almak için tıklayın.",
                           lambda: self.goruntu_ac(QGuiApplication.clipboard().image()))

    def _model_yukle(self, degistir: str = "") -> None:
        """Seçili yerel modelleri (dil + anlam) arka planda başlatır; zaten çalışanlara dokunmaz."""
        if self._yz_baslatici and self._yz_baslatici.isRunning():
            return
        self.durum.model.setText("Model başlatılıyor…")
        self._yz_baslatici = YZBaslatici(self.s.yz, degistir, self)
        self._yz_baslatici.ilerleme.connect(lambda m: self.durum.model.setText(m[:60]))
        self._yz_baslatici.bitti.connect(self._model_hazir)
        self._yz_baslatici.start()

    def _model_hazir(self, durum: dict) -> None:
        yz = self.s.yz
        self.s.hat.model = yz.model
        self.s.hat.anlam = yz.anlam
        if yz.model.hazir:
            olcum = durum.get("olcum") or {}
            self.durum.model.setText(f"Model: {yz.model.ad}" + (f" · {olcum['sure_sn']} sn" if olcum.get("sure_sn") else ""))
        else:
            self.durum.model.setText("Alıntıya dayalı mod (dil modeli yok)")
        self.zeka.model_durumu_yaz(durum)
        if durum.get("son_hata"):
            log.warning("YZ: %s", durum["son_hata"])
        self._anlam_dizinle()
        QTimer.singleShot(1500, self._model_kurulumu_oner)

    def _model_kurulumu_oner(self) -> None:
        """İlk açılışta: bu bilgisayara uygun model kurulu değilse bir kez sorar (kurulum sihirbazı gibi)."""
        yz, ayar = self.s.yz, self.s.ayarlar
        if ayar.al("yz.kurulum_soruldu", False) or (self._indirme and self._indirme.isRunning()):
            return
        from PySide6.QtWidgets import QApplication
        if QApplication.platformName() in ("offscreen", "minimal") or not yz.durum().get("sunucu_var"):
            return
        eksik = yz.eksik_kurulum()
        if not eksik:
            return
        ayar.ayarla("yz.kurulum_soruldu", True)
        ayar.kaydet()
        toplam = sum(m.yaklasik_gb for m in eksik)
        liste = "\n".join(f"  • {m.ad} (~{m.yaklasik_gb:g} GB)" for m in eksik)
        kutu = QMessageBox(QMessageBox.Question, UYGULAMA_ADI,
                           "Akıl Hocası'nın soruları anlayıp gerekçeli cevap ve resmî yazı taslağı hazırlayabilmesi için "
                           "bu bilgisayara uygun yerel dil modeli kurulmalı:\n\n" + liste +
                           f"\n\nToplam yaklaşık {toplam:g} GB tek seferlik indirme. Modeller bu bilgisayarda çalışır; "
                           "sorularınız ve belgeleriniz dışarı gönderilmez. İndirme arka planda sürer, program bu sırada "
                           "alıntıya dayalı modda kullanılabilir.\n\nŞimdi kurulsun mu?",
                           QMessageBox.Yes | QMessageBox.No, self)
        evet = kutu.button(QMessageBox.Yes)
        evet.setText("Kur")
        kutu.button(QMessageBox.No).setText("Daha sonra (Zekâ ekranından)")
        kutu.finished.connect(lambda _: kutu.clickedButton() == evet and self._model_kur([m.kimlik for m in eksik]))
        kutu.open()

    def _model_kur(self, kimlikler: list) -> None:
        if not kimlikler:
            self.zeka.indirme_bitti("Bu bilgisayar için önerilen modeller zaten kurulu. Başka bir model için tablodan seçin.")
            return
        if self._indirme and self._indirme.isRunning():
            return
        self._indirme = ModelIndirmeCalisani(self.s.yz, list(kimlikler), self)
        self._indirme.ilerleme.connect(self.zeka.indirme_durumu)
        self._indirme.ilerleme.connect(
            lambda a, b, _m: self.durum.model.setText(f"Model indiriliyor %{int(100 * a / b)}" if b else "Model indiriliyor"))
        self._indirme.bitti.connect(self._model_kuruldu)
        self._indirme.start()

    def _model_kuruldu(self, sonuc: dict) -> None:
        self.zeka.indirme_bitti(sonuc.get("mesaj", ""))
        self._bildirim("Model kurulumu", sonuc.get("mesaj", "")[:200])
        self.zeka.yenile()
        self._model_yukle()

    def _model_kullan(self, kimlik: str) -> None:
        if not any(m["kimlik"] == kimlik for m in self.s.yz.kurulu()):
            self.zeka.indirme_bitti("Bu model kurulu değil; önce \"Seçiliyi kur\" ile indirin.")
            return
        self._model_yukle(degistir=kimlik)

    def _model_sil(self, kimlik: str) -> None:
        if not any(m["kimlik"] == kimlik for m in self.s.yz.kurulu()):
            return
        if QMessageBox.question(self, UYGULAMA_ADI, "Model dosyası bu bilgisayardan silinsin mi?") != QMessageBox.Yes:
            return
        from ..yz.sunucu import ModelHatasi
        try:
            self.s.yz.sil(kimlik)
            self.zeka.indirme_bitti("Model silindi.")
        except ModelHatasi as e:
            self.zeka.indirme_bitti(str(e))
        self.zeka.yenile()

    def _anlam_dizinle(self) -> None:
        """Anlam dizinini küçük partilerle tamamlar (yeni maddeler geldikçe; kullanıcı soru sorarken bekler)."""
        if (not self._zamanlayici_acik or not self.s.yz.anlam.hazir
                or (self._anlam_calisani and self._anlam_calisani.isRunning())):
            return
        hazir, toplam = self.s.yz.anlam.ilerleme()
        if hazir >= toplam:
            return
        self._anlam_calisani = AnlamCalisani(self.s.yz, 256, self)
        self._anlam_calisani.bitti.connect(self._anlam_partisi_bitti)
        self._anlam_calisani.start()

    def _anlam_partisi_bitti(self, islenen: int) -> None:
        if self.yigin.currentWidget() is self.zeka:
            self.zeka.model_durumu_yaz(self.s.yz.durum())
        if islenen and bosta_kalma_sn() > 60:
            QTimer.singleShot(2_000, self._anlam_dizinle)

    # ================================================================== Hızlı Yakala
    def hizli_yakala(self) -> None:
        gorunurdu = self.isVisible() and not self.isMinimized()
        self.hide()

        def baslat():
            self.katman = YakalamaKatmani()
            self.katman.secildi.connect(lambda img: (self._geri_getir(gorunurdu), self.goruntu_ac(img)))
            self.katman.iptal.connect(lambda: self._geri_getir(gorunurdu))
            self.katman.show()
            self.katman.activateWindow()
            self.katman.raise_()

        QTimer.singleShot(220, baslat)

    def _geri_getir(self, gorunurdu: bool) -> None:
        if gorunurdu:
            self.show()

    def goruntu_ac(self, img: QImage) -> None:
        if img is None or img.isNull():
            return
        p = CanliMetinPenceresi(img, self.s.ocr, self.s.ayarlar.al("gizlilik.maske_varsayilan", True))
        p.sor.connect(self._yakalanani_sor)
        p.yaziya.connect(self.yaziya_gonder)
        p.duzeltildi.connect(self._ocr_duzeltildi)
        p.show()
        p.raise_()
        p.activateWindow()
        self._pencereler = [w for w in self._pencereler if w.isVisible()] + [p]

    def _yakalanani_sor(self, metin: str) -> None:
        self.goster()
        self._sayfa("danisma")
        self.danisma.soruyu_doldur(metin.strip())

    def belge_ice_aktar(self, yol: str) -> None:
        uzanti = Path(yol).suffix.lower()
        if uzanti in (".png", ".jpg", ".jpeg", ".bmp"):
            self.goruntu_ac(QImage(yol))
            return
        from ..crawler.depo import metin_cikar
        icerik = Path(yol).read_bytes()
        metin = metin_cikar(icerik)
        if not metin.strip() and uzanti == ".pdf":
            img = _pdf_ilk_sayfa(icerik)
            if img is not None:
                self.goruntu_ac(img)
                return
            QMessageBox.information(self, UYGULAMA_ADI, "Bu PDF taranmış görünüyor; sayfa görüntüsüne dönüştürmek "
                                    "için PyMuPDF gerekir (README).")
            return
        p = BelgeMetniPenceresi(Path(yol).name, metin)
        p.sor.connect(self._yakalanani_sor)
        p.yaziya.connect(self.yaziya_gonder)
        p.show()
        self._pencereler.append(p)

    # ================================================================== cevap eylemleri
    def yaziya_gonder(self, veri) -> None:
        self.goster()
        if isinstance(veri, Cevap):
            self.yazi.cevaptan(veri)                 # doğrulanmış cevap yazının dayanağı olur
        else:
            self.yazi.metin_al(str(veri))            # yakalanan/açılan metin gelen yazı kabul edilir
        self._sayfa("yazi")

    def belge_ac(self, ref) -> None:
        kayit = self.s.depo.bul(ref.kod) if ref.kod else None
        if kayit:
            import tempfile
            hedef = self.s.depo.kopya_ver(kayit, Path(tempfile.gettempdir()) / "AkilHocasi")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(hedef)))
        elif ref.url:
            QDesktopServices.openUrl(QUrl(ref.url))
        else:
            self._sayfa("depo")
            self.depo_sayfa.ara.setText(ref.kod.replace("TOGÜ.", ""))

    def _faydali(self, cevap: Cevap) -> None:
        if cevap.olay_id:
            self.s.ogrenme.geri_bildirim(cevap.olay_id, +1, cevap)
        self.durum.etkinlik.setText("Teşekkürler: cevap öğrenme hafızasına ve soru-cevap bankasına eklendi")

    def _kaynak_tiklandi(self, cevap: Cevap, kid: str) -> None:
        k = cevap.kaynak(kid)
        if k and cevap.olay_id:
            self.s.ogrenme.tiklama(cevap.olay_id, k.pasaj.belge_kimlik, k.pasaj.madde_no)

    def _ocr_duzeltildi(self, yanlis: str, dogru: str) -> None:
        self.s.ogrenme.ocr_duzeltme_kaydet(yanlis, dogru)

    def geri_bildirim(self, cevap: Cevap) -> None:
        if cevap.olay_id:
            self.s.ogrenme.geri_bildirim(cevap.olay_id, -1, cevap)
        yol = self.s.yollar.gunluk / "geri_bildirim.jsonl"
        kayit = {"zaman": datetime.now().isoformat(timespec="seconds"), "soru": cevap.soru,
                 "durum": cevap.durum.value, "kaynaklar": [k.etiket for k in cevap.kaynaklar]}
        with yol.open("a", encoding="utf-8") as f:
            f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
        QMessageBox.information(self, UYGULAMA_ADI, "Bildiriminiz kaydedildi. Soru incelenip altın soru setine "
                                "ve gerekirse işlem kartına eklenecek.")

    # ================================================================== güncelleme
    def _zamanlayici_tik(self) -> None:
        if not self._zamanlayici_acik or self._cikiliyor:
            return
        self._durumu_guncelle()
        if bosta_kalma_sn() > 120:
            self._anlam_dizinle()
        if self._tarama and self._tarama.isRunning():
            return
        z = self.s.zamanlayici
        son = {g: _dt(self.s.kutuphane.zamanlayici_son(g)) for g in GOREVLER}
        bekleyen = z.bekleyenler(datetime.now(), son, bostayken=bosta_kalma_sn() > 600)
        if "sabah" in bekleyen:
            self._sabah_ozeti()
            self.s.kutuphane.zamanlayici_yaz("sabah")
            bekleyen.remove("sabah")
        if "siteler" in bekleyen:
            bekleyen.remove("siteler")
            if self.s.ayarlar.al("gozlem.motor.acik", True) and self.s.motor.tarayici_yolu():
                for site in self.s.ayarlar.al("gozlem.motor.siteler", []) or []:
                    self.s.motor.ekle(site)
            self.s.kutuphane.zamanlayici_yaz("siteler")
        if "ogrenme" in bekleyen:
            bekleyen.remove("ogrenme")
            if not bekleyen:          # ağ taraması yokken öğren (aynı anda ikisi çalışmasın)
                self.ogren()
        if bekleyen:
            self.guncelle(bekleyen)

    def guncelle(self, gorevler: list[str]) -> None:
        if self.s.tarayici is None:
            self._bildirim(UYGULAMA_ADI, "Güncelleme için 'requests' paketi gerekli (README).")
            return
        if self._tarama and self._tarama.isRunning():
            return
        self.durum.calisiyor(True, "Güncelleme başladı")
        self._tarama = TaramaCalisani(self.s.tarayici, gorevler, self)
        self._tarama.ilerleme.connect(self.durum.etkinlik_yaz)
        self._tarama.gorev_bitti.connect(self._gorev_bitti)
        self._tarama.hepsi_bitti.connect(self._tarama_bitti)
        self._tarama.start()

    def _gorev_bitti(self, rapor) -> None:
        log.info("%s: %s; hata: %d", rapor.gorev, rapor.ozet, len(rapor.hatalar))
        for h in rapor.hatalar[:5]:
            log.warning("  %s", h)
        if rapor.yeni or rapor.guncellenen:
            self.rozet.setText(str(rapor.yeni + rapor.guncellenen))
            self.rozet.adjustSize()
            self.rozet.show()

    def _tarama_bitti(self) -> None:
        self.durum.calisiyor(False, "")
        self._durumu_guncelle()
        if self.s.kutuphane.takipteki_sorular() and not (self._takip and self._takip.isRunning()):
            self._takip = TakipCalisani(self.s.hat, self.s.kutuphane, self)
            self._takip.bulundu.connect(self._takip_bulundu)
            self._takip.start()

    def _takip_bulundu(self, soru: str) -> None:
        self._bildirim("Takipteki sorunuz için kaynak bulundu", soru[:120],
                       lambda q=soru: (self.goster(), self._sayfa("danisma"), self.danisma.sor(q, "derin")))

    # ================================================================== öğrenme
    def ogren(self) -> None:
        if (self._ogrenme and self._ogrenme.isRunning()) or (self._tarama and self._tarama.isRunning()):
            return
        self.durum.calisiyor(True, "Öz değerlendirme ve öğrenme")
        self._ogrenme = OgrenmeCalisani(self.s, self)
        self._ogrenme.ilerleme.connect(self.durum.etkinlik_yaz)
        self._ogrenme.bitti.connect(self._ogrenme_bitti)
        self._ogrenme.start()

    def _ogrenme_bitti(self, rapor: list) -> None:
        for satir in rapor:
            log.info("Öğrenme: %s", satir)
        self.durum.calisiyor(False, "Öğrenme tamamlandı")
        if self.yigin.currentWidget() is self.degisti:
            self.degisti.yenile()
        if self.s.ayarlar.al("yz.kendini_gelistir", True) and self.s.hat.model.hazir:
            self.kendini_gelistir()

    # ================================================================== kendini geliştirme
    def kendini_gelistir(self, elle: bool = False) -> None:
        """Anlam dizini, çalışma soruları, hatalardan dersler, gelişim kapısı ve model yarışı (arka planda)."""
        if self._zeka and self._zeka.isRunning():
            if elle:
                self.zeka.gelisim_durumu_yaz("Kendini geliştirme zaten çalışıyor.")
            return
        if not self.s.hat.model.hazir:
            self.zeka.gelisim_durumu_yaz("Kendini geliştirme için dil modeli gerekli. Önce modeli kurun.")
            return
        if self._anlam_calisani and self._anlam_calisani.isRunning():
            self._anlam_calisani.durdur.set()
        sure = float(self.s.ayarlar.al("yz.gelisim_suresi_dk", 45))
        self.durum.calisiyor(True, "Kendini geliştirme")
        self.zeka.gelisim_durumu_yaz(f"Çalışıyor (en çok {sure:g} dakika)…")
        self._zeka = ZekaCalisani(self.s, sure, self)
        self._zeka.ilerleme.connect(self.durum.etkinlik_yaz)
        self._zeka.ilerleme.connect(self.zeka.gelisim_durumu_yaz)
        self._zeka.bitti.connect(self._zeka_bitti)
        self._zeka.start()

    def _zeka_bitti(self, rapor: list) -> None:
        for satir in rapor:
            log.info("Kendini geliştirme: %s", satir)
        self.durum.calisiyor(False, "Kendini geliştirme tamamlandı")
        self.s.hat.model = self.s.yz.model
        ozet = "; ".join(str(r) for r in rapor[-4:])
        self.zeka.gelisim_durumu_yaz(f"Son çalışma {datetime.now():%d.%m.%Y %H:%M}: {ozet}" if ozet else "Tamamlandı.")
        self.zeka.yenile()

    def _aday_model_dene(self, yol: str) -> None:
        if self._aday and self._aday.isRunning():
            return
        self._aday_yolu = yol
        self.durum.calisiyor(True, "Aday model altın soru setinde karşılaştırılıyor")
        self._aday = AdayModelCalisani(self.s, yol, self)
        self._aday.bitti.connect(self._aday_sonucu)
        self._aday.start()

    def _aday_sonucu(self, karar: dict) -> None:
        self.durum.calisiyor(False, "")
        if karar.get("devreye_al"):
            self.s.yz.dis_modeli_benimse(karar["model"], karar.get("sunucu"), self._aday_yolu)
            self.s.hat.model = karar["model"]
            self.durum.model.setText(f"Model: {karar['model'].ad}")
        ayrinti = ""
        if "eski" in karar and "yeni" in karar:
            ayrinti = (f"\n\nAltın set: mevcut model {karar['eski']['gecen']}/{karar['eski']['toplam']} doğru "
                       f"(kritik {karar['eski']['kritik']}), aday {karar['yeni']['gecen']}/{karar['yeni']['toplam']} "
                       f"(kritik {karar['yeni']['kritik']}).")
        QMessageBox.information(self, UYGULAMA_ADI, ("Aday model devreye alındı: " if karar.get("devreye_al")
                                                    else "Aday model devreye alınmadı: ") + karar.get("neden", "") + ayrinti)

    def _sabah_ozeti(self) -> None:
        n = self.s.kutuphane.istatistik()["bugun_degisiklik"]
        son = self.s.kutuphane.son_degisiklikler(1)
        metin = f"Son 24 saatte {len(son)} değişiklik." if son else "Son 24 saatte değişiklik yok."
        self._bildirim("Bugün neler değişti", metin, lambda: (self.goster(), self._sayfa("degisti")))
        if n:
            self.rozet.setText(str(n))
            self.rozet.adjustSize()
            self.rozet.show()

    def _durumu_guncelle(self) -> None:
        ist = self.s.kutuphane.istatistik()
        son = _dt(self.s.kutuphane.zamanlayici_son("hafif"))
        sonraki = self.s.zamanlayici.sonraki(datetime.now())
        self.durum.kontrol.setText(f"Son kontrol {son:%H:%M} · Sonraki {sonraki:%H:%M}" if son
                                   else f"İlk kontrol bekleniyor · {sonraki:%H:%M}")
        self.durum.kutuphane.setText(f"Kütüphane: {ist['madde']:,} madde · {ist['belge']:,} belge".replace(",", "."))
        self.durum.takip.setText(f"Takipte: {ist['takip']} soru" if ist["takip"] else "")
        if not self.durum._calisiyor and ist["bugun_degisiklik"]:
            self.durum.etkinlik.setText(f"Bugün {ist['bugun_degisiklik']} değişiklik")

    def _durum_bilgisi(self) -> dict:
        ist = self.s.kutuphane.istatistik()
        return {"ocr_motorlari": [m.ad for m in self.s.ocr.motorlar],
                "model": "Model yüklü" if self.s.hat.model.hazir else "Alıntıya dayalı mod",
                "kutuphane": f"{ist['belge']} belge, {ist['madde']} madde, {ist['soru_cevap']} soru-cevap"}

    # ================================================================== tarayıcı gözlemcisi
    def _gozlem_kur(self) -> None:
        """Yerel gözlem sunucusunu ayarlara göre (yeniden) başlatır; eklenti ve motor aynı havuza akar."""
        from ..gozlem.eslestirme import anahtari_hazirla
        from ..gozlem.kurulum import eklentiyi_hazirla
        from ..gozlem.sunucu import GozlemSunucusu
        if self._gozlem_sunucusu:
            self._gozlem_sunucusu.durdur()
            self._gozlem_sunucusu = None
        a = self.s.ayarlar
        try:
            eklentiyi_hazirla(self.s.yollar.kok)
        except OSError as e:
            log.warning("Eklenti klasörü hazırlanamadı: %s", e)
        anahtar = anahtari_hazirla(a)
        self.havuz.gozlem_anahtar.setText(anahtar)
        if not a.al("gozlem.acik", True):
            self.durum.gozlem.setText("")
            self.havuz.gozlem_durumu_yaz("Eklenti gözlemi kapalı; gömülü tarayıcı yine çalışır.")
            return
        port = int(a.al("gozlem.port", 47231))
        sunucu = GozlemSunucusu(self.s.gozlem, anahtar, port, dosyalar=self.s.dosya_kuyrugu, motor=self.s.motor,
                                bildir=self._gozlem_koprusu.geldi.emit)
        if sunucu.baslat():
            self._gozlem_sunucusu = sunucu
            self.durum.gozlem.setText("Kaynak havuzu: hazır")
            self.havuz.gozlem_durumu_yaz(f"Yerel bağlantı 127.0.0.1:{port} üzerinde hazır.")
        else:
            self.durum.gozlem.setText("Kaynak havuzu: eklenti bağlantısı kapalı")
            self.havuz.gozlem_durumu_yaz(f"{port} numaralı bağlantı noktası kullanımda. Başka bir numara seçip kaydedin; "
                                         "eklenti yenisini köprüyle kendiliğinden alır.")

    def _gozlem_geldi(self, sonuc: dict) -> None:
        karar = sonuc.get("karar", "")
        self._gozlem_sayac[karar] = self._gozlem_sayac.get(karar, 0) + 1
        if self._gozlem_sunucusu:
            self.havuz.eklenti_temas(self._gozlem_sunucusu.son_temas)
        if karar == "kabul":
            self.durum.etkinlik.setText(f"Gözlemden eklendi: {sonuc.get('kimlik', '')[:60]}")
        self._havuz_yenileme.start(1500)

    def _motor_durumu(self, d: dict) -> None:
        self.havuz.motor_durumu(d)
        e = d.get("etkin")
        if e and e.get("durum") == "calisiyor":
            self.durum.gozlem.setText(f"Taranıyor: {e['kok'].split('//')[-1].rstrip('/')} · {e['sayfa']}/{e['en_cok']}")
        else:
            self.durum.gozlem.setText("Kaynak havuzu: hazır" if self._gozlem_sunucusu else "")
            self._havuz_yenileme.start(500)
        if not self._havuz_yenileme.isActive():
            self._havuz_yenileme.start(3000)

    def _havuzu_yenile(self) -> None:
        self.havuz.yenile()
        self._durumu_guncelle()

    def _site_tara(self, url: str) -> None:
        if not self.s.ayarlar.al("gozlem.motor.acik", True):
            self.havuz.gozlem_durumu_yaz("Gömülü tarayıcı ayarlarda kapalı.")
            return
        if not self.s.motor.tarayici_yolu():
            self.havuz.gozlem_durumu_yaz("Bilgisayarda Edge ya da Chrome bulunamadı; tarama yapılamıyor.")
            return
        ok, mesaj = self.s.motor.ekle(url)
        self.havuz.gozlem_durumu_yaz(mesaj)

    def _ayarlar_kaydedildi(self) -> None:
        from ..crawler.zamanlayici import Zamanlayici
        self.s.zamanlayici = Zamanlayici(self.s.ayarlar.al("guncelleme"), self.s.makine_kimligi)
        self._kisayol_kur()
        self._model_yukle()
        self._gozlem_kur()
        self._durumu_guncelle()
        self._bildirim(UYGULAMA_ADI, "Ayarlar kaydedildi.")

    # ================================================================== pencere
    def goster(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e) -> None:
        if not self._cikiliyor and self.tepsi.isVisible():
            e.ignore()
            self.hide()
            if not self.s.ayarlar.al("arayuz.tepsi_bildirildi", False):
                self._bildirim(UYGULAMA_ADI, "Program arka planda çalışmaya ve saat başı güncellemeye devam ediyor. "
                               "Tepsideki simgeden açabilirsiniz.")
                self.s.ayarlar.ayarla("arayuz.tepsi_bildirildi", True)
                self.s.ayarlar.kaydet()
            return
        self.cik()

    def calisanlari_durdur(self, bekle_ms: int = 3000) -> None:
        """Arka plan iş parçacıklarını durdurur ve bekler (çalışırken yok edilen QThread programı çökertir)."""
        self._zamanlayici_acik = False
        self.zaman.stop()
        if self._gozlem_sunucusu:
            self._gozlem_sunucusu.durdur()
        self.s.motor.kapat()
        self.s.dosya_kuyrugu.durdur()
        if self.s.tarayici:
            self.s.tarayici.durdur.set()
        for c in (self._indirme, self._anlam_calisani, self._zeka):
            if c and c.isRunning():
                c.durdur.set()
        yazi_calisani = getattr(self.yazi, "calisan", None)
        danisma_calisani = getattr(self.danisma, "calisan", None)
        for t in (self._tarama, self._takip, self._ogrenme, self._aday, self._indirme, self._anlam_calisani, self._zeka,
                  self._yz_baslatici, yazi_calisani, danisma_calisani):
            if t and t.isRunning():
                t.wait(bekle_ms)
        self.s.yz.durdur()

    def cik(self) -> None:
        self._cikiliyor = True
        self.calisanlari_durdur()
        self.kisayol.kaldir()
        self.tepsi.hide()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()


def _dt(iso: str | None):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def _pdf_ilk_sayfa(icerik: bytes) -> QImage | None:
    try:
        import fitz
    except ImportError:
        return None
    with fitz.open(stream=icerik, filetype="pdf") as doc:
        pm = doc[0].get_pixmap(dpi=200)
        return QImage(pm.samples, pm.width, pm.height, pm.stride,
                      QImage.Format_RGBA8888 if pm.alpha else QImage.Format_RGB888).copy()
