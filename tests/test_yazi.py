"""Resmî Yazı Hazırlama: dil kuralları, gelen yazı çözümleme, kontrol listesi, sınama ve Word çıktısı."""

import json

from akil_hocasi.answer.dogrulama import DogrulamaMotoru
from akil_hocasi.answer.hat import CevapHatti
from akil_hocasi.crawler.beyaz_liste import BIRINCIL
from akil_hocasi.yazi.cikti import docx_kaydet, ebys_metni, html_onizleme
from akil_hocasi.yazi.dil import ilgi_hali, kisi_adi, konu_bicimi, muhatap_bicimi, sayilari_grupla, yonelme
from akil_hocasi.yazi.gelen import cevap_muhatabi, cozumle
from akil_hocasi.yazi.hazirlayici import YaziHazirlayici, YaziIstegi, kendi_adi
from akil_hocasi.yazi.kontrol import duzelt, kontrol_et
from akil_hocasi.yazi.kurallar import bitis_ifadesi, bitis_uyumlu_mu, ilgi_satirlari, makam_tahmini
from akil_hocasi.yazi.model import Ilgi, Imza, Paragraf, Yazi

GELEN = """GÜNLÜDÜR
T.C.
TOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ
Strateji Geliştirme Daire Başkanlığı

Sayı : E-12345678-841-123456                                   05.11.2026
Konu : aylıksız izin kullanan personel

PERSONEL DAİRE BAŞKANLIĞINA

İlgi : 15.10.2026 tarihli ve E-12345678-841-111 sayılı yazımız.

Bütçe çalışmalarında kullanılmak üzere aylıksız izin kullanan personel sayısının ve izin sürelerinin
20.11.2026 tarihine kadar Başkanlığımıza bildirilmesi gerekmektedir.
Bilgilerinizi ve gereğini rica ederim.

Mehmet KAYA
Daire Başkanı
"""

PROFIL = {"idare": "TOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ", "birim": "Personel Daire Başkanlığı", "imza_ad": "ahmet",
          "imza_soyad": "yılmaz", "imza_unvan": "Daire Başkanı", "adres": "Taşlıçiftlik Yerleşkesi Tokat",
          "bilgi_ad": "Ayşe Kara", "bilgi_unvan": "Şef"}


def test_dil_kurallari():
    assert muhatap_bicimi("Strateji Geliştirme Daire Başkanlığı") == "STRATEJİ GELİŞTİRME DAİRE BAŞKANLIĞINA"
    assert muhatap_bicimi("TOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ REKTÖRLÜĞÜ") == "TOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ REKTÖRLÜĞÜNE"
    assert yonelme("Sağlık Bilimleri Enstitüsü") == "Sağlık Bilimleri Enstitüsüne"
    assert yonelme("PERSONEL DAİRE BAŞKANLIĞINA") == "PERSONEL DAİRE BAŞKANLIĞINA"          # zaten yönelme hâlinde
    assert ilgi_hali("Sosyal Güvenlik Kurumu") == "Sosyal Güvenlik Kurumunun"
    assert ilgi_hali("PERSONEL DAİRE BAŞKANLIĞINA") == "PERSONEL DAİRE BAŞKANLIĞININ"
    assert konu_bicimi("öğretim elemanı görevlendirilmesi hk.") == "Öğretim Elemanı Görevlendirilmesi Hakkında"
    assert konu_bicimi("PERSONEL DAİRE BAŞKANLIĞI VE TOGÜ") == "Personel Daire Başkanlığı ve TOGÜ"
    assert kisi_adi("ayşe nur yılmaz") == "Ayşe Nur YILMAZ"
    assert sayilari_grupla("12500 TL; 2026 yılı; madde 1234") == "12.500 TL; 2026 yılı; madde 1234"
    assert kendi_adi("Ziraat Fakültesi Dekanlığı") == "Dekanlığımız" and kendi_adi("Genel Sekreterlik") == "Sekreterliğimiz"


def test_bitis_ve_makam():
    assert bitis_ifadesi("ust", "bilgi") == "Bilgilerinizi arz ederim."
    assert bitis_ifadesi("alt", "gereği") == "Gereğini rica ederim."
    assert bitis_ifadesi("karisik", "bilgi_ve_gereği") == "Bilgilerinizi ve gereğini arz ve rica ederim."
    assert bitis_ifadesi("kisi") == "Bilgilerinize sunulur."
    assert not bitis_uyumlu_mu("Gereğini rica ederim.", "ust")[0]
    assert makam_tahmini("TOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ REKTÖRLÜĞÜNE") == ("ust", True)
    assert makam_tahmini("Sayın Ali VELİ")[0] == "kisi"


def test_ilgi_siralama_ve_bicim():
    y = Yazi(muhatap="Strateji Geliştirme Daire Başkanlığı", ilgiler=[
        Ilgi("05.11.2026", "E-1-2-3", "Strateji Geliştirme Daire Başkanlığı"),
        Ilgi("01.10.2026", "E-4-5-6", "Sosyal Güvenlik Kurumu"),
        Ilgi(tarih="02.11.2026", kisi="ali öztürk", tur="dilekçesi")])
    s = ilgi_satirlari(y)
    assert s[0] == "a) Sosyal Güvenlik Kurumunun 01.10.2026 tarihli ve E-4-5-6 sayılı yazısı."     # eskiden yeniye
    assert s[1] == "b) Ali ÖZTÜRK'ün 02.11.2026 tarihli dilekçesi."
    assert s[2] == "c) 05.11.2026 tarihli ve E-1-2-3 sayılı yazı."       # muhatap idareden gelen: idare adı yazılmaz


def test_gelen_yazi_cozumleme():
    g = cozumle(GELEN)
    assert g.idare == "TOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ" and g.birim == "Strateji Geliştirme Daire Başkanlığı"
    assert g.sayi == "E-12345678-841-123456" and g.tarih == "05.11.2026"
    assert g.konu == "Aylıksız İzin Kullanan Personel"
    assert g.muhatap == "PERSONEL DAİRE BAŞKANLIĞINA" and g.ivedilik == "GÜNLÜDÜR"
    assert g.sure == "20.11.2026 tarihine kadar"
    assert len(g.istenenler) == 1 and "bildirilmesi" in g.istenenler[0]
    assert cevap_muhatabi(g, "TOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ") == ("Strateji Geliştirme Daire Başkanlığı", "")
    assert cevap_muhatabi(g, "BAŞKA ÜNİVERSİTE")[0] == "TOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ"


def test_kontrol_listesi_ve_sinama():
    y = Yazi(baslik=["T.C.", "X ÜNİVERSİTESİ", "Personel Daire Başkanlığı"], konu="izin. ",
             muhatap="Rektörlük Makamı", makam="ust",
             paragraflar=[Paragraf("657 sayılı Kanunun 108 inci maddesi uyarınca 12500 TL ödenir ve KBS ekte."),
                          Paragraf("Gereğini rica ederim.")],
             imza=Imza("a", "b", "c", yetki="Rektör a"))
    yapilan = duzelt(y)
    assert y.paragraflar[-1].metin == "Gereğini arz ederim." and y.konu == "İzin"
    assert any("Bitiş" in x for x in yapilan) and "12.500 TL" in y.paragraflar[0].metin
    k = {(x.baslik, x.durum) for x in kontrol_et(y, ["Kaynak metin: 657 sayılı Kanun md. 108 hükmü"])}
    assert ("Ek", "hata") in k                        # metinde ek var, ek listesi boş
    assert ("İmza", "uyari") in k                     # "Rektör a" → "Rektör a."
    assert ("Kısaltmalar", "uyari") in k              # KBS açılmamış
    hatalar = [x.mesaj for x in kontrol_et(y, ["657 sayılı Kanun md. 108"]) if x.durum == "hata"]
    assert any("12.500" in h for h in hatalar)        # tutar kaynakta yok
    assert not any("657" in h for h in hatalar)       # atıf kaynakta var


def test_sablonla_hazirlama_ve_ciktilar(kutuphane, tmp_path):
    hat = CevapHatti(kutuphane, DogrulamaMotoru(kutuphane, BIRINCIL))
    h = YaziHazirlayici(hat)
    s = h.hazirla(YaziIstegi(tur="cevap", gelen=cozumle(GELEN), profil=PROFIL,
                             talimat="Başkanlığımızda aylıksız izin kullanan personel bulunmamaktadır."))
    y = s.yazi
    assert y.muhatap == "Strateji Geliştirme Daire Başkanlığı" and y.makam == "ayni"
    assert y.ilgiler[0].sayi == "E-12345678-841-123456" and y.ilgiler[0].idare == ""
    assert y.paragraflar[0].metin.startswith("İlgi yazı ile")
    assert "Başkanlığımızda aylıksız izin kullanan personel bulunmamaktadır." in [p.metin for p in y.paragraflar]
    assert y.paragraflar[-1].metin == "Bilgilerinizi arz ederim."
    assert s.hata_sayisi == 0, [k.mesaj for k in s.kontrol if k.durum == "hata"]
    assert any(d.startswith("Anla") or "Yazı türü" in d for d in s.dusunce)
    metin = ebys_metni(y)
    assert "MUHATAP:\nSTRATEJİ GELİŞTİRME DAİRE BAŞKANLIĞINA" in metin
    assert "İLGİ:\n05.11.2026 tarihli ve E-12345678-841-123456 sayılı yazı." in metin
    assert "TASLAK" in html_onizleme(y)
    yol = docx_kaydet(y, tmp_path / "taslak.docx")
    from docx import Document
    d = Document(str(yol))
    metinler = [p.text for p in d.paragraphs]
    assert "T.C." in metinler and "TOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ" in metinler and "Personel Daire Başkanlığı" in metinler
    assert "STRATEJİ GELİŞTİRME DAİRE BAŞKANLIĞINA" in metinler and "Ahmet YILMAZ" in metinler
    bolum = d.sections[0]
    assert round(bolum.left_margin.cm, 2) == 1.5 and round(bolum.top_margin.cm, 2) == 1.5
    assert d.styles["Normal"].font.name == "Times New Roman" and d.styles["Normal"].font.size.pt == 12
    govde = next(p for p in d.paragraphs if p.text.startswith("İlgi yazı ile"))
    assert round(govde.paragraph_format.first_line_indent.cm, 2) == 1.25


class _UyduranModel:
    """İlk yazımda kaynakta olmayan bir tarih uyduran, düzeltme turunda yer tutucu kullanan sahte model."""
    hazir = True
    ad = "sahte-yazar"

    def __init__(self):
        self.turlar = 0

    def sohbet(self, mesajlar, max_tokens=900, sicaklik=0.2, json_mod=False, json_sema=None, dusunme=False, akis=None):
        sistem, kullanici = mesajlar[0]["content"], mesajlar[-1]["content"]
        if "çözümle" in sistem:
            return json.dumps({"konu": "izin", "niyet": "yazi", "personel_turu": "657/4-A memur", "olgular": [],
                               "alt_sorular": [], "terimler": ["aylıksız izin"], "eksik": [], "zorluk": "kolay"})
        if "METİN bölümünü" not in sistem:
            return json.dumps({"dogrudan_cevap": False, "kisa_cevap": [], "uygulama": [], "adimlar": [],
                               "dikkat": [], "degerlendirme": [], "guven": "hukum_yok", "acik_nokta": ""})
        assert "Başkanlığımız" in sistem and "Doğruluk" in sistem
        self.turlar += 1
        if "ÇIKARILAN CÜMLELER" in kullanici:
            return json.dumps({"konu": "", "eksik_bilgiler": ["izin süreleri"], "ekler": [], "paragraflar": [
                {"metin": "İlgi yazı ile aylıksız izin kullanan personel bilgisi istenmiştir.", "kaynaklar": []},
                {"metin": "Başkanlığımızda aylıksız izin kullanan [personel sayısı] personel bulunmaktadır.",
                 "kaynaklar": []}]})
        return json.dumps({"konu": "", "eksik_bilgiler": [], "ekler": [], "paragraflar": [
            {"metin": "İlgi yazı ile aylıksız izin kullanan personel bilgisi istenmiştir.", "kaynaklar": []},
            {"metin": "Başkanlığımızda 3 personel 01.09.2026 tarihinden itibaren izindedir.", "kaynaklar": []},
            {"metin": "Bilgilerinizi arz ederim.", "kaynaklar": []}]})


def test_model_uydurursa_sinama_cikarir_ve_duzeltir(kutuphane):
    model = _UyduranModel()
    hat = CevapHatti(kutuphane, DogrulamaMotoru(kutuphane, BIRINCIL), model=model)
    s = YaziHazirlayici(hat).hazirla(YaziIstegi(tur="cevap", gelen=cozumle(GELEN), profil=PROFIL, arastir=False))
    metinler = [p.metin for p in s.yazi.paragraflar]
    assert not any("01.09.2026" in m for m in metinler)                       # uydurulan tarih çıktı
    assert any("01.09.2026" in c["metin"] for c in s.cikarilanlar)
    assert any("[personel sayısı]" in m for m in metinler) and model.turlar == 2
    assert metinler[-1] == "Bilgilerinizi arz ederim." and metinler.count("Bilgilerinizi arz ederim.") == 1
    assert s.model_kullanildi and s.hata_sayisi == 0
    assert any("[personel sayısı]" in m for m in metinler)


def test_tek_haneli_miktar_da_sinanir():
    from akil_hocasi.yazi.kontrol import sinama
    y = Yazi(paragraflar=[Paragraf("Başkanlığımızda 3 personel izinlidir."), Paragraf("1 inci fıkra uygulanır.")])
    assert [n for n, _ in sinama(y, [])] == [0]                       # "3 personel" kaynakta yok; "1 inci" sıra sözcüğü
    assert sinama(y, ["Talimat: 3 personel izinli"]) == []


def test_bitis_ifadesi_tek_ve_sonda_kalir():
    y = Yazi(makam="ayni", paragraflar=[Paragraf("İlgi yazı ile bilgi istenmiştir."),
                                        Paragraf("Bilgilerinizi arz ederim.", tur="bitis"),
                                        Paragraf("Sonradan eklenen paragraf.")])
    duzelt(y)
    assert [p.metin for p in y.paragraflar] == ["İlgi yazı ile bilgi istenmiştir.", "Sonradan eklenen paragraf.",
                                                "Bilgilerinizi arz ederim."]


def test_istenenlerin_karsilanmasi_denetlenir():
    from akil_hocasi.yazi.kontrol import karsilaniyor_mu
    istenen = "Aylıksız izin kullanan personel sayısının ve izin sürelerinin bildirilmesi gerekmektedir."
    assert karsilaniyor_mu(istenen, "Başkanlığımızda aylıksız izin kullanan personel bulunmamaktadır.")
    assert not karsilaniyor_mu(istenen, "Bütçe teklifimiz ekte gönderilmiştir.")
    y = Yazi(baslik=["T.C.", "A", "B"], konu="x", muhatap="Rektörlük", makam="ust", istenenler=[istenen],
             paragraflar=[Paragraf("Bütçe teklifimiz hazırlanmıştır."), Paragraf("Bilgilerinizi arz ederim.")],
             imza=Imza("a", "b", "c"))
    assert any(k.baslik == "İstenenlerin karşılanması" and k.durum == "uyari" for k in kontrol_et(y, []))
