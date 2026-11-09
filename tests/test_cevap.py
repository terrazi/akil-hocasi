from akil_hocasi.answer.dogrulama import DogrulamaMotoru
from akil_hocasi.answer.hat import CevapHatti
from akil_hocasi.answer.modeller import Cevap, Cumle, Durum, Kaynak
from akil_hocasi.crawler.beyaz_liste import BIRINCIL


def _cevap(kutuphane, *cumleler):
    p = kutuphane.madde_getir("9999", "2")
    c = Cevap(soru="Aylıksız izin ne kadar?", kaynaklar=[Kaynak("K1", p)])
    c.kisa_cevap = list(cumleler)
    return c


def test_dogrulama_testleri(kutuphane):
    motor = DogrulamaMotoru(kutuphane, BIRINCIL)
    c = _cevap(
        kutuphane,
        Cumle("Memura en fazla 6 ay aylıksız izin verilebilir.", ["K1"]),                 # geçer
        Cumle("“Memura isteği üzerine en fazla 6 ay aylıksız izin verilebilir.”", ["K1"]),  # birebir alıntı
        Cumle("“Memura isteği üzerine en fazla 24 ay izin verilir hükmü vardır.”", ["K1"]),  # uydurma alıntı
        Cumle("İzin süresi en fazla 18 aydır.", ["K1"]),                                    # kaynakta olmayan sayı
        Cumle("İlgili mevzuat çerçevesinde işlem yapılır.", ["K1"]),                        # afaki
        Cumle("Bu izin kıdemden sayılır.", []),                                             # kaynaksız
    )
    motor.dogrula(c)
    kalan = [x.metin for x in c.kisa_cevap]
    assert len(kalan) == 2
    assert c.durum == Durum.DOGRULANDI
    testler = {u.test for u in c.uyarilar}
    assert {"Alıntı", "Çapraz kontrol", "Somutluk", "Kaynak"} <= testler


def test_beyaz_liste_disi_kaynak_reddedilir(kutuphane):
    p = kutuphane.madde_getir("9999", "2")
    p.kaynak_url = "https://ornek-forum.com/konu/1"
    c = Cevap(soru="x", kaynaklar=[Kaynak("K1", p)])
    c.kisa_cevap = [Cumle("Memura en fazla 6 ay aylıksız izin verilebilir.", ["K1"])]
    DogrulamaMotoru(kutuphane, BIRINCIL).dogrula(c)
    assert c.durum == Durum.HUKUM_YOK and not c.kisa_cevap


def test_ekonomik_kod_duzeltilir(kutuphane):
    p = kutuphane.madde_getir("9999", "2")
    p.metin += " Gider 03.3.1.01 ekonomik koduna kaydedilir."
    c = Cevap(soru="x", kaynaklar=[Kaynak("K1", p)])
    c.kisa_cevap = [Cumle("Gider 03.3.1.1 koduna kaydedilir.", ["K1"])]
    DogrulamaMotoru(kutuphane, BIRINCIL).dogrula(c)
    assert c.kisa_cevap and "03.3.1.01" in c.kisa_cevap[0].metin


def test_hiyerarsi_uyarisi(kutuphane):
    # Üst norm (657/108) yönergeden sonra kütüphaneye yeni sürüm olarak girsin
    kutuphane.belge_kaydet(tur="kanun", kimlik="657", baslik="657 sayılı Devlet Memurları Kanunu",
                           metin="Aylıksız izin\nMADDE 108 – (1) Örnek metin.", sha256="z1",
                           kaynak_url="https://www.mevzuat.gov.tr/x")
    p = kutuphane.madde_getir("TOGÜ.USE.999", "1")
    c = Cevap(soru="x", kaynaklar=[Kaynak("K1", p)])
    c.kisa_cevap = [Cumle("Usul ve esaslar 657 sayılı Kanunun 108 inci maddesine dayanır.", ["K1"])]
    DogrulamaMotoru(kutuphane, BIRINCIL).dogrula(c)
    assert any(u.test == "Hiyerarşi" for u in c.uyarilar)
    assert c.durum == Durum.CELISKILI


def test_hat_dogrudan_cevap_model_yok(kutuphane):
    hat = CevapHatti(kutuphane, DogrulamaMotoru(kutuphane, BIRINCIL))
    adimlar = []
    c = hat.cevapla("Aylıksız izin en fazla kaç ay verilebilir?", ilerleme=lambda a, t, m: adimlar.append(a))
    assert c.durum == Durum.DOGRULANDI
    assert adimlar == list(range(1, 8))
    assert any("6 ay" in x.metin for x in c.kisa_cevap)
    assert c.kaynaklar[0].pasaj.madde_no == "2"
    assert all(x.kaynaklar for x in c.kisa_cevap)
    assert "Kısa cevap" in c.duz_metin()


def test_hat_form_belgesi_bulunur(kutuphane):
    hat = CevapHatti(kutuphane, DogrulamaMotoru(kutuphane, BIRINCIL))
    c = hat.cevapla("Aylıksız izin talebi hangi form ile birim amirine yapılır?")
    assert any(b.kod == "TOGÜ.FRM.396" for b in c.belgeler)


def test_hat_hukum_yok_takip_ve_somut_yol(kutuphane):
    hat = CevapHatti(kutuphane, DogrulamaMotoru(kutuphane, BIRINCIL))
    c = hat.cevapla("Kurum kreşi aidatı bordrodan kesilebilir mi?")
    assert c.durum == Durum.HUKUM_YOK
    assert c.acik_nokta and c.takip_id is not None
    assert any("görüş" in s.metin for s in c.somut_yol)
    assert kutuphane.takipteki_sorular()


class SahteModel:
    hazir = True
    ad = "sahte"

    def __init__(self, taslak):
        self.taslak = taslak

    def sohbet(self, mesajlar, max_tokens=700, sicaklik=0.1, json_mod=False):
        if "SORU:" in mesajlar[-1]["content"]:
            return self.taslak
        return '{"terimler": ["aylıksız izin"]}'


def test_hat_modelin_uydurmasi_ayiklanir(kutuphane):
    taslak = ('{"dogrudan_cevap": true, "kisa_cevap": ['
              '{"metin": "Memura en fazla 6 ay aylıksız izin verilebilir.", "kaynaklar": ["K1"]},'
              '{"metin": "Bu süre 36 aya kadar uzatılabilir.", "kaynaklar": ["K1"]}],'
              '"adimlar": [{"metin": "Talep TOGÜ.FRM.396 formu ile yapılır.", "kaynaklar": ["K2"]}], "dikkat": []}')
    hat = CevapHatti(kutuphane, DogrulamaMotoru(kutuphane, BIRINCIL), model=SahteModel(taslak))
    c = hat.cevapla("Aylıksız izin ne kadar verilebilir ve hangi formla istenir?")
    metinler = " ".join(x.metin for x in c.kisa_cevap)
    assert "6 ay" in metinler and "36" not in metinler
    assert c.model_kullanildi
