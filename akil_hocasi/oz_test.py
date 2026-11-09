"""Paket öz testi: kurulum paketinin içindeki programı gerçek Qt ile ekransız çalıştırır.

Kullanım: AkilHocasi.exe --oz-test=rapor.txt
Ana pencereyi kurar, bütün sayfaları açar, örnek bir soruyu cevaplatır, OCR motorlarını
gerçek bir görüntüyle dener ve Hızlı Yakala penceresini açar. Sonuç rapor dosyasına yazılır;
çıkış kodu 0 = başarılı. Derleme hattı bu testi her kurulum dosyasından önce çalıştırır.
"""

from __future__ import annotations

import os
import platform
import sys
import tempfile
import traceback
from pathlib import Path


def calistir(rapor_yolu: str) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["AKILHOCASI_VERI"] = tempfile.mkdtemp(prefix="akilhocasi_oztest_")
    satirlar: list[str] = []
    hatalar: list[str] = []

    def adim(ad: str, fn) -> object:
        try:
            sonuc = fn()
            goster = sonuc if isinstance(sonuc, (str, int, float)) and sonuc != "" else ""
            satirlar.append(f"[TAMAM] {ad}" + (f": {goster}" if goster != "" else ""))
            return sonuc
        except Exception:
            hatalar.append(ad)
            satirlar.append(f"[HATA]  {ad}\n{traceback.format_exc()}")
            return None

    from . import __version__
    satirlar.append(f"Akıl Hocası {__version__} öz testi — Python {platform.python_version()}, {platform.platform()}")

    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    from .ui.tema import stil_sayfasi
    app.setStyleSheet(stil_sayfasi())

    from .uygulama import servisleri_kur
    s = adim("Servisler", servisleri_kur)
    if s is None:
        return _bitir(rapor_yolu, satirlar, hatalar)

    ornek = ("ÖZ TEST BELGESİ\nDeneme hükmü\nMADDE 1 – (1) Deneme hükmüne göre başvuru 15 gün içinde "
             "TOGÜ.FRM.396 formu ile yapılır.\n")
    adim("Kütüphaneye örnek belge", lambda: s.kutuphane.belge_kaydet(
        tur="kanun", kimlik="OZTEST", baslik="Öz test belgesi", metin=ornek, sha256="oztest",
        kaynak_url="https://www.mevzuat.gov.tr/oztest"))

    from .ui.ana_pencere import AnaPencere
    pencere = adim("Ana pencere", lambda: AnaPencere(s))
    if pencere is None:
        return _bitir(rapor_yolu, satirlar, hatalar)
    pencere.show()
    app.processEvents()

    def sayfalar():
        for a in pencere.sayfalar:
            pencere._sayfa(a)
            app.processEvents()
        return ", ".join(pencere.sayfalar)
    adim("Sayfalar", sayfalar)

    def soru():
        dongu = QEventLoop()
        pencere.danisma.cevap_hazir.connect(lambda _c: dongu.quit())
        QTimer.singleShot(60_000, dongu.quit)
        pencere.danisma.sor("Deneme hükmüne göre başvuru kaç gün içinde yapılır?", "derin")
        dongu.exec()
        c = pencere.danisma.son_cevap
        if c is None:
            raise RuntimeError("Cevap gelmedi")
        if not any("15 gün" in x.metin for x in c.kisa_cevap):
            raise RuntimeError(f"Beklenen alıntı yok: {c.durum.value}")
        return f"{c.durum.value}, {len(c.kaynaklar)} kaynak, {len(c.belgeler)} belge"
    adim("Danışma: soru-cevap", soru)

    def ogrenme():
        c = pencere.danisma.son_cevap
        if c is not None and c.olay_id:
            pencere._faydali(c)
        from .ogrenme.degerlendirme import GeceDegerlendirmesi
        rapor = GeceDegerlendirmesi(s.hat, s.kutuphane, s.ogrenme, s.siralayici).calistir()
        pencere._sayfa("degisti")
        app.processEvents()
        d = s.ogrenme.durum()
        return f"faydalı {d['faydali']}, örnek hafıza {d['ornek']}; " + " | ".join(rapor)[:160]
    adim("Öğrenme döngüsü", ogrenme)

    def ocr():
        motorlar = [m.ad for m in s.ocr.motorlar]
        if not motorlar:
            raise RuntimeError("Hiç OCR motoru yok")
        img = QImage(900, 120, QImage.Format_RGB32)
        img.fill(QColor("white"))
        p = QPainter(img)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setPen(QColor("#202020"))
        p.setFont(QFont("Arial", 16))
        p.drawText(16, 50, "Pijamalı hasta yağız şoföre çabucak güvendi.")
        p.drawText(16, 95, "TC Kimlik No: 10000000146  Tarih: 09.11.2026")
        p.end()
        from .ui.bilesenler import qimage_to_numpy
        sonuc = s.ocr.oku(qimage_to_numpy(img))
        metin = sonuc.metin()
        if "Pijamalı" not in metin and "şoföre" not in metin:
            raise RuntimeError(f"Türkçe metin okunamadı ({sonuc.motor}): {metin[:120]}")
        return f"motorlar: {', '.join(motorlar)} | okunan: {metin.splitlines()[0][:60]}"
    adim("OCR (Türkçe)", ocr)

    def yakala():
        from .ui.hizli_yakala import CanliMetinPenceresi
        img = QImage(400, 80, QImage.Format_RGB32)
        img.fill(QColor("white"))
        w = CanliMetinPenceresi(img, s.ocr, True)
        w.show()
        app.processEvents()
        w.close()
        return "açıldı"
    adim("Hızlı Yakala penceresi", yakala)

    adim("Belge Deposu sayfası", lambda: pencere.depo_sayfa.yenile() or "yenilendi")
    adim("Tesseract yolu", lambda: __import__("akil_hocasi.ocr.motorlar", fromlist=["x"]).paketteki_tesseract() or "pakette yok")

    def gozlemci():
        import json as _json
        import socket
        import urllib.request

        from .gozlem.sunucu import GozlemSunucusu
        eklenti = s.yollar.kok / "gozlemci_eklenti" / "manifest.json"
        if not eklenti.is_file():
            raise RuntimeError("eklenti klasörü pakette yok veya kopyalanamadı")
        with socket.socket() as so:
            so.bind(("127.0.0.1", 0))
            port = so.getsockname()[1]
        sunucu = GozlemSunucusu(s.gozlem, "oztest", port)
        if not sunucu.baslat():
            raise RuntimeError("gözlem sunucusu başlatılamadı")
        try:
            metin = "Öz test duyurusu. " * 30
            istek = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/gozlem", method="POST",
                data=_json.dumps({"url": "https://personel.gop.edu.tr/oztest", "metin": metin}).encode(),
                headers={"Content-Type": "application/json", "X-AkilHocasi-Anahtar": "oztest",
                         "Origin": "chrome-extension://oztest"})
            with urllib.request.urlopen(istek, timeout=5) as y:
                karar = _json.loads(y.read())["karar"]
        finally:
            sunucu.durdur()
        if karar != "kabul":
            raise RuntimeError(f"beklenmeyen karar: {karar}")
        return f"eklenti v{_json.loads(eklenti.read_text('utf-8'))['version']}, sunucu ve değerlendirici çalışıyor"
    adim("Tarayıcı gözlemcisi", gozlemci)

    if pencere._gozlem_sunucusu:
        pencere._gozlem_sunucusu.durdur()
    pencere._cikiliyor = True
    pencere.kisayol.kaldir()
    pencere.tepsi.hide()
    return _bitir(rapor_yolu, satirlar, hatalar)


def _bitir(rapor_yolu: str, satirlar: list[str], hatalar: list[str]) -> int:
    satirlar.append("")
    satirlar.append("SONUÇ: " + ("BAŞARILI" if not hatalar else f"BAŞARISIZ ({', '.join(hatalar)})"))
    Path(rapor_yolu).write_text("\n".join(satirlar), encoding="utf-8")
    return 0 if not hatalar else 1
