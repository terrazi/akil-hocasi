from collections import Counter

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from akil_hocasi.core.algilama import algila
from akil_hocasi.core.turkce import PANGRAM
from akil_hocasi.ocr.duzeltme import TurkceDuzeltici
from akil_hocasi.ocr.hat import OcrHatti, oyla
from akil_hocasi.ocr.iyilestirme import harf_yuksekligi, iyilestir
from akil_hocasi.ocr.motorlar import TesseractMotoru
from akil_hocasi.ocr.sonuc import OcrKelime, OcrSonuc

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _ekran_goruntusu(satirlar, boyut=14, genislik=760):
    """Ekran görüntüsünü taklit eden küçük punto metin."""
    font = ImageFont.truetype(FONT, boyut)
    yukseklik = 20 + len(satirlar) * (boyut + 10)
    img = Image.new("RGB", (genislik, yukseklik), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i, s in enumerate(satirlar):
        d.text((12, 10 + i * (boyut + 10)), s, font=font, fill=(30, 30, 30))
    return np.array(img)[:, :, ::-1].copy()   # RGB -> BGR


def test_duzeltici():
    d = TurkceDuzeltici(Counter({"aylıksız": 5, "izin": 9, "şoföre": 2}))
    assert d.oner("ayliksiz") == "aylıksız"
    assert d.oner("Sofore") == "Şoföre"
    assert d.oner("izin") == ""                      # zaten doğru


def test_tablo_ve_satir():
    k = [OcrKelime("Ad", 10, 10, 20, 12), OcrKelime("Soyad", 35, 10, 40, 12), OcrKelime("Tutar", 200, 11, 40, 12),
         OcrKelime("Ali", 10, 40, 20, 12), OcrKelime("Kaya", 35, 40, 30, 12), OcrKelime("1.250,00", 200, 41, 60, 12)]
    s = OcrSonuc(k, "test", 300, 60)
    assert s.metin() == "Ad Soyad Tutar\nAli Kaya 1.250,00"
    assert s.tablo_metni() == "Ad Soyad\tTutar\nAli Kaya\t1.250,00"


def test_oylama_anlasmazligi_isaretler():
    a = OcrSonuc([OcrKelime("ayliksiz", 0, 0, 50, 12, 0.7)], "A", 100, 20)
    b = OcrSonuc([OcrKelime("aylıksız", 1, 0, 50, 12, 0.95)], "B", 100, 20)
    s = oyla(a, b)
    assert s.kelimeler[0].metin == "aylıksız" and "ayliksiz" in s.kelimeler[0].alternatifler


def test_olcekleme_harf_yuksekligi():
    img = _ekran_goruntusu(["Küçük punto metin"], boyut=11)
    g, kat = iyilestir(img, 1)
    assert kat > 1.5 and harf_yuksekligi(g) > harf_yuksekligi(img[:, :, 0])


tesseract = TesseractMotoru()


@pytest.mark.skipif(not tesseract.kullanilabilir(), reason="Tesseract (tur) kurulu değil")
def test_tesseract_turkce_pangram_ve_algilama():
    img = _ekran_goruntusu([PANGRAM, "TC Kimlik No: 10000000146  Tarih: 09.11.2026",
                            "Sayı: E-63599082-105.01.01.01"], boyut=14)
    hat = OcrHatti([tesseract])
    s = hat.oku(img, seviye=1)
    metin = s.metin()
    for kelime in ("Pijamalı", "hasta", "yağız", "şoföre", "çabucak", "güvendi"):
        assert kelime in metin, (kelime, metin)
    turler = {b.tur for b in algila(metin)}
    assert {"tc", "tarih"} <= turler, metin
    # Kutular orijinal görüntü sınırları içinde
    h, w = img.shape[:2]
    assert all(0 <= k.x < w and 0 <= k.y < h for k in s.kelimeler)


@pytest.mark.skipif(not tesseract.kullanilabilir(), reason="Tesseract (tur) kurulu değil")
def test_bolge_yeniden_okuma():
    img = _ekran_goruntusu(["Birinci satır burada", "İkinci satır: Ödeme emri belgesi"], boyut=13)
    hat = OcrHatti([tesseract])
    ilk = hat.oku(img)
    ikinci_satir_y = 10 + 23
    yeni = hat.bolgeyi_yeniden_oku(img, ilk, (0, ikinci_satir_y - 4, img.shape[1], 24))
    assert "Ödeme" in yeni.metin() and "Birinci" in yeni.metin()
