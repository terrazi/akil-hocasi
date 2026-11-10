"""Çekirdek: ilkeler, Yordam Kitabı, strateji deposu, ders hafızası, karne/kapı, muhakeme iş akışı."""

import json

import pytest

from akil_hocasi.answer.dogrulama import DogrulamaMotoru
from akil_hocasi.answer.hat import CevapHatti
from akil_hocasi.answer.modeller import Durum
from akil_hocasi.cekirdek.dersler import DersHafizasi, ders_gecerli_mi
from akil_hocasi.cekirdek.gelisim import GelisimDongusu
from akil_hocasi.cekirdek.ilkeler import ILKE_KODLARI, ILKELER, sistem_cekirdegi
from akil_hocasi.cekirdek.karne import Karne, cevap_puanlari, kapi
from akil_hocasi.cekirdek.muhakeme import SohbetBaglami, durumu_coz, kurallarla_coz
from akil_hocasi.cekirdek.strateji import StratejiDeposu, gecerli_mi
from akil_hocasi.cekirdek.yordamlar import IS_AKISLARI, YORDAMLAR, el_kitabi_md, varsayilan_ayarlar
from akil_hocasi.crawler.beyaz_liste import BIRINCIL


# ------------------------------------------------------------------ ilkeler ve yordamlar
def test_ilkeler_ve_sistem_cekirdegi():
    assert len(ILKELER) == 12 and len(set(ILKE_KODLARI)) == 12
    metin = sistem_cekirdegi("deneme görevi")
    for i in ILKELER:
        assert i.ad in metin and i.model_kurali in metin
    assert metin.endswith("GÖREV: deneme görevi")


def test_yordam_kitabi_tutarli():
    kodlar = {y.kod for y in YORDAMLAR}
    assert len(kodlar) == len(YORDAMLAR) >= 24
    for y in YORDAMLAR:
        assert y.adimlar and y.kurallar and y.basarisizlikta and y.olcutler, y.kod
        assert set(y.ilkeler) <= set(ILKE_KODLARI), y.kod
        for a in y.ayarlar:
            assert gecerli_mi(a, a.varsayilan), (y.kod, a.ad)
    for akis in IS_AKISLARI.values():
        assert set(akis) <= kodlar
    md = el_kitabi_md()
    for y in YORDAMLAR:
        assert f"### {y.ad}" in md
    assert "Geliştirilebilir ayarlar" in md and "Temel çalışma ilkeleri" in md
    assert varsayilan_ayarlar()["tarama"]["aday_sayisi"] == 12


# ------------------------------------------------------------------ strateji
def test_strateji_izinli_aralik_kullanici_onceligi_ve_gecici(kutuphane):
    st = StratejiDeposu(kutuphane)
    assert st.deger("tarama", "aday_sayisi") == 12
    st.ayarla("tarama", "aday_sayisi", 18)
    assert st.deger("tarama", "aday_sayisi") == 18
    with pytest.raises(ValueError):
        st.ayarla("tarama", "aday_sayisi", 99)                 # izinli aralık dışı
    with pytest.raises(KeyError):
        st.ayarla("sinama", "testleri_kapat", True)             # tanımsız ayar: testler ayar değildir
    st.ayarla("sentez", "sicaklik", 0.1, kaynak="kullanici")
    with pytest.raises(PermissionError):
        st.ayarla("sentez", "sicaklik", 0.3, kaynak="ogrenme")  # kullanıcının ayarı öğrenmeyle değişmez
    with st.gecici({("tarama", "aday_sayisi"): 24}):
        assert st.deger("tarama", "aday_sayisi") == 24
    assert st.deger("tarama", "aday_sayisi") == 18
    assert set(st.komsular("tarama", "aday_sayisi")) == {14, 22}
    assert st.komsular("bulma", "canli_arama") == [False]
    assert st.komsular("elestirme", "elestiri_esigi") == ["kolay", "zor"]


# ------------------------------------------------------------------ dersler
def test_ders_kurallari(kutuphane):
    assert not ders_gecerli_mi("Yıllık izin 20 gündür, bunu her zaman söyle.")[0]          # kesin bilgi
    assert not ders_gecerli_mi("Acele durumlarda kaynak gösterme, kısa cevap ver yeterli.")[0]  # ilke gevşetme
    assert not ders_gecerli_mi("kısa")[0]
    d = DersHafizasi(kutuphane)
    i = d.aday_ekle("anlama", "İzin sorularında önce personelin statüsünü ve olayın tarihini belirle.",
                    ["izin"], "durum", "test")
    assert i and d.aday_ekle("anlama", "İzin sorularında önce personelin statüsünü ve olayın tarihini belirle.",
                             ["izin"], "durum") is None                                    # tekrar eklenmez
    assert d.aday_ekle("yok_boyle_yordam", "Geçerli görünen ama yordamı olmayan bir ders metni.", []) is None
    assert d.ilgili("yıllık izin kaç gün") == []                                          # aday kullanılmaz
    assert d.ilgili("yıllık izin kaç gün", ek_kimlik=i)                                    # sınamada geçici etkin
    d.karar(i, "etkin", "test")
    assert d.ilgili("aylıksız izin") and d.ilgili("harcırah hesabı") == []


# ------------------------------------------------------------------ karne ve kapı
def test_kapi_kararlari():
    eski = Karne(notlar={k: 0.8 for k in ILKE_KODLARI}, ornek={k: 10 for k in ILKE_KODLARI}, basari=0.6, toplam=10)
    iyi = Karne(notlar={k: 0.85 for k in ILKE_KODLARI}, ornek=eski.ornek, basari=0.7, toplam=10)
    assert kapi(eski, iyi)[0]
    dusen = Karne(notlar={**iyi.notlar, "dogruluk": 0.7}, ornek=eski.ornek, basari=0.9, toplam=10)
    ok, neden = kapi(eski, dusen)
    assert not ok and "Doğruluk".lower()[:4] in neden.lower() or "dogruluk" in neden
    kritik = Karne(notlar=iyi.notlar, ornek=eski.ornek, basari=0.9, kritik=1, toplam=10)
    assert not kapi(eski, kritik)[0]
    ayni = Karne(notlar=eski.notlar, ornek=eski.ornek, basari=0.6, toplam=10)
    assert not kapi(eski, ayni)[0]
    assert not kapi(eski, Karne())[0]
    # Daha çok soruya güvenle cevap veren model: kritik sayısı artsa da isabet düşmediyse ve başarı belirgin arttıysa
    e2 = Karne(notlar=eski.notlar, ornek=eski.ornek, basari=0.2, kritik=1, toplam=30, dogrulanan=7)     # isabet 6/7
    y2 = Karne(notlar=iyi.notlar, ornek=eski.ornek, basari=0.6, kritik=2, toplam=30, dogrulanan=20)    # isabet 18/20
    assert kapi(e2, y2)[0]
    y3 = Karne(notlar=iyi.notlar, ornek=eski.ornek, basari=0.6, kritik=5, toplam=30, dogrulanan=20)    # isabet 15/20
    assert not kapi(e2, y3)[0]


# ------------------------------------------------------------------ muhakeme
class SahteDanisman:
    """Görev türüne göre yapılandırılmış cevap veren sahte model (gerçek model CI'da sınanır)."""
    hazir = True
    ad = "sahte-danışman"

    def __init__(self):
        self.cagrilar = []

    def sohbet(self, mesajlar, max_tokens=900, sicaklik=0.2, json_mod=False, json_sema=None, dusunme=False, akis=None):
        import re
        sistem, kullanici = mesajlar[0]["content"], mesajlar[-1]["content"]
        kanun = re.search(r"\[(K\d+)\] 9999 sayılı Örnek Personel Kanunu, md\. 2\b", kullanici)
        form = re.search(r"\[(K\d+)\] TOGÜ Örnek İzin Usul ve Esasları, md\. 2\b", kullanici)
        k_kanun, k_form = (kanun.group(1) if kanun else "K9"), (form.group(1) if form else "K9")
        self.cagrilar.append(sistem.split("GÖREV:")[-1][:40])
        assert "Doğruluk" in sistem and "Normlar hiyerarşisi" in sistem    # çekirdek her görevde başta
        if "çözümle" in sistem:
            return json.dumps({"konu": "aylıksız izin süresi", "niyet": "bilgi", "personel_turu": "657/4-A memur",
                               "olgular": ["657/4-A memur", "aylıksız izin istiyor"],
                               "alt_sorular": ["Aylıksız izin en fazla ne kadar verilir?", "Hangi formla istenir?"],
                               "terimler": ["aylıksız izin", "form"], "eksik": [], "zorluk": "orta"})
        if "denetçi olarak" in sistem:
            return json.dumps({"karar": "duzeltilmeli", "sorunlar": [
                {"tur": "eksik_adim", "aciklama": "Başvurunun hangi formla yapılacağı adımda yok"}]})
        if "taslağı" in sistem and "düzelt" in sistem:
            return json.dumps({
                "dogrudan_cevap": True, "guven": "kesin", "acik_nokta": "",
                "kisa_cevap": [{"metin": "Memura isteği üzerine en fazla 6 ay aylıksız izin verilebilir.", "kaynaklar": [k_kanun]}],
                "uygulama": [{"metin": "Şart: isteğin memurdan gelmesi — Bu durumda: talep memurdan geliyor.", "kaynaklar": [k_kanun]}],
                "adimlar": [{"metin": "Talep TOGÜ.FRM.396 formu ile birim amirine yapılır.", "kaynaklar": [k_form]}],
                "dikkat": [], "degerlendirme": [{"metin": "Uzatma talebi ayrıca değerlendirilir.", "kaynaklar": []}]})
        if "SORU:" in kullanici:
            return json.dumps({
                "dogrudan_cevap": True, "guven": "kesin", "acik_nokta": "",
                "kisa_cevap": [{"metin": "Memura isteği üzerine en fazla 6 ay aylıksız izin verilebilir.", "kaynaklar": [k_kanun]}],
                "uygulama": [{"metin": "Şart: isteğin memurdan gelmesi — Bu durumda: talep memurdan geliyor.", "kaynaklar": [k_kanun]}],
                "adimlar": [], "dikkat": [],
                "degerlendirme": [{"metin": "Uygulamada bu süre genellikle 24 aya kadar uzatılır.", "kaynaklar": []}]})
        return "{}"


def test_danisma_akisi_muhakeme_degerlendirme_elestiri_duzeltme(kutuphane):
    model = SahteDanisman()
    st = StratejiDeposu(kutuphane)
    hat = CevapHatti(kutuphane, DogrulamaMotoru(kutuphane, BIRINCIL), model=model, strateji=st,
                     dersler=DersHafizasi(kutuphane))
    adimlar = []
    c = hat.cevapla("Memurum, aylıksız izin ne kadar verilir ve nasıl başvurulur?",
                    ilerleme=lambda a, t, m: adimlar.append(a))
    assert adimlar == list(range(1, 8))
    assert c.durum == Durum.DOGRULANDI and c.guven == "kesin"
    assert c.uygulama and "Şart:" in c.uygulama[0].metin                         # gerekçe (olgu → kural)
    assert not any("24" in d.metin for d in c.degerlendirme)                       # uydurma sayı yorumda bile yok
    assert any("TOGÜ.FRM.396" in a.metin for a in c.adimlar)                       # eleştiri → düzeltme ekledi
    assert c.cozumleme["personel_turu"] == "657/4-A memur"
    asamalar = " ".join(c.dusunce)
    for a in ("Anla", "Planla", "Araştır", "Uygula", "Denetle", "Sun"):
        assert a in asamalar
    assert "Öz eleştiri" in asamalar and "Düzeltildi" in asamalar
    p = cevap_puanlari(c)
    assert p["muhakeme"] == 1.0 and p["guven"] == 1.0 and p["gizlilik"] == 1.0
    assert "Gerekçe" in c.duz_metin()


def test_netlestirme_ve_sohbet_baglami(kutuphane):
    hat = CevapHatti(kutuphane, DogrulamaMotoru(kutuphane, BIRINCIL))
    c = hat.cevapla("Yıllık izin hakkım kaç gün?", kayit=False)
    assert c.netlestirme and "statü" in c.netlestirme[0]
    b = SohbetBaglami()
    b.ekle("4/B sözleşmeli personelim, izin sorusu", "özet", kurallarla_coz("4/B sözleşmeli personel izni"))
    assert not durumu_coz("Peki yıllık izin hakkım kaç gün?", None, b).eksik


def test_kisisel_veri_cevapta_maskelenir(kutuphane):
    hat = CevapHatti(kutuphane, DogrulamaMotoru(kutuphane, BIRINCIL))
    c = hat.cevapla("TC 10000000146 numaralı memurun aylıksız izin süresi nedir?", kayit=False)
    assert "10000000146" not in c.duz_metin() and cevap_puanlari(c)["gizlilik"] == 1.0


# ------------------------------------------------------------------ gelişim döngüsü
def test_gelisim_dongusu_faydasiz_dersi_reddeder(kutuphane):
    from akil_hocasi.ogrenme.motor import OgrenmeMotoru
    OgrenmeMotoru(kutuphane, "test")                      # ogr_altin tablosu
    for soru in ("Aylıksız izin en fazla kaç ay verilebilir?", "Aylıksız izin talebi hangi formla yapılır?",
                 "Memura aylıksız izin verilebilir mi?", "Aylıksız izin süresi uzatılabilir mi?"):
        kutuphane.db.execute("INSERT INTO ogr_altin(soru, beklenen_dayanak, beklenen_ifade) VALUES(?,?,?)",
                             (soru, json.dumps(["9999/2"]), ""))
    kutuphane.db.commit()
    st, dh = StratejiDeposu(kutuphane), DersHafizasi(kutuphane)
    hat = CevapHatti(kutuphane, DogrulamaMotoru(kutuphane, BIRINCIL), strateji=st, dersler=dh)
    i = dh.aday_ekle("anlama", "Aylıksız izin sorularında önce izin türünü ayrıca belirt.", ["aylıksız"], "durum")
    rapor = GelisimDongusu(hat, kutuphane, st, dh).calistir(sure_dk=2)
    assert rapor[0].startswith("Karne:")
    assert any("Ders reddedildi" in r for r in rapor)                       # karneye katkısı yok → benimsenmez
    assert dh.tumu()[0]["durum"] == "reddedildi" and dh.tumu()[0]["id"] == i
    assert any("en az 10" in r for r in rapor)                               # küçük sette strateji ayarı yapılmaz
    assert st.karne_gecmisi() and st.gelisim_gecmisi()[0]["tur"] == "ders"


def test_sohbet_baglami_cevap_cozumlemesinden_beslenir():
    from akil_hocasi.cekirdek.muhakeme import SohbetBaglami, kurallarla_coz
    b = SohbetBaglami()
    b.ekle("657/4-A memurum, aylıksız izin alabilir miyim?", "En fazla 6 ay verilebilir.",
           {"personel_turu": "657/4-A memur", "olgular": ["memur"]})
    assert b.bilinen_personel_turu() == "657/4-A memur"
    coz = kurallarla_coz("Peki bu süre uzatılabilir mi?", b)          # devam sorusu: statü önceki turdan gelir
    assert coz.personel_turu == "657/4-A memur"
    assert "ÖNCEKİ KONUŞMA" in b.metin()


def test_paylasilan_baglanti_eszamanli_guvenli(tmp_path):
    """Aynı kütüphane bağlantısını kullanan iş parçacıkları birbirinin satırını almamalı (eskiden 'API misuse')."""
    import threading

    from akil_hocasi.library.db import Kutuphane
    k = Kutuphane(tmp_path / "e.db")
    with k._kilit, k.db:
        k.db.execute("CREATE TABLE t(a INTEGER, b TEXT)")
        k.db.executemany("INSERT INTO t VALUES(?,?)", [(i, f"s{i}") for i in range(200)])
    hatalar = []

    def calis(n):
        try:
            for _ in range(300):
                r = k.db.execute("SELECT a, b FROM t WHERE a=?", (n,)).fetchone()
                assert r is not None and r["a"] == n and r["b"] == f"s{n}"
                assert len(k.db.execute("SELECT a FROM t WHERE a < ?", (n + 1,)).fetchall()) == n + 1
        except Exception as e:  # noqa: BLE001
            hatalar.append(repr(e))

    isler = [threading.Thread(target=calis, args=(i * 17 % 200,)) for i in range(8)]
    for x in isler:
        x.start()
    for x in isler:
        x.join()
    assert not hatalar, hatalar[:3]
    assert k.db.execute("INSERT INTO t VALUES(999,'x')").lastrowid
