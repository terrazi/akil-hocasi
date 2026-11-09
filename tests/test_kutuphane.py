import json

from akil_hocasi.library.ayristirici import atiflari_bul, maddelere_bol
from akil_hocasi.library.sozluk import birim_oner, genislet
from conftest import ORNEK_KANUN


def test_maddelere_bolme():
    parcalar = maddelere_bol(ORNEK_KANUN)
    nolar = [p.madde_no for p in parcalar]
    assert nolar == ["Giriş", "1", "2", "3", "Ek 1", "Geçici 1"]
    md2 = parcalar[2]
    assert md2.baslik == "Aylıksız izin"
    assert "657/108" in md2.atiflar
    assert "Yıllık izin" not in md2.metin            # kenar başlığı sonraki maddeye taşındı
    assert parcalar[3].baslik == "Yıllık izin"
    assert parcalar[4].mulga
    assert "./2" in parcalar[5].atiflar


def test_atif_bulma():
    assert atiflari_bul("2547 sayılı Kanunun 39 uncu maddesi uyarınca") == ["2547/39"]
    assert atiflari_bul("bu Kanunun 64 üncü maddesinde") == ["./64"]


def test_sozluk():
    assert "aylıksız izin" in genislet("Ücretsiz izin nasıl alınır?")
    assert birim_oner("harcırah ödemesi") == "Strateji Geliştirme Daire Başkanlığı"
    assert birim_oner("aylıksız izin dönüşü") == "Personel Daire Başkanlığı"


def test_arama_esanlamli_ve_turkce_karakter(kutuphane):
    sonuc = kutuphane.ara("ücretsiz izin süresi", ek_terimler=genislet("ücretsiz izin"))
    assert sonuc and sonuc[0].madde_no == "2"
    assert kutuphane.ara("AYLIKSIZ IZIN")[0].madde_no == "2"       # büyük harf, noktasız yazım
    assert kutuphane.ara("yillik izin suresi")[0].madde_no == "3"


def test_surumleme_ve_tarihli_madde(kutuphane):
    ilk = kutuphane.madde_getir("9999", "2")
    assert "6 ay" in ilk.metin and ilk.yururlukte
    yeni = ORNEK_KANUN.replace("en fazla 6 ay", "en fazla 12 ay")
    assert kutuphane.belge_kaydet(tur="kanun", kimlik="9999", baslik="9999 sayılı Örnek Personel Kanunu",
                                  metin=yeni, sha256="a2", kaynak_url="https://www.mevzuat.gov.tr/ornek/9999") == "guncellendi"
    assert kutuphane.belge_kaydet(tur="kanun", kimlik="9999", baslik="x", metin=yeni, sha256="a2") == "ayni"
    guncel = kutuphane.madde_getir("9999", "2")
    assert "12 ay" in guncel.metin
    eski = kutuphane.madde_getir("9999", "2", tarih=ilk.son_kontrol)
    assert eski is not None and "6 ay" in eski.metin and not eski.yururlukte
    # Aramada yalnızca güncel sürüm döner
    assert all("6 ay" not in p.metin for p in kutuphane.ara("aylıksız izin"))


def test_bagimli_kart_ve_soru_cevap_isaretlenir(kutuphane):
    kutuphane.kart_kaydet("KART-IZIN", "Aylıksız izin", {"adimlar": []}, ["9999/2"], onaylayan="Uzman")
    kutuphane.soru_cevap_kaydet("Aylıksız izin kaç ay?", "Kısa cevap", ["9999/2"], [])
    kutuphane.belge_kaydet(tur="kanun", kimlik="9999", baslik="9999 sayılı Örnek Personel Kanunu",
                           metin=ORNEK_KANUN + "\nMADDE 4 – (1) Yeni madde.", sha256="a3")
    kart = kutuphane.db.execute("SELECT durum FROM islem_kartlari").fetchone()
    sc = kutuphane.db.execute("SELECT durum FROM soru_cevap").fetchone()
    assert kart["durum"] == "inceleme_bekliyor"
    assert sc["durum"] == "yeniden_dogrulanacak"
    turler = [r["tur"] for r in kutuphane.son_degisiklikler()]
    assert "inceleme" in turler and "guncellendi" in turler


def test_atif_zinciri(kutuphane):
    p = kutuphane.madde_getir("TOGÜ.USE.999", "1")
    assert "657/108" in p.atiflar
    # Geçici 1, aynı belgenin 2. maddesine atıf yapar → md. 2'nin geri atıflarında görünür
    md2 = kutuphane.madde_getir("9999", "2")
    zincir = kutuphane.atif_zinciri(md2)
    assert any(z.madde_no == "Geçici 1" for z in zincir)


def test_takip_ve_istatistik(kutuphane):
    sid = kutuphane.takibe_al("Mevzuatta olmayan bir durum?")
    assert kutuphane.takibe_al("Mevzuatta olmayan bir durum?") == sid
    ist = kutuphane.istatistik()
    assert ist["belge"] == 2 and ist["takip"] == 1 and ist["madde"] >= 6
    json.dumps(ist)
