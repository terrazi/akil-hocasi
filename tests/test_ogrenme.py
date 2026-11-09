import json

from akil_hocasi.answer.dogrulama import DogrulamaMotoru
from akil_hocasi.answer.hat import CevapHatti
from akil_hocasi.answer.modeller import Durum
from akil_hocasi.crawler.beyaz_liste import BIRINCIL
from akil_hocasi.library.db import Kutuphane
from akil_hocasi.ocr.duzeltme import TurkceDuzeltici
from akil_hocasi.ogrenme import OgrenmeMotoru
from akil_hocasi.ogrenme.degerlendirme import GeceDegerlendirmesi
from akil_hocasi.ogrenme.egitim import egitim_verisi_disa_aktar, modelleri_karsilastir
from akil_hocasi.ogrenme.paket import esitle, paket_ice_aktar, paket_olustur
from akil_hocasi.ogrenme.siralayici import OgrenenSiralayici
from conftest import ORNEK_KANUN


def _hat(k, ogr, siralayici=None, model=None):
    return CevapHatti(k, DogrulamaMotoru(k, BIRINCIL), model=model, ogrenme=ogr, siralayici=siralayici)


def test_terim_karsiligini_kullanimdan_ogrenir(kutuphane):
    ogr = OgrenmeMotoru(kutuphane, "pc-a")
    hat = _hat(kutuphane, ogr)
    once = hat.cevapla("tatil hakkı")
    assert once.durum == Durum.HUKUM_YOK and not once.kaynaklar
    for _ in range(2):                                  # iki kez gözlenince eşik aşılır
        assert hat.cevapla("tatil hakkı").durum == Durum.HUKUM_YOK
        assert hat.cevapla("aylıksız izin hakkı").durum == Durum.DOGRULANDI
    assert "ayliksiz" in ogr.ogrenilmis_terimler("tatil hakkı")
    sonra = hat.cevapla("tatil hakkı")
    # Artık ilgili madde bulunuyor; ama soru doğrudan cevaplanmadığı için uydurulmuyor
    assert any(k.pasaj.madde_no == "2" for k in sonra.kaynaklar)
    assert sonra.durum == Durum.HUKUM_YOK


def test_faydali_cevap_bankaya_ve_hafizaya_girer(kutuphane):
    ogr = OgrenmeMotoru(kutuphane, "pc-a")
    hat = _hat(kutuphane, ogr)
    c = hat.cevapla("Aylıksız izin en fazla kaç ay verilebilir?")
    assert c.olay_id and c.durum == Durum.DOGRULANDI
    ogr.geri_bildirim(c.olay_id, +1, c)
    assert kutuphane.soru_cevap_ara("aylıksız izin kaç ay")
    assert ogr.benzer_ornekler("Aylıksız izin kaç ay verilir?")
    assert ogr.kaynak_puani("9999", "2") >= 1
    # Bankadaki dayanak bir sonraki soruda 1. basamakta kullanılır
    c2 = hat.cevapla("aylıksız izin süresi kaç ay")
    assert c2.kaynaklar[0].pasaj.madde_no == "2"


def test_ocr_duzeltmesi_ogrenilir(kutuphane):
    ogr = OgrenmeMotoru(kutuphane, "pc-a")
    ogr.duzeltici = TurkceDuzeltici()
    ogr.ocr_duzeltme_kaydet("Gorevlendirme", "Görevlendirme")
    assert ogr.duzeltici.oner("Gorevlendirme") == "Görevlendirme"
    assert ogr.ocr_duzeltmeleri()["Gorevlendirme"] == "Görevlendirme"


def _buyuk_kutuphane(tmp_path):
    konular = ["Yıllık izin", "Mazeret izni", "Hastalık izni", "Aylıksız izin", "Görevlendirme", "Harcırah",
               "Fazla çalışma", "Ek ders", "Kıst maaş", "Aile yardımı", "Taşınır devri", "Doğrudan temin",
               "Yaklaşık maliyet", "Muayene kabul", "İstifa", "Naklen atama", "Askerlik", "Disiplin",
               "Jüri ücreti", "Ödeme emri", "Resmî yazışma", "İmza yetkisi", "Bilgi edinme", "Dilekçe",
               "Kişisel veri", "Toplu sözleşme", "Sendika", "Emeklilik", "Sözleşmeli personel", "Kadro"]
    satirlar = ["SENTETİK TEST KANUNU"]
    for i, konu in enumerate(konular, 1):
        satirlar.append(konu)
        satirlar.append(f"MADDE {i} – (1) {konu} ile ilgili usul bu maddede düzenlenir. "
                        f"{konu} işlemleri ilgili birim tarafından yürütülür. Genel izin ve personel hükümleri saklıdır.")
    k = Kutuphane(tmp_path / "buyuk.db")
    k.belge_kaydet(tur="kanun", kimlik="8888", baslik="8888 sayılı Sentetik Kanun", metin="\n".join(satirlar),
                   sha256="s1", kaynak_url="https://www.mevzuat.gov.tr/sentetik")
    return k


def test_siralayici_kendi_verisiyle_egitilir_ve_kapiyi_gecmeden_devreye_girmez(tmp_path):
    k = _buyuk_kutuphane(tmp_path)
    ogr = OgrenmeMotoru(k, "pc-a")
    sir = OgrenenSiralayici(k, ogr)
    assert not sir.aktif
    r = sir.egit()
    assert r is not None and r.sorgu >= 20 and r.ornek > r.sorgu
    assert r.devreye_girdi == sir.aktif
    if r.devreye_girdi:
        assert r.yeni_mrr > r.taban_mrr
    gecmis = sir.gecmis()
    assert gecmis and gecmis[0]["surum"] == r.surum
    # İkinci eğitim: yalnızca iyileşirse yeni sürüm aktif olur; aktif sürüm sayısı her zaman en fazla bir
    sir.egit()
    aktifler = k.db.execute("SELECT COUNT(*) FROM ogr_model WHERE aktif=1").fetchone()[0]
    assert aktifler <= 1
    # Uygulama sırasında onaylı kart dayanakları (skor >= 50) dokunulmaz
    p = k.ara("Harcırah usul")[0]
    p.skor = 60.0
    sir.uygula("Harcırah usul", [p])
    assert p.skor == 60.0


def test_ogrenme_paketi_paylasimi(tmp_path, kutuphane):
    a = OgrenmeMotoru(kutuphane, "pc-a")
    hat_a = _hat(kutuphane, a)
    for _ in range(2):
        hat_a.cevapla("tatil hakkı")
        hat_a.cevapla("aylıksız izin hakkı")
    c = hat_a.cevapla("Aylıksız izin en fazla kaç ay verilebilir? TC 10000000146")
    a.geri_bildirim(c.olay_id, +1, c)
    a.ocr_duzeltme_kaydet("Gorevlendirme", "Görevlendirme")
    yol = paket_olustur(a, tmp_path / "a.ahp")

    kb = Kutuphane(tmp_path / "b.db")
    kb.belge_kaydet(tur="kanun", kimlik="9999", baslik="9999 sayılı Örnek Personel Kanunu", metin=ORNEK_KANUN,
                    sha256="a1", kaynak_url="https://www.mevzuat.gov.tr/ornek/9999")
    b = OgrenmeMotoru(kb, "pc-b")
    b.duzeltici = TurkceDuzeltici()
    sonuc = paket_ice_aktar(b, yol)
    assert sonuc["makine"] == "pc-a" and sonuc["soru_cevap"] == 1
    assert "ayliksiz" in b.ogrenilmis_terimler("tatil hakkı")
    assert b.duzeltici.oner("Gorevlendirme") == "Görevlendirme"
    sc = kb.db.execute("SELECT soru, durum FROM soru_cevap").fetchone()
    assert sc["durum"] == "yeniden_dogrulanacak"             # yerel doğrulamadan kullanılmaz
    assert "10000000146" not in sc["soru"]                    # kişisel veri maskeli
    assert paket_ice_aktar(b, yol) == {"atlandi": "değişiklik yok"}
    # Aynı paket tekrar alınsa da sayılar iki katına çıkmaz
    assert b._es_anlam_sayilari()[("tatil", "ayliksiz")] == 2
    # Ortak klasörle eşitleme
    klasor = tmp_path / "ortak"
    klasor.mkdir()
    esitle(a, klasor)
    assert "1 bilgisayardan" in esitle(b, klasor) or "0 bilgisayardan" in esitle(b, klasor)
    assert len(list(klasor.glob("*.ahp"))) == 2


def test_gece_degerlendirmesi(kutuphane):
    ogr = OgrenmeMotoru(kutuphane, "pc-a")
    hat = _hat(kutuphane, ogr)
    ogr.altin_set_yukle([
        {"soru": "Aylıksız izin en fazla kaç ay verilebilir?", "beklenen_dayanak": ["9999/2"], "beklenen_ifade": "6 ay"},
        {"soru": "Kurum kreşi aidatı bordrodan kesilir mi?", "beklenen_dayanak": ["9999/9"]},
    ])
    iyi = kutuphane.soru_cevap_kaydet("aylıksız izin süresi", "6 ay", ["9999/2"], [])
    kotu = kutuphane.soru_cevap_kaydet("uzay görevi izni", "x", ["9999/99"], [])
    kutuphane.db.execute("UPDATE soru_cevap SET durum='yeniden_dogrulanacak'")
    rapor = GeceDegerlendirmesi(hat, kutuphane, ogr, OgrenenSiralayici(kutuphane, ogr)).calistir()
    metin = "\n".join(rapor)
    assert "Altın set: %50 başarı (1/2), kritik hata 0" in metin
    durumlar = dict(kutuphane.db.execute("SELECT id, durum FROM soru_cevap").fetchall())
    assert durumlar[iyi] == "dogrulandi" and durumlar[kotu] == "askida"
    assert not kutuphane.takipteki_sorular()                  # öz değerlendirme takip listesini kirletmez


class SahteModel:
    hazir = True

    def __init__(self, ad, taslak):
        self.ad, self.taslak = ad, taslak

    def sohbet(self, mesajlar, max_tokens=700, sicaklik=0.1, json_mod=False):
        return self.taslak if "SORU:" in mesajlar[-1]["content"] else '{"terimler": []}'


def test_egitim_verisi_ve_model_kapisi(tmp_path, kutuphane):
    ogr = OgrenmeMotoru(kutuphane, "pc-a")
    hat = _hat(kutuphane, ogr)
    c = hat.cevapla("Aylıksız izin en fazla kaç ay verilebilir?")
    ogr.geri_bildirim(c.olay_id, +1, c)
    n = egitim_verisi_disa_aktar(ogr, tmp_path / "egitim.jsonl")
    assert n == 1
    satir = json.loads((tmp_path / "egitim.jsonl").read_text("utf-8").splitlines()[0])
    roller = [m["role"] for m in satir["messages"]]
    assert roller == ["system", "user", "assistant"]
    hedef = json.loads(satir["messages"][2]["content"])
    assert hedef["dogrudan_cevap"] and all(x["kaynaklar"] for x in hedef["kisa_cevap"])

    ogr.altin_set_yukle([{"soru": "Aylıksız izin en fazla kaç ay verilebilir?", "beklenen_ifade": "6 ay"}])
    kotu = SahteModel("kotu", '{"dogrudan_cevap": false, "kisa_cevap": [], "acik_nokta": "bilinmiyor"}')
    iyi = SahteModel("iyi", '{"dogrudan_cevap": true, "kisa_cevap": [{"metin": "Memura en fazla 6 ay aylıksız izin verilebilir.", "kaynaklar": ["K1"]}]}')
    karar = modelleri_karsilastir(hat, kutuphane, kotu, iyi)
    assert karar["devreye_al"] is True
    assert modelleri_karsilastir(hat, kutuphane, iyi, kotu)["devreye_al"] is False
