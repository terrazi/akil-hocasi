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

    def ara_rapor(simdiki: str = "") -> None:
        """Rapor her adımda yazılır: öz test takılırsa derleme hattı nerede kaldığını gösterebilir."""
        try:
            Path(rapor_yolu).write_text("\n".join(satirlar + ([f"[SÜRÜYOR] {simdiki}"] if simdiki else [])),
                                        encoding="utf-8")
        except OSError:
            pass

    def adim(ad: str, fn) -> object:
        import time as _zaman
        ara_rapor(ad)
        bas = _zaman.monotonic()
        try:
            sonuc = fn()
            goster = sonuc if isinstance(sonuc, (str, int, float)) and sonuc != "" else ""
            sure = _zaman.monotonic() - bas
            satirlar.append(f"[TAMAM] {ad}" + (f": {goster}" if goster != "" else "") + (f" ({sure:.0f} sn)" if sure >= 5 else ""))
            return sonuc
        except Exception:
            hatalar.append(ad)
            satirlar.append(f"[HATA]  {ad}\n{traceback.format_exc()}")
            return None
        finally:
            ara_rapor()

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
    if s.bilgi_paketi is not None:                     # belirlenimci olsun: çekirdek paket önce işlensin
        import time as _t
        _b = _t.monotonic()
        s.bilgi_paketi.join(900)
        satirlar.append(f"[BİLGİ] Çekirdek bilgi paketi {(_t.monotonic() - _b):.0f} sn'de işlendi")

    ornek = ("ÖZ TEST BELGESİ\nDeneme hükmü\nMADDE 1 – (1) Deneme hükmüne göre başvuru 15 gün içinde "
             "TOGÜ.FRM.396 formu ile yapılır.\n")
    adim("Kütüphaneye örnek belge", lambda: s.kutuphane.belge_kaydet(
        tur="kanun", kimlik="OZTEST", baslik="Öz test belgesi", metin=ornek, sha256="oztest",
        kaynak_url="https://www.mevzuat.gov.tr/oztest"))

    from .ui.ana_pencere import AnaPencere
    pencere = adim("Ana pencere", lambda: AnaPencere(s))
    if pencere is None:
        return _bitir(rapor_yolu, satirlar, hatalar)
    pencere._zamanlayici_acik = False                 # arka plan güncellemesi öz testi etkilemesin
    pencere.zaman.stop()
    pencere.show()
    app.processEvents()
    # Yerel modeller arka planda başlar; arayüz akışı modelsiz (belirlenimci) sınanır, model ayrıca uçtan uca sınanır
    if pencere._yz_baslatici:
        pencere._yz_baslatici.wait(600_000)
        app.processEvents()
    from .answer.llm import BosModel
    gercek_model = s.hat.model
    s.hat.model = BosModel()

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
    s.hat.model = gercek_model

    def ocr():
        motorlar = [m.ad for m in s.ocr.motorlar]
        if not motorlar:
            raise RuntimeError("Hiç OCR motoru yok")
        # Ekransız (offscreen) Qt'nin yazı tipi listesi boş olabilir: yazı tipi dosyası doğrudan yüklenir
        from PySide6.QtGui import QFontDatabase
        aile = "Arial"
        for dosya in (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf"),
                      os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segoeui.ttf"),
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            if os.path.isfile(dosya):
                no = QFontDatabase.addApplicationFont(dosya)
                aileler = QFontDatabase.applicationFontFamilies(no) if no >= 0 else []
                if aileler:
                    aile = aileler[0]
                    break
        img = QImage(900, 120, QImage.Format_RGB32)
        img.fill(QColor("white"))
        p = QPainter(img)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setPen(QColor("#202020"))
        p.setFont(QFont(aile, 16))
        p.drawText(16, 50, "Pijamalı hasta yağız şoföre çabucak güvendi.")
        p.drawText(16, 95, "TC Kimlik No: 10000000146  Tarih: 09.11.2026")
        p.end()
        from .ui.bilesenler import qimage_to_numpy
        dizi = qimage_to_numpy(img)
        if int(dizi.min()) > 200:
            raise RuntimeError(f"Test görüntüsü boş çizildi (yazı tipi: {aile}); OCR sınanamadı")
        sonuc = s.ocr.oku(dizi)
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

    def gomulu_tarayici():
        from .gozlem.cdp import BasliksizTarayici, tarayici_bul
        yol = tarayici_bul(s.ayarlar.al("gozlem.motor.tarayici_yolu", ""))
        if not yol:
            return "Edge/Chrome bulunamadı (gömülü tarayıcı kapalı; eklenti yine çalışır)"
        with BasliksizTarayici(yol, durulma=0.2) as t:
            sonuc = t.sayfa_oku("data:text/html,<h1>Akil Hocasi</h1>")
            surum = t.surum
        if sonuc.get("tur") != "kapsam_disi":          # data: adresi beyaz listede değil: ortak kural reddetmeli
            raise RuntimeError(f"ortak okuma kuralı beklenmeyen sonuç verdi: {sonuc}")
        return f"{surum}: görünmez tarayıcı, yalıtılmış dünya ve ortak okuma kuralı çalışıyor"
    adim("Gömülü tarayıcı", gomulu_tarayici)

    def kopru():
        import json as _json
        import struct
        import subprocess

        from .gozlem.eslestirme import EKLENTI_KIMLIGI, KOPRU_EXE
        if not getattr(sys, "frozen", False):
            return "geliştirme ortamı (köprü exe'si paketle gelir)"
        exe = Path(sys.executable).with_name(KOPRU_EXE)
        if not exe.is_file():
            raise RuntimeError(f"{KOPRU_EXE} pakette yok")
        veri = _json.dumps({"tur": "eslestir"}).encode()
        c = subprocess.run([str(exe), f"chrome-extension://{EKLENTI_KIMLIGI}/"], input=struct.pack("<I", len(veri)) + veri,
                           capture_output=True, timeout=60, env=dict(os.environ))
        n = struct.unpack("<I", c.stdout[:4])[0]
        cevap = _json.loads(c.stdout[4:4 + n])
        if not cevap.get("ok") or not cevap.get("anahtar"):
            raise RuntimeError(f"köprü cevabı: {cevap}")
        return "köprü exe'si tarayıcı gibi çağrıldı, eşleşme anahtarını döndürdü"
    adim("Eklenti köprüsü", kopru)

    adim("Kaynak Havuzu sayfası", lambda: pencere.havuz.yenile() or "yenilendi")

    def bilgi_paketi():
        from .crawler.kaynaklar import RESMI_YAZISMA_KIMLIGI
        from .library.bilgi_paketi import paket_klasoru, paketi_yukle
        klasor = paket_klasoru()
        if klasor is None:
            return "pakette yok (derleme sırasında mevzuat.gov.tr'ye ulaşılamamış olabilir)"
        if s.bilgi_paketi is not None:
            s.bilgi_paketi.join(300)
        sonuc = paketi_yukle(s.tarayici, klasor)
        if sonuc["hata"]:
            raise RuntimeError("; ".join(sonuc["hata"][:3]))
        import json as _json
        belgeler = _json.loads((klasor / "manifest.json").read_text("utf-8"))["belgeler"]
        eksik = [b["kimlik"] for b in belgeler if not s.kutuphane.belge_bilgisi(b["kimlik"])]
        if eksik:
            raise RuntimeError(f"kütüphaneye işlenmeyen: {', '.join(eksik)}")
        ryy = "var" if s.kutuphane.belge_bilgisi(RESMI_YAZISMA_KIMLIGI) else "yok"
        return f"{len(belgeler)} belge kütüphanede (Resmî Yazışma Yönetmeliği: {ryy})"
    adim("Çekirdek bilgi paketi", bilgi_paketi)

    def cekirdek():
        import threading

        from .cekirdek.ilkeler import CEKIRDEK_SURUMU, ILKELER, sistem_cekirdegi
        from .cekirdek.yordamlar import IS_AKISLARI, YORDAMLAR, el_kitabi_md
        if len(ILKELER) < 12 or len(YORDAMLAR) < 20 or "GÖREV:" not in sistem_cekirdegi("deneme"):
            raise RuntimeError("çekirdek eksik yüklendi")
        if len(el_kitabi_md()) < 5000:
            raise RuntimeError("El Kitabı eksik")
        # Sınama ayarları yalnız sınavı yürüten iş parçacığında geçerli olmalı
        gorulen = []
        with s.strateji.gecici({("secme", "sunulacak_kaynak"): 3}):
            ic = s.strateji.deger("secme", "sunulacak_kaynak")
            th = threading.Thread(target=lambda: gorulen.append(s.strateji.deger("secme", "sunulacak_kaynak")))
            th.start()
            th.join()
        if ic != 3 or gorulen != [6]:
            raise RuntimeError(f"geçici ayar yalıtımı bozuk: iç {ic}, diğer iş parçacığı {gorulen}")
        return (f"sürüm {CEKIRDEK_SURUMU}: {len(ILKELER)} ilke, {len(YORDAMLAR)} yordam, {len(IS_AKISLARI)} iş akışı, "
                f"{len(s.strateji.tumu())} ayar")
    adim("Çekirdek (ilkeler, yordamlar, strateji)", cekirdek)

    adim("Zekâ sayfası", lambda: pencere.zeka.yenile() or f"{pencere.zeka.model_tablosu.rowCount()} model listelendi")

    def kaggle_baglantisi():
        import json as _json
        import zipfile as _zip

        from .yz.kaggle_paketi import paket_olustur
        d = Path(tempfile.mkdtemp())
        gguf = d / "akilhocasi-4b-oztest.gguf"
        gguf.write_bytes(b"GGUF" + b"\0" * 64)
        (d / "akilhocasi-4b-oztest.json").write_text(_json.dumps({
            "kimlik": "akilhocasi-4b-oztest", "ad": "Öz test eğitilmiş model", "tur": "sohbet", "temel": "qwen3.5-4b",
            "en_az_bellek_gb": 7.5, "egitim": {"kapi": False}}), encoding="utf-8")
        once = pencere.zeka.model_tablosu.rowCount()
        pencere._ozel_model_ekle(str(gguf))
        pencere._is_calisani.wait(60_000)
        app.processEvents()
        if not any(m["kimlik"] == "akilhocasi-4b-oztest" for m in s.yz.ozel_modeller()):
            raise RuntimeError("eğitilmiş model eklenemedi")
        if pencere.zeka.model_tablosu.rowCount() != once + 1:
            raise RuntimeError("eğitilmiş model Zekâ tablosunda görünmüyor")
        s.yz.sil("akilhocasi-4b-oztest")
        m = paket_olustur(s.kutuphane, d / "paket.zip")
        with _zip.ZipFile(d / "paket.zip") as z:
            if {"kutuphane.db", "sorular.jsonl", "manifest.json"} - set(z.namelist()):
                raise RuntimeError("eğitim paketi eksik")
        return f"eğitilmiş model eklendi ve listelendi; eğitim paketi {m['boyut_mb']} MB ({m['belge']} belge)"
    adim("Kaggle bağlantısı (eğitilmiş model, eğitim paketi)", kaggle_baglantisi)

    def resmi_yazi():
        from .answer.llm import BosModel
        from .yazi.cikti import docx_kaydet
        sayfa = pencere.yazi
        s.ayarlar.ayarla("yazi.profil", {"idare": "TOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ", "birim": "Personel Daire Başkanlığı",
                                         "imza_ad": "Öz", "imza_soyad": "Test", "imza_unvan": "Daire Başkanı"})
        sayfa.metin_al("T.C.\nTOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ\nStrateji Geliştirme Daire Başkanlığı\n\n"
                       "Sayı : E-12345678-841-123456   05.11.2026\nKonu : Deneme hükmü uygulaması\n\n"
                       "PERSONEL DAİRE BAŞKANLIĞINA\n\nDeneme hükmüne göre başvuru süresinin bildirilmesi "
                       "gerekmektedir.\nBilgilerinizi rica ederim.\n")
        sayfa.talimat.setPlainText("Başvurular TOGÜ.FRM.396 formu ile 15 gün içinde yapılmaktadır.")
        if sayfa.gelen is None or sayfa.gelen.sayi != "E-12345678-841-123456":
            raise RuntimeError("gelen yazı çözümlenemedi")
        eski_model, s.hat.model = s.hat.model, BosModel()
        try:
            istek_sayfa = sayfa
            istek_sayfa.hazirla()
            istek_sayfa.calisan.wait(120_000)
            app.processEvents()
        finally:
            s.hat.model = eski_model
        sonuc = sayfa.sonuc
        if sonuc is None:
            raise RuntimeError("taslak oluşmadı: " + sayfa.durum.text())
        y = sonuc.yazi
        if y.muhatap != "Strateji Geliştirme Daire Başkanlığı" or y.paragraflar[-1].metin != "Bilgilerinizi arz ederim.":
            raise RuntimeError(f"beklenmeyen taslak: {y.muhatap} / {y.paragraflar[-1].metin}")
        for i in range(sayfa.sekmeler.count()):
            sayfa.sekmeler.setCurrentIndex(i)
            app.processEvents()
        sayfa.metin_duzen.setPlainText(sayfa.metin_duzen.toPlainText() + "\n\nEk paragraf 3 personel.")
        sayfa.yeniden_denetle()
        yol = docx_kaydet(y, Path(tempfile.mkdtemp()) / "oz_test_taslak.docx")
        if "STRATEJİ GELİŞTİRME DAİRE BAŞKANLIĞINA" not in sayfa.ebys.toPlainText():
            raise RuntimeError("EBYS metni eksik")
        return (f"{len(y.paragraflar)} paragraf, {sonuc.hata_sayisi} hata, kontrol listesi {len(sonuc.kontrol)} madde, "
                f"Word {yol.stat().st_size // 1024} KB")
    adim("Resmî yazı (gelen yazı → taslak → Word/EBYS)", resmi_yazi)

    def model_sunucusu():
        from .yz.sunucu import sunucu_exe
        exe = sunucu_exe(s.ayarlar.al("yz.sunucu_yolu", ""))
        if not exe:
            if getattr(sys, "frozen", False):
                raise RuntimeError("llama-server pakette yok")
            return "geliştirme ortamı (llama-server paketle gelir)"
        import subprocess
        c = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        surum = (c.stdout + c.stderr).strip().splitlines()
        return f"{Path(exe).name}: {surum[0][:80] if surum else 'sürüm bilgisi yok'}"
    adim("Yerel model sunucusu", model_sunucusu)

    def yerel_model():
        import time as _time

        from .yz.sunucu import env_model_klasoru
        if not env_model_klasoru():
            return "atlandı (AKILHOCASI_MODELLER tanımlı değil)"
        d = s.yz.baslat()
        if not s.yz.model.hazir:
            raise RuntimeError(f"dil modeli başlamadı: {d.get('son_hata')}")
        if not s.yz.anlam.hazir:
            raise RuntimeError(f"anlam modeli başlamadı: {d.get('son_hata')}")
        s.hat.model, s.hat.anlam = s.yz.model, s.yz.anlam
        from .yz import sunucu as _sunucu
        if sys.platform == "win32" and _sunucu._IS_NESNESI is None:
            raise RuntimeError("model sunucusu iş nesnesine bağlanamadı (program kapanınca sunucu açık kalabilir)")
        islenen = s.yz.anlam.eksikleri_isle(64, belge_kimligi="OZTEST") + s.yz.anlam.eksikleri_isle(32)
        bulunan = s.yz.anlam.ara("başvuru için tanınan süre ne kadar", 3)
        oztest_id = s.kutuphane.db.execute(
            "SELECT m.id FROM maddeler m JOIN belgeler b ON b.id=m.belge_id WHERE b.kimlik='OZTEST'").fetchone()[0]
        if not bulunan or bulunan[0][0] != oztest_id:
            raise RuntimeError(f"anlam araması öz test maddesini bulamadı: {bulunan}")
        ham = s.yz.model.sohbet([{"role": "user", "content": "Türkiye'nin başkenti neresidir? JSON ver."}], max_tokens=60,
                                json_sema={"type": "object", "properties": {"sehir": {"type": "string"}},
                                           "required": ["sehir"]})
        import json as _json
        if "sehir" not in _json.loads(ham):
            raise RuntimeError(f"yapılandırılmış çıktı bozuk: {ham[:120]}")
        t0 = _time.monotonic()
        c = s.hat.cevapla("Deneme hükmüne göre başvuru kaç gün içinde ve hangi formla yapılır?", "derin", kayit=False)
        sure = _time.monotonic() - t0
        if not c.dusunce:
            raise RuntimeError("düşünce kaydı boş")
        olcum = s.yz.model.hiz_olc()
        from .yz.oz_gelisim import GeceZekaCalismasi
        uretim = GeceZekaCalismasi(s, lambda _m: None).sentetik_uret(2, _time.monotonic() + 240)
        if pencere._anlam_calisani:
            pencere._anlam_calisani.durdur.set()
            pencere._anlam_calisani.wait(60_000)
        s.yz.durdur()
        return (f"{s.yz.secili('sohbet')['ad']}: {islenen} madde vektörlendi, anlam araması doğru, JSON çıktı geçerli, "
                f"cevap {sure:.0f} sn ({c.durum.value}, {len(c.kaynaklar)} kaynak, güven {c.guven or '-'}), "
                f"kısa cevap {olcum.get('sure_sn', '?')} sn; çalışma sorusu üretimi: {uretim}")
    adim("Yerel dil modeli (uçtan uca)", yerel_model)

    pencere._cikiliyor = True
    adim("Kapanış (arka plan iş parçacıkları)", lambda: pencere.calisanlari_durdur(30_000) or "durduruldu")
    pencere.kisayol.kaldir()
    pencere.tepsi.hide()
    return _bitir(rapor_yolu, satirlar, hatalar)


def _bitir(rapor_yolu: str, satirlar: list[str], hatalar: list[str]) -> int:
    satirlar.append("")
    satirlar.append("SONUÇ: " + ("BAŞARILI" if not hatalar else f"BAŞARISIZ ({', '.join(hatalar)})"))
    Path(rapor_yolu).write_text("\n".join(satirlar), encoding="utf-8")
    return 0 if not hatalar else 1
