"""Sistem Rehberi: katalog, kılavuz ayrıştırma, güvenli toplama, ekran tanıma, cevapta arayüz adı doğrulaması.

Kılavuz metinleri sentetiktir (gerçek kılavuz metni değildir).
"""

import io
from urllib.parse import urlparse

import pytest

from akil_hocasi.crawler import beyaz_liste
from akil_hocasi.rehber import SistemRehberi, kullanim_sorusu_mu
from akil_hocasi.rehber.ekran import ekrani_coz
from akil_hocasi.rehber.kilavuz import (Sayfa, Satir, arayuz_adlari, ayristir, bolumlere_ayir, etiketleri_bul,
                                        kilavuz_etiketi, yollari_bul)
from akil_hocasi.rehber.sistemler import SISTEMLER, sistem, sistem_bul
from akil_hocasi.rehber.toplayici import KilavuzToplayici, adres_izinli, sistem_alani_mi

# ---------------------------------------------------------------------------- sentetik kılavuz


def _sayfalar():
    ust = Satir("Örnek Harcama Yönetim Sistemi Kullanıcı Kılavuzu", 8)
    return [
        Sayfa(1, [Satir("HARCAMA YÖNETİM SİSTEMİ", 20, True), Satir("KULLANICI KILAVUZU", 18, True),
                  Satir("Muhasebat Genel Müdürlüğü", 11), Satir("Versiyon 1.2", 11), Satir("26/03/2019", 11)]),
        Sayfa(2, [ust, Satir("İÇİNDEKİLER", 14, True), Satir("A. Sisteme Giriş ........ 3", 11),
                  Satir("B. Ödeme Emri Belgesi Oluşturma ........ 4", 11), Satir("C. Sık Hatalar ........ 5", 11),
                  Satir("D. Raporlar ........ 5", 11), Satir("Sayfa 2 / 5", 8)]),
        Sayfa(3, [ust, Satir("A. Sisteme Giriş", 14, True), Satir("1- Giriş sayfasında e-Devlet ile giriş yapılır.", 11),
                  Satir("2- Rol seçimi ekranından harcama birimi rolü seçilir.", 11), Satir("Sayfa 3 / 5", 8)]),
        Sayfa(4, [ust, Satir("B. Ödeme Emri Belgesi Oluşturma", 14, True),
                  Satir("Harcama Yönetimi > Ödeme Emri Belgesi > Yeni menüsünden işlem başlatılır.", 11),
                  Satir("1. “Ödeme Türü” alanından ödeme türü seçilir.", 11),
                  Satir("2. Kaydet butonuna basılır ve belge ekranda görüntülenir.", 11),
                  Satir("3. E-İmzaya Gönder düğmesine tıklanır.", 11), Satir("Sayfa 4 / 5", 8)]),
        Sayfa(5, [ust, Satir("C. Sık Hatalar", 14, True),
                  Satir("“Kullanıcının bu birimde yetkisi bulunmamaktadır” uyarısı alınırsa Harcama Birimi Kimlik", 11),
                  Satir("Yöneticisine başvurularak rol tanımlatılır.", 11), Satir("Sayfa 5 / 5", 8)]),
    ]


def _pdf_bayti() -> bytes:
    pytest.importorskip("reportlab")
    try:
        import fitz  # noqa: F401
    except ImportError:
        pytest.importorskip("pdfplumber")
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    import glob
    yazilar = sorted(glob.glob("/usr/share/fonts/truetype/dejavu/DejaVuSans*.ttf")
                     + glob.glob("C:/Windows/Fonts/arial*.ttf"))
    normal = next((y for y in yazilar if y.lower().endswith(("dejavusans.ttf", "arial.ttf"))), None)
    kalin = next((y for y in yazilar if y.lower().endswith(("dejavusans-bold.ttf", "arialbd.ttf"))), normal)
    if not normal:
        pytest.skip("Türkçe yazı tipi yok")
    pdfmetrics.registerFont(TTFont("TN", normal))
    pdfmetrics.registerFont(TTFont("TB", kalin))
    tampon = io.BytesIO()
    c = canvas.Canvas(tampon, pagesize=A4)
    for s in _sayfalar():
        y = 800
        for x in s.satirlar:
            c.setFont("TB" if x.kalin else "TN", x.boyut)
            c.drawString(50, y, x.metin)
            y -= x.boyut + 8
        c.showPage()
    c.save()
    return tampon.getvalue()


# ---------------------------------------------------------------------------- katalog


def test_katalog_adresleri_ve_tohumlar_guvenli():
    kimlikler = [s.kimlik for s in SISTEMLER]
    assert len(kimlikler) == len(set(kimlikler))
    for gerekli in ("EBYS", "MYS", "KBS", "HITAP", "SGK", "YOKSIS", "PBS", "EKAP", "KARIYER", "OSYM", "TOGU"):
        assert sistem(gerekli) is not None
    for s in SISTEMLER:
        if s.adres:
            assert s.adres.startswith("https://")
        for t in s.tohumlar:                       # tohumlar yalnız resmî (beyaz liste) alanlarda
            assert beyaz_liste.kilavuz_izinli_mi(t), t
            assert adres_izinli(t, s, tohum=True), t


def test_sistem_bul_ve_kullanim_sorusu():
    assert sistem_bul("ebys.gop.edu.tr Ana Sayfa Evrak Yaz Kurum İçi Gidecek Evrak")[0][0].kimlik == "EBYS"
    assert sistem_bul("Hizmet Takip Programı — Hizmet Cetveli")[0][0].kimlik == "HITAP"
    assert sistem_bul("mysv2.hmb.gov.tr Ödeme Emri Belgesi")[0][0].kimlik == "MYS"
    assert not sistem_bul("kbsx tablosu")          # kısa kısaltma yalnız bütün sözcük olarak sayılır
    s, kalip = kullanim_sorusu_mu("KBS'de ek ders bordrosu nasıl hazırlanır?")
    assert s.kimlik == "KBS" and kalip
    s, kalip = kullanim_sorusu_mu("Aylıksız izin süresi ne kadardır?")
    assert s is None


# ---------------------------------------------------------------------------- ayrıştırma


def test_bolumlere_ayirma_basliklar_adimlar_etiketler_yollar():
    bolumler = bolumlere_ayir(_sayfalar())
    basliklar = [b.baslik for b in bolumler]
    assert basliklar[:3] == ["A. Sisteme Giriş", "B. Ödeme Emri Belgesi Oluşturma", "C. Sık Hatalar"]
    tum = "\n".join(b.metin for b in bolumler)
    assert "Kullanıcı Kılavuzu" not in tum and "Sayfa 3 / 5" not in tum      # üst/alt bilgi atıldı
    assert "........" not in tum                                              # içindekiler atıldı
    oeb = bolumler[1]
    assert oeb.no == "4"
    assert oeb.yollar == ["Harcama Yönetimi > Ödeme Emri Belgesi > Yeni"]
    assert {"Ödeme Türü", "Kaydet", "E-İmzaya Gönder"} <= set(oeb.etiketler)
    assert len(oeb.adimlar) == 4 and oeb.adimlar[1].startswith("“Ödeme Türü”")


def test_pdf_kilavuzu_ayristirilir():
    b = ayristir(_pdf_bayti(), "hys_kilavuz.pdf")
    o = b.ozet()
    assert o["tur"] == "pdf" and o["sayfa"] == 5 and not o["taranmis"]
    assert b.yayimlayan == "Muhasebat Genel Müdürlüğü" and b.tarih == "26/03/2019" and b.surum == "1.2"
    assert any(x.baslik.startswith("B. Ödeme Emri") and x.no == "4" for x in b.bolumler)


def test_html_ve_docx_kilavuz():
    html = ("<html><body><nav>Menü</nav><h2>Kurum Dışı Gidecek Evrak Yaz</h2>"
            "<p>Ana Sayfa >> Kısayollar >> Evrak Yaz menüsü kullanılır.</p>"
            "<ol><li>“Evrakın Gittiği Yer” alanı seçilir.</li><li>E-İmzaya Sun butonuna basılır.</li></ol>"
            "<h2>Sık Sorulan Sorular</h2><p>İmza sırasında “paket özet bilgisi alınamadı” hatası alınırsa ek adındaki "
            "çift tırnak kaldırılır.</p></body></html>").encode()
    b = ayristir(html, "sss.html")
    assert b.tur == "html" and b.bolumler[0].no == "b1"
    assert "Ana Sayfa > Kısayollar > Evrak Yaz" in b.bolumler[0].yollar
    assert "E-İmzaya Sun" in b.bolumler[0].etiketler
    docx = pytest.importorskip("docx")
    belge = docx.Document()
    belge.add_heading("Hizmet Cetveli Girişi", level=1)
    belge.add_paragraph("1. Hizmet Bilgileri sekmesine tıklanır.")
    belge.add_paragraph("2. Kaydet düğmesine basılır ve kayıt listede görüntülenir.")
    tampon = io.BytesIO()
    belge.save(tampon)
    b = ayristir(tampon.getvalue(), "hitap.docx")
    assert b.tur == "docx" and b.bolumler[0].baslik == "Hizmet Cetveli Girişi"
    assert "Kaydet" in b.bolumler[0].etiketler


def test_etiket_yol_ve_cevap_adlari():
    assert "Personel Listesi Yenile" in etiketleri_bul("Açılan ekranda Personel Listesi Yenile butonuna basılır.")
    assert yollari_bul("ilgili harcama biriminin KBS Saymanlık İşlemleri>Saymanlık Memur Maaş İşlemleri ekranından") == [
        "KBS Saymanlık İşlemleri > Saymanlık Memur Maaş İşlemleri"]
    adlar = arayuz_adlari("Personel İşlemleri > Özgeçmiş İşlemleri menüsünden “Kişisel Bilgiler” düğmesine basın.")
    assert {"Personel İşlemleri", "Özgeçmiş İşlemleri", "Kişisel Bilgiler"} <= set(adlar)
    assert arayuz_adlari("KBS'de işlem 'Maaş' menüsünden yapılır.") == []      # kesme işareti tırnak sayılmaz
    assert kilavuz_etiketi("EBYS Sunumu", "12", "Olur Evrakı Yaz") == "EBYS Sunumu, s. 12 (Olur Evrakı Yaz)"
    assert kilavuz_etiketi("SSS", "b3") == "SSS, bölüm 3"


# ---------------------------------------------------------------------------- güvenli toplama


def test_adres_kurallari():
    kbs, hitap = sistem("KBS"), sistem("HITAP")
    assert sistem_alani_mi("https://www.kbs.gov.tr/x") and sistem_alani_mi("https://ebys.gop.edu.tr/")
    assert not sistem_alani_mi("https://ebysyardim.gop.edu.tr/")
    assert not adres_izinli("https://www.kbs.gov.tr/gen/login.htm", kbs)                 # giriş sayfası
    assert not adres_izinli("https://www.kbs.gov.tr/TMYS/uygulama", kbs)                 # sistem sayfası
    assert adres_izinli("https://www.kbs.gov.tr/kilavuz/ekders.pdf", kbs)                # statik belge
    assert adres_izinli("https://hitap.sgk.gov.tr/HitapWeb/dosyalar/kilavuz.pdf", hitap)
    assert not adres_izinli("https://ornek-forum.com/kilavuz.pdf", kbs)                  # beyaz liste dışı
    assert not adres_izinli("https://www.sgk.gov.tr/logout", kbs)
    assert adres_izinli("https://www.osym.gov.tr/kpss-kilavuz", sistem("OSYM"))          # kılavuz için ek alan
    assert not beyaz_liste.izinli_mi("https://www.osym.gov.tr/")                          # genel taramaya girmez


class _Yanit:
    def __init__(self, durum, icerik=b"", basliklar=None, url=""):
        self.status_code, self._icerik, self.headers, self.url = durum, icerik, basliklar or {}, url
        self.text = icerik.decode("utf-8", "ignore")

    def iter_content(self, n):
        for i in range(0, len(self._icerik), n):
            yield self._icerik[i:i + n]


class _Oturum:
    def __init__(self, sayfalar):
        self.sayfalar, self.headers, self.istekler = sayfalar, {}, []

    def get(self, url, headers=None, timeout=None, stream=False):
        self.istekler.append(url)
        if url.endswith("/robots.txt") or url not in self.sayfalar:
            return _Yanit(404, url=url)
        icerik, etag, tur = self.sayfalar[url]
        if headers and headers.get("If-None-Match") == etag:
            return _Yanit(304, url=url)
        return _Yanit(200, icerik, {"ETag": etag, "Content-Type": tur}, url=url)


def test_toplayici_yalniz_guvenli_belgeleri_alir(tmp_path, kutuphane):
    from akil_hocasi.crawler.depo import BelgeDeposu
    from akil_hocasi.crawler.indirici import Indirici

    html = ("<html><body>"
            "<a href='/depo/ebys_kullanim_kilavuzu.html'>EBYS Kullanım Kılavuzu</a>"
            "<a href='https://ebys.gop.edu.tr/giris'>EBYS Giriş</a>"
            "<a href='https://ebys.gop.edu.tr/Login.aspx'>Sisteme gir</a>"
            "<a href='/haberler'>Haberler</a>"
            "<a href='https://ornek-forum.com/ebys-kilavuz.pdf'>EBYS kılavuz (forum)</a>"
            "<a href='/depo/parola.html'>EBYS yardım kılavuzu (oturum)</a>"
            "</body></html>").encode()
    kilavuz = ("<html><body><h2>Olur Evrakı Yaz</h2><p>Ana Sayfa >> Kısayollar >> Evrak Yaz >> Olur Evrakı Yaz</p>"
               "<ol><li>“Gönderilen Makam” alanı seçilir.</li><li>E-İmzaya Sun butonuna basılır.</li></ol>"
               "<h2>Kurum Dışı Gelen Evrak</h2><ol><li>Tara ve Ekle butonuna basılır.</li>"
               "<li>“Evrak Tarihi” alanı doldurulur.</li></ol></body></html>").encode()
    parola = b"<html><form><input type='password' name='p'></form><p>EBYS kullanim kilavuzu gizli</p></html>"
    kok = "https://ebysyardim.gop.edu.tr/"
    oturum = _Oturum({kok: (html, "e1", "text/html"),
                      kok + "depo/ebys_kullanim_kilavuzu.html": (kilavuz, "k1", "text/html"),
                      kok + "depo/parola.html": (parola, "p1", "text/html")})
    t = KilavuzToplayici(kutuphane, BelgeDeposu(tmp_path / "depo"), Indirici(0, oturum=oturum))
    rapor = t.topla(["EBYS"])
    istenen = {u for u in oturum.istekler if not u.endswith("robots.txt")}
    assert not any(urlparse(u).hostname == "ebys.gop.edu.tr" for u in istenen)          # sisteme hiç gidilmedi
    assert not any("ornek-forum" in u for u in istenen)
    assert rapor.yeni == 1, rapor.belgeler
    kilavuzlar = kutuphane.belgeleri_listele("KLV:EBYS:")
    assert len(kilavuzlar) == 1 and kilavuzlar[0]["bolum"] >= 2
    assert not kutuphane.ara("gizli", turler=("kilavuz",))                               # parolalı sayfa saklanmadı
    # ikinci tur: değişmeyen kılavuz yeniden işlenmez
    rapor2 = t.topla(["EBYS"])
    assert rapor2.yeni == 0 and rapor2.guncellenen == 0


# ---------------------------------------------------------------------------- rehber, ekran, cevap


def _rehber(kutuphane, tmp_path):
    from akil_hocasi.crawler.depo import BelgeDeposu
    r = SistemRehberi(kutuphane, BelgeDeposu(tmp_path / "depo"))
    html = ("<html><body><h1>Harcama Yönetim Sistemi Kılavuzu</h1>"
            "<h2>Ödeme Emri Belgesi Oluşturma</h2><p>Harcama Yönetimi > Ödeme Emri Belgesi > Yeni menüsü açılır.</p>"
            "<ol><li>“Ödeme Türü” alanından tür seçilir.</li><li>Kaydet butonuna basılır.</li>"
            "<li>E-İmzaya Gönder düğmesine tıklanır.</li></ol>"
            "<h2>Sık Karşılaşılan Hatalar</h2><p>“Kullanıcının bu birimde yetkisi bulunmamaktadır” uyarısı alınırsa "
            "Harcama Birimi Kimlik Yöneticisine başvurularak MYSV2 rolü tanımlatılır.</p></body></html>").encode()
    sonuc = r.toplayici().dosya_ekle(html, "hys_kilavuz.html")
    assert sonuc["sonuc"] == "yeni" and sonuc["sistem"] == "MYS"
    return r


def test_rehber_arama_sik_islemler(kutuphane, tmp_path):
    r = _rehber(kutuphane, tmp_path)
    bolumler = r.ara("MYS'de ödeme emri belgesi nasıl oluşturulur?")
    assert bolumler and bolumler[0].baslik == "Ödeme Emri Belgesi Oluşturma"
    assert bolumler[0].etiket.endswith("bölüm 1 (Ödeme Emri Belgesi Oluşturma)")
    assert any(i["baslik"] == "Ödeme Emri Belgesi Oluşturma" for i in r.sik_islemler("MYS"))
    d = {x["kimlik"]: x for x in r.sistemler()}
    assert d["MYS"]["kilavuz"] == 1 and d["EBYS"]["kilavuz"] == 0
    assert not kutuphane.ara("ödeme emri", turler=("kanun",))                            # tür süzgeci


def test_ekran_tanima_maskeler_ve_bolum_bulur(kutuphane, tmp_path):
    r = _rehber(kutuphane, tmp_path)
    ocr = ("https://mysv2.hmb.gov.tr/harcama\nHarcama Yönetim Sistemi\nÖdeme Emri Belgesi\nTC Kimlik: 12345678950\n"
           "Kullanıcının bu birimde yetkisi bulunmamaktadır\nKaydet")
    a = r.ekran(ocr)
    assert a.sistem.kimlik == "MYS" and "mysv2.hmb.gov.tr" in a.adresler
    assert "12345678950" not in a.metin
    assert a.hatalar == ["Kullanıcının bu birimde yetkisi bulunmamaktadır"]
    assert a.bolumler and a.bolumler[0].baslik == "Sık Karşılaşılan Hatalar"
    assert "yetkisi bulunmamaktadır" in a.soru_onerisi() and a.soru_onerisi().startswith("MYS (HYS) ekranında")
    bos = ekrani_coz("Merhaba dünya")
    assert not bos.tanindi and bos.soru_onerisi() == "Ekranda takıldım. Sonraki adım nedir?"


def test_dogrulama_kilavuzda_olmayan_dugmeyi_cikarir(kutuphane, tmp_path):
    from akil_hocasi.answer.dogrulama import DogrulamaMotoru
    from akil_hocasi.answer.modeller import Cevap, Cumle, Kaynak
    r = _rehber(kutuphane, tmp_path)
    p = r.ara("ödeme emri belgesi oluşturma", "MYS")[0]
    c = Cevap(soru="MYS'de ÖEB nasıl oluşturulur?", kaynaklar=[Kaynak("K1", p)])
    c.kisa_cevap = [Cumle("Harcama Yönetimi > Ödeme Emri Belgesi > Yeni menüsünden işlem başlatılır.", ["K1"])]
    c.adimlar = [Cumle("“Ödeme Türü” alanından tür seçilir ve “Kaydet” butonuna basılır.", ["K1"], "adim"),
                 Cumle("“Onayla” düğmesine basılır.", ["K1"], "adim"),                             # kılavuzda yok
                 Cumle("Harcama Yönetimi > Onay İşlemleri menüsü açılır.", ["K1"], "adim")]        # yol uydurma
    DogrulamaMotoru(kutuphane, beyaz_liste.BIRINCIL).dogrula(c)
    kalan = [x.metin for x in c.adimlar]
    assert kalan == ["“Ödeme Türü” alanından tür seçilir ve “Kaydet” butonuna basılır."]
    assert c.kisa_cevap and sum(u.test == "Arayüz" for u in c.uyarilar) == 2


def test_hat_kullanim_sorusunda_kilavuzu_kaynak_yapar(kutuphane, tmp_path):
    from akil_hocasi.answer.dogrulama import DogrulamaMotoru
    from akil_hocasi.answer.hat import KILAVUZ_EKI, CevapHatti, sentez_gorevi
    r = _rehber(kutuphane, tmp_path)
    hat = CevapHatti(kutuphane, DogrulamaMotoru(kutuphane, beyaz_liste.BIRINCIL), rehber=r)
    c = hat.cevapla("MYS'de ödeme emri belgesi nasıl oluşturulur?", kayit=False)
    assert any(k.pasaj.belge_turu == "kilavuz_yerel" for k in c.kaynaklar)
    assert sentez_gorevi(c.kaynaklar).endswith(KILAVUZ_EKI)
    # mevzuat sorusunda kılavuz öne alınmaz
    c2 = hat.cevapla("Aylıksız izin ne kadar verilebilir?", kayit=False)
    assert c2.kaynaklar and c2.kaynaklar[0].pasaj.belge_turu != "kilavuz_yerel"
