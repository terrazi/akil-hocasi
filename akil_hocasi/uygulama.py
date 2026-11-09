"""Uygulama girişi: servisleri kurar, tek örnek kontrolü yapar ve ana pencereyi açar."""

from __future__ import annotations

import logging
import platform
import socket
import sys
import time
import uuid
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .answer.dogrulama import DogrulamaMotoru
from .answer.hat import CevapHatti
from .answer.llm import BosModel
from .config import Ayarlar, Yollar, veri_klasoru
from .crawler.beyaz_liste import BIRINCIL
from .crawler.depo import BelgeDeposu
from .crawler.zamanlayici import Zamanlayici
from .library.db import Kutuphane
from .ocr.duzeltme import TurkceDuzeltici
from .ocr.hat import OcrHatti
from .ocr.motorlar import motorlari_hazirla
from .gozlem import GozlemDegerlendirici
from .ogrenme import OgrenmeMotoru
from .ogrenme.siralayici import OgrenenSiralayici

log = logging.getLogger("akilhocasi")


@dataclass
class Servisler:
    yollar: Yollar
    ayarlar: Ayarlar
    kutuphane: Kutuphane
    depo: BelgeDeposu
    tarayici: object | None
    hat: CevapHatti
    ocr: OcrHatti
    zamanlayici: Zamanlayici
    makine_kimligi: str
    ogrenme: OgrenmeMotoru
    siralayici: OgrenenSiralayici
    gozlem: GozlemDegerlendirici


_cevrimici_onbellek = {"zaman": 0.0, "durum": True}


def cevrimici_mi() -> bool:
    """Ağ var mı? (5 dakika önbellekli, 2 sn zaman aşımı)"""
    if time.time() - _cevrimici_onbellek["zaman"] < 300:
        return _cevrimici_onbellek["durum"]
    try:
        socket.create_connection(("www.resmigazete.gov.tr", 443), timeout=2).close()
        durum = True
    except OSError:
        durum = False
    _cevrimici_onbellek.update(zaman=time.time(), durum=durum)
    return durum


def makine_kimligi() -> str:
    return f"{platform.node()}-{uuid.getnode():x}"


def gunlugu_kur(yollar: Yollar) -> None:
    isleyici = RotatingFileHandler(yollar.gunluk / "akilhocasi.log", maxBytes=2_000_000, backupCount=3,
                                   encoding="utf-8")
    isleyici.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(isleyici)
    log.setLevel(logging.INFO)

    def yakalanmayan(tur, deger, iz):
        log.error("Yakalanmayan hata", exc_info=(tur, deger, iz))
        sys.__excepthook__(tur, deger, iz)

    sys.excepthook = yakalanmayan


def servisleri_kur() -> Servisler:
    yollar = Yollar(veri_klasoru()).olustur()
    gunlugu_kur(yollar)
    ayarlar = Ayarlar(yollar.ayarlar)
    kutuphane = Kutuphane(yollar.veritabani)
    depo = BelgeDeposu(yollar.depo, ayarlar.al("depo.disk_siniri_mb", 2048))

    tarayici = None
    saglayicilar = []
    try:
        from .crawler.indirici import Indirici
        from .crawler.tarayici import HedefliSaglayici, Tarayici
        tarayici = Tarayici(kutuphane, depo, Indirici())
        saglayicilar = [HedefliSaglayici(tarayici)]
    except ImportError:
        log.warning("requests kurulu değil; çevrimiçi güncelleme kapalı")

    # OCR düzeltme sözlüğü kütüphanedeki mevzuat metinlerinden öğrenilir
    duzeltici = TurkceDuzeltici()
    for satir in kutuphane.db.execute("SELECT metin FROM maddeler WHERE yururluk_bitis IS NULL LIMIT 20000"):
        duzeltici.metinden_ogren(satir[0])
    motorlar = motorlari_hazirla(ayarlar.al("ocr.motor_sirasi", ["windows", "tesseract", "rapidocr"]),
                                 ayarlar.al("ocr.tesseract_yolu", ""))
    ocr = OcrHatti(motorlar, duzeltici, ayarlar.al("ocr.oylama", True))

    kimlik = makine_kimligi()
    ogrenme = OgrenmeMotoru(kutuphane, kimlik)
    ogrenme.duzeltici = duzeltici
    duzeltici.ogrenilmis.update(ogrenme.ocr_duzeltmeleri())
    siralayici = OgrenenSiralayici(kutuphane, ogrenme)
    hat = CevapHatti(kutuphane, DogrulamaMotoru(kutuphane, BIRINCIL), BosModel(), cevrimici=saglayicilar,
                     depo=depo, cevrimici_mi=cevrimici_mi,
                     ogrenme=ogrenme if ayarlar.al("ogrenme.acik", True) else None, siralayici=siralayici)
    return Servisler(yollar, ayarlar, kutuphane, depo, tarayici, hat, ocr,
                     Zamanlayici(ayarlar.al("guncelleme", {}), kimlik), kimlik, ogrenme, siralayici,
                     GozlemDegerlendirici(kutuphane))


_MUTEX = None


def _calisiyor_isareti() -> None:
    """Kurulum/kaldırma sihirbazı programın açık olduğunu bu adlandırılmış mutex'ten anlar."""
    global _MUTEX
    if sys.platform == "win32":
        import ctypes
        _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "AkilHocasi.Calisiyor")


def main() -> int:
    from . import __version__
    for arg in sys.argv[1:]:
        if arg == "--surum":
            if getattr(sys, "frozen", False):
                # Pencereli exe'de konsol yok; sürüm exe'nin yanındaki dosyaya yazılır
                (Path(sys.executable).parent / "surum.txt").write_text(__version__, encoding="utf-8")
            else:
                print(__version__)
            return 0
        if arg == "--gozlemci-kur":
            from .config import Yollar, veri_klasoru
            from .gozlem.kurulum import kurulumu_goster
            return kurulumu_goster(Yollar(veri_klasoru()).olustur().kok)
        if arg.startswith("--oz-test"):
            rapor = arg.split("=", 1)[1] if "=" in arg else "oz_test_raporu.txt"
            try:
                from .oz_test import calistir
                return calistir(rapor)
            except Exception:
                import traceback
                Path(rapor).write_text("SONUÇ: BAŞARISIZ (öz test çöktü)\n" + traceback.format_exc(), encoding="utf-8")
                return 1
    _calisiyor_isareti()

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QGuiApplication
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    from . import UYGULAMA_ADI
    from .ui.ana_pencere import AnaPencere
    from .ui.tema import stil_sayfasi

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(UYGULAMA_ADI)
    app.setOrganizationName("AkilHocasi")
    app.setQuitOnLastWindowClosed(False)

    # Tek örnek: ikinci açılış mevcut pencereyi öne getirir
    ad = "AkilHocasi-tek-ornek"
    soket = QLocalSocket()
    soket.connectToServer(ad)
    if soket.waitForConnected(300):
        soket.write(b"goster")
        soket.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(ad)
    sunucu = QLocalServer()
    sunucu.listen(ad)

    font = QFont("Segoe UI Variable Text" if sys.platform == "win32" else "Noto Sans", 10)
    app.setFont(font)
    app.setStyleSheet(stil_sayfasi())

    servisler = servisleri_kur()
    pencere = AnaPencere(servisler)
    sunucu.newConnection.connect(lambda: (sunucu.nextPendingConnection(), pencere.goster()))
    if "--tepside" not in sys.argv:
        pencere.show()
    log.info("Akıl Hocası başladı")
    return app.exec()
