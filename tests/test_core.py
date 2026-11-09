from akil_hocasi.core import dogrulayicilar as d
from akil_hocasi.core.algilama import algila
from akil_hocasi.core.maskeleme import iban_maskele, metni_maskele, tc_maskele
from akil_hocasi.core.turkce import PANGRAM, alinti_normalle, katla, tr_lower, tr_title, tr_upper


def test_turkce_buyuk_kucuk_harf():
    assert tr_upper("istanbul ılık çiğ") == "İSTANBUL ILIK ÇİĞ"
    assert tr_lower("İSTANBUL ILIK ÇİĞ") == "istanbul ılık çiğ"
    assert tr_lower(tr_upper(PANGRAM)) == tr_lower(PANGRAM)
    assert tr_title("ısparta ığdır izmir") == "Isparta Iğdır İzmir"
    # Python'un varsayılanı yanlış: bunu düzelttiğimizi gösterir
    assert "i".upper() == "I" and tr_upper("i") == "İ"


def test_katlama_ve_alinti_normallestirme():
    assert katla("AYLIKSIZ İzin") == "ayliksiz izin"
    assert katla("Şoföre Çabucak Güvendi") == "sofore cabucak guvendi"
    assert alinti_normalle("“Aylıksız   izin”\nverilir – ") == alinti_normalle('"aylıksız izin" verilir -')


def test_tc_kimlik():
    assert d.tc_kimlik_gecerli("10000000146")
    assert not d.tc_kimlik_gecerli("10000000145")     # 11. hane yanlış
    assert not d.tc_kimlik_gecerli("10000000156")     # 10. hane yanlış
    assert not d.tc_kimlik_gecerli("00000000146")     # 0 ile başlayamaz
    assert not d.tc_kimlik_gecerli("1000000014")      # 10 hane


def test_iban():
    bban = "0006100519786457841326"
    kontrol = d.iban_kontrol_haneleri("TR", bban)
    iban = f"TR{kontrol}{bban}"
    assert d.iban_gecerli(iban)
    assert d.iban_gecerli(" ".join(iban[i:i + 4] for i in range(0, len(iban), 4)))
    bozuk = iban[:-1] + ("0" if iban[-1] != "0" else "1")
    assert not d.iban_gecerli(bozuk)
    assert not d.iban_gecerli(iban[:-1])               # TR için 26 karakter şart


def test_ekonomik_kod_ve_e_sayi():
    assert d.ekonomik_kod_gecerli("03.3.1.01")
    assert not d.ekonomik_kod_gecerli("03.3.1.1")
    assert d.ekonomik_kod_duzelt("03.3.1.1") == "03.3.1.01"
    assert d.e_sayi_gecerli("E-63599082-105.01.01.01")
    assert not d.e_sayi_gecerli("63599082-105")
    assert d.tarih_gecerli("29.02.2024") and not d.tarih_gecerli("30.02.2024")


def test_maskeleme():
    assert tc_maskele("10000000146") == "100******46"
    assert iban_maskele("TR330006100519786457841326").startswith("TR33 ****")
    assert iban_maskele("TR330006100519786457841326").endswith("26")
    m = metni_maskele("TC: 10000000146, IBAN: TR330006100519786457841326")
    assert "10000000146" not in m and "0006100519786457841326" not in m


def test_akilli_algilama():
    bban = "0006100519786457841326"
    iban = f"TR{d.iban_kontrol_haneleri('TR', bban)}{bban}"
    metin = (f"Sayı: E-63599082-105.01.01.01 Tarih: 09.11.2026 TC 10000000146 ve 10000000145, "
             f"IBAN {iban}, tutar 12.450,75 TL, ekonomik kod 03.3.1.1")
    bulgular = algila(metin)
    turler = [b.tur for b in bulgular]
    for t in ("e_sayi", "tarih", "tc", "iban", "tutar", "ekonomik_kod"):
        assert t in turler, t
    tcler = [b for b in bulgular if b.tur == "tc"]
    assert [b.gecerli for b in tcler] == [True, False]
    assert "Sağlama" in tcler[1].not_
    eko = next(b for b in bulgular if b.tur == "ekonomik_kod")
    assert not eko.gecerli and "03.3.1.01" in eko.not_
    ib = next(b for b in bulgular if b.tur == "iban")
    assert ib.gecerli and ib.kopya_degeri(maskeli=True) != iban and ib.kopya_degeri(maskeli=False) == iban
