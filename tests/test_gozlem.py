"""Tarayıcı gözlemcisi: değerlendirme kararları ve yerel sunucu güvenliği."""

import json
import socket
import urllib.error
import urllib.request

import pytest
from conftest import ORNEK_KANUN

from akil_hocasi.gozlem.degerlendirici import (
    GozlemDegerlendirici,
    maskele,
    siniflandir,
    sistem_mi,
)
from akil_hocasi.gozlem.sunucu import GozlemSunucusu

SAYFA_METNI = ("Personel Daire Başkanlığı duyurusu. Akademik ve idari personelin yıllık izin talepleri "
               "birim amirinin onayından sonra Personel Daire Başkanlığına iletilir. Başvurular dilekçe ile "
               "yapılır ve izin süresi hizmet süresine göre belirlenir. Ayrıntılı bilgi için birim "
               "personel işleri sorumlusuna başvurunuz. Bu duyuru bilgilendirme amaçlıdır.")


@pytest.fixture
def d(kutuphane):
    return GozlemDegerlendirici(kutuphane)


@pytest.mark.parametrize("url", [
    "https://www.turkiye.gov.tr/memur-maas-bordro",
    "https://kbs.muhasebat.gov.tr/",
    "https://ebys.gop.edu.tr/envision/",
    "https://obs.gop.edu.tr/",
    "https://portal.gop.edu.tr/duyuru",
    "https://personel.gop.edu.tr/giris",
    "https://hitap.sgk.gov.tr/",
    "https://ekap.kik.gov.tr/EKAP/",
    "https://kalite.gop.edu.tr/login?next=/",
])
def test_kamu_sistemleri_gozlenmez(url):
    assert sistem_mi(url)


@pytest.mark.parametrize("url", [
    "https://ebysyardim.gop.edu.tr/mevzuat",
    "https://kalite.gop.edu.tr/formlar",
    "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=657&MevzuatTur=1&MevzuatTertip=5",
    "https://www.resmigazete.gov.tr/eskiler/2025/01/20250101.htm",
])
def test_herkese_acik_resmi_sayfalar_serbest(url):
    assert not sistem_mi(url)


def test_maskeleme():
    m = maskele("TC 10000000146, tel 0532 123 45 67, kart 4111 1111 1111 1111, IBAN TR33 0006 1005 1978 6457 8413 26")
    assert "10000000146" not in m and "123 45 67" not in m and "4111 1111" not in m and "6457" not in m
    assert "[CEP TELEFONU]" in m and "[KART NO]" in m


def test_siniflandirma():
    assert siniflandir(ORNEK_KANUN, 0) == "mevzuat"
    assert siniflandir("Formlar: TOGÜ.FRM.001 TOGÜ.FRM.002 TOGÜ.FRM.003", 0) == "liste"
    assert siniflandir(SAYFA_METNI, 0) == "sayfa"


def test_oturumlu_sayfa_reddedilir(d):
    s = d.degerlendir({"url": "https://personel.gop.edu.tr/duyuru", "metin": SAYFA_METNI, "parola_alani": True})
    assert s["karar"] == "ret" and "oturum" in s["neden"]


def test_beyaz_liste_disi_reddedilir(d):
    s = d.degerlendir({"url": "https://ornek-blog.com/izin", "metin": SAYFA_METNI})
    assert s["karar"] == "ret" and "beyaz liste" in s["neden"]


def test_ikincil_site_yalniz_ipucu(d):
    metin = "Aylıksız izin süresi uzatılabilir mi?\nUzun bir haber metni burada yer alır.\n" * 3
    s = d.degerlendir({"url": "https://www.memurlar.net/haber/1", "baslik": "Aylıksız izin", "metin": metin})
    assert s["karar"] == "ipucu"
    assert d.k.db.execute("SELECT COUNT(*) FROM belgeler WHERE kimlik LIKE 'WEB:%memurlar%'").fetchone()[0] == 0
    sorular = json.loads(d.k.db.execute("SELECT sorular FROM gozlem_ipucu").fetchone()[0])
    assert sorular == ["Aylıksız izin süresi uzatılabilir mi?"]


def test_birincil_sayfa_kutuphaneye_girer_ve_surumlenir(d):
    url = "https://personel.gop.edu.tr/duyurular/izin"
    s = d.degerlendir({"url": url, "baslik": "İzin duyurusu", "metin": SAYFA_METNI + " İletişim: 0532 123 45 67"})
    assert s["karar"] == "kabul" and s["sinif"] == "sayfa"
    metin = d.k.db.execute("SELECT metin FROM maddeler m JOIN belgeler b ON b.id=m.belge_id WHERE b.kimlik=?",
                           (s["kimlik"],)).fetchone()[0]
    assert "0532" not in metin
    assert d.degerlendir({"url": url, "baslik": "İzin duyurusu", "metin": SAYFA_METNI + " İletişim: 0532 123 45 67"})["karar"] == "ayni"
    assert d.degerlendir({"url": url, "baslik": "İzin duyurusu", "metin": SAYFA_METNI + " Güncellendi."})["neden"] == "guncellendi"


def test_mevzuat_sayfasi_kanun_kimligiyle_kaydedilir(d):
    url = "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=8888&MevzuatTur=1&MevzuatTertip=5"
    s = d.degerlendir({"url": url, "baslik": "8888 sayılı Kanun", "metin": ORNEK_KANUN.replace("ÖRNEK", "DENEME")})
    assert s["karar"] == "kabul" and s["kimlik"] == "8888" and s["sinif"] == "mevzuat"
    assert d.k.madde_getir("8888", "2")


def test_ayni_icerik_baska_adreste_tekrar(d):
    d.degerlendir({"url": "https://personel.gop.edu.tr/a", "metin": SAYFA_METNI})
    s = d.degerlendir({"url": "https://personel.gop.edu.tr/a?print=1", "metin": SAYFA_METNI})
    assert s["karar"] == "tekrar"


def test_dosya_baglantilari_kuyruga(d):
    dosyalar = [{"url": f"https://kalite.gop.edu.tr/depo/f{i}.docx", "metin": f"TOGÜ.FRM.{100 + i} Form {i}"} for i in range(6)]
    dosyalar.append({"url": "https://ornek.com/kotu.pdf", "metin": "dış dosya"})
    dosyalar.append({"url": "https://ebys.gop.edu.tr/belge.pdf", "metin": "sistem dosyası"})
    s = d.degerlendir({"url": "https://kalite.gop.edu.tr/formlar", "metin": "Formlar listesi", "dosyalar": dosyalar})
    assert s["karar"] == "liste" and len(s["indirilecek"]) == 6
    assert s["indirilecek"][0]["kod"] == "TOGÜ.FRM.100"


# ------------------------------------------------------------------------- sunucu

def _bos_port() -> int:
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


@pytest.fixture
def sunucu(d):
    s = GozlemSunucusu(d, anahtar="gizli-anahtar", port=_bos_port())
    assert s.baslat()
    yield s
    s.durdur()


def _istek(sunucu, yol, veri=None, anahtar="gizli-anahtar", origin="chrome-extension://abc"):
    basliklar = {"Origin": origin, "Content-Type": "application/json"}
    if anahtar:
        basliklar["X-AkilHocasi-Anahtar"] = anahtar
    govde = json.dumps(veri).encode() if veri is not None else None
    r = urllib.request.Request(f"http://127.0.0.1:{sunucu.port}{yol}", data=govde, headers=basliklar)
    try:
        with urllib.request.urlopen(r, timeout=5) as y:
            return y.status, json.loads(y.read()), dict(y.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), dict(e.headers)


def test_sunucu_durum_ve_kurallar(sunucu):
    kod, veri, basliklar = _istek(sunucu, "/v1/durum")
    assert kod == 200 and veri["ok"] and "gop.edu.tr" in veri["birincil"] and "ebys" in veri["sistem_anahtarlari"]
    assert basliklar["Access-Control-Allow-Origin"] == "chrome-extension://abc"


def test_sunucu_anahtarsiz_ve_yabanci_kaynak_reddedilir(sunucu):
    assert _istek(sunucu, "/v1/durum", anahtar="yanlis")[0] == 401
    assert _istek(sunucu, "/v1/durum", anahtar="")[0] == 401
    assert _istek(sunucu, "/v1/durum", origin="https://kotu-site.com")[0] == 403


def test_sunucu_gozlem_alir(sunucu):
    kod, veri, _ = _istek(sunucu, "/v1/gozlem", {"url": "https://personel.gop.edu.tr/d", "metin": SAYFA_METNI, "mod": "pasif"})
    assert kod == 200 and veri["karar"] == "kabul" and veri["kuyruga_alinan"] == 0
    kod, veri, _ = _istek(sunucu, "/v1/gozlem", {"url": "https://www.turkiye.gov.tr/x", "metin": SAYFA_METNI})
    assert kod == 200 and veri["karar"] == "ret"


class SahteMotor:
    def __init__(self):
        self.eklenen, self.durduruldu = [], False

    def tarayici_yolu(self):
        return "/usr/bin/sahte-tarayici"

    def ekle(self, url):
        if "ebys" in url:
            return False, "Yalnız beyaz listedeki herkese açık resmî siteler taranır"
        self.eklenen.append(url)
        return True, "Tarama sıraya alındı."

    def durdur(self):
        self.durduruldu = True

    def durum(self):
        return {"etkin": None, "sirada": list(self.eklenen)}


def test_sunucu_taramayi_motora_devreder(d):
    motor = SahteMotor()
    s = GozlemSunucusu(d, anahtar="gizli-anahtar", port=_bos_port(), motor=motor)
    assert s.baslat()
    try:
        kod, veri, _ = _istek(s, "/v1/tara", {"url": "https://kalite.gop.edu.tr/"})
        assert kod == 200 and veri == {"ok": True, "motor": True, "mesaj": "Tarama sıraya alındı."}
        assert not _istek(s, "/v1/tara", {"url": "https://ebys.gop.edu.tr/"})[1]["ok"]
        kod, veri, _ = _istek(s, "/v1/tara")
        assert veri["sirada"] == ["https://kalite.gop.edu.tr/"]
        assert _istek(s, "/v1/tara", {"komut": "durdur"})[1]["ok"] and motor.durduruldu
        assert _istek(s, "/v1/durum")[1]["motor"] is True
        assert s.son_temas > 0
        assert _istek(s, "/v1/tara", {"url": "https://kalite.gop.edu.tr/"}, anahtar="yanlis")[0] == 401
    finally:
        s.durdur()


def test_sunucu_motorsuz_eklentiye_birakir(sunucu):
    kod, veri, _ = _istek(sunucu, "/v1/tara", {"url": "https://kalite.gop.edu.tr/"})
    assert kod == 200 and veri["ok"] is False and veri["motor"] is False
