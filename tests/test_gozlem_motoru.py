"""Gömülü tarama motoru: kurallar ve gerçek Chrome/Edge ile uçtan uca site taraması.

Uçtan uca test, bilgisayarda Chrome/Edge yoksa atlanır. Sahte TOGÜ sitesi yerel bir HTTP sunucusundan sunulur;
tarayıcıya *.gop.edu.tr adlarını bu sunucuya yönlendirmesi söylenir (internet gerekmez).
"""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from akil_hocasi.gozlem import motor as motor_modulu
from akil_hocasi.gozlem.cdp import BasliksizTarayici, WebSoket, tarayici_bul
from akil_hocasi.gozlem.degerlendirici import GozlemDegerlendirici
from akil_hocasi.gozlem.kurallar import (benzerlik, genisletilsin_mi, robots_ayristir, robots_izinli,
                                         yol_kalibi)
from akil_hocasi.gozlem.motor import GozlemMotoru, kok_adres


# ------------------------------------------------------------------ kurallar (JS ile aynı örnekler)
def test_robots_ve_kaliplar_js_ile_ayni():
    r = robots_ayristir("User-agent: Googlebot\nDisallow: /\n\nUser-agent: *\nDisallow: /gizli/\nAllow: /gizli/acik\nDisallow: /*.php$\n")
    assert robots_izinli(r, "/duyurular") and not robots_izinli(r, "/gizli/x") and robots_izinli(r, "/gizli/acik/1")
    assert not robots_izinli(r, "/ara.php") and robots_izinli(r, "/ara.php?x=1")
    assert robots_izinli(robots_ayristir("User-agent: *\nDisallow:\n"), "/her/sey")
    assert not robots_izinli(robots_ayristir("User-agent: akilhocasi\nDisallow: /\nUser-agent: *\nAllow: /\n"), "/a")
    assert yol_kalibi("https://x.gop.edu.tr/duyuru/123?sayfa=2") == "x.gop.edu.tr/duyuru/:n?sayfa=*"
    assert yol_kalibi("https://x.gop.edu.tr/haber-2024-001") == "x.gop.edu.tr/:id"
    imza = ["0:body", "1:div.icerik"]
    assert benzerlik(imza, imza) == 1 and benzerlik(["a"], ["b"]) == 0
    assert genisletilsin_mi(imza, "k", [{"kalip": "k", "imza": imza}] * 4)
    assert not genisletilsin_mi(imza, "k", [{"kalip": "k", "imza": imza}] * 5)


def test_kok_adres_ve_kuyruk_kurallari(kutuphane):
    assert kok_adres("https://Kalite.gop.edu.tr") == "https://kalite.gop.edu.tr/"
    assert kok_adres("ftp://x") is None
    m = GozlemMotoru(GozlemDegerlendirici(kutuphane), tarayici_fabrikasi=lambda: None)
    try:
        assert not m.ekle("https://ebys.gop.edu.tr/")[0]
        assert not m.ekle("https://www.memurlar.net/")[0]
        assert not m.ekle("https://ornek.com/")[0]
    finally:
        m.kapat()


def test_websocket_buyuk_cerceve_maskeleme():
    from akil_hocasi.gozlem.cdp import _maskele_hizli
    veri = bytes(range(256)) * 300
    maske = b"\x01\x02\x03\x04"
    assert _maskele_hizli(_maskele_hizli(veri, maske), maske) == veri
    assert _maskele_hizli(b"", maske) == b""


# ------------------------------------------------------------------ sahte TOGÜ sitesi
SAYFA = """<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8"><title>{baslik}</title></head>
<body><nav>Ana Sayfa | Menü | Duyurular</nav><div class="sablon"><main><h1>{baslik}</h1>{govde}</main></div>
<footer>© TOGÜ</footer></body></html>"""
UZUN = ("Bu metin Personel Daire Başkanlığının herkese açık bilgilendirme sayfasıdır. Başvurular birim amirine "
        "dilekçe ile yapılır, süreler ilgili mevzuata göre hesaplanır ve sonuç ilgiliye yazılı olarak bildirilir. ")


def _site(port: int):
    def baglanti(yol, metin):
        return f'<a href="{yol}">{metin}</a>'

    sayfalar = {
        "/": ("Kalite Koordinatörlüğü", "".join([
            f"<p>{UZUN}</p>", baglanti("/formlar", "Formlar"), baglanti("/mevzuat", "Usul ve esaslar"),
            baglanti("/spa", "Duyuru uygulaması"), baglanti("/kayit/sil?id=3", "Kaydı sil"), baglanti("/yazdir", "Yazdır"), baglanti("/gizli/rapor", "İç rapor"),
            baglanti("/giris", "Personel girişi"), baglanti("/oturum", "Profil"), baglanti("/yonlendir", "EBYS"),
            baglanti("/yok", "Kırık bağlantı"), baglanti(f"http://ebys.gop.edu.tr:{port}/", "EBYS"),
            baglanti("/depo/rapor.pdf", "Faaliyet raporu"),
            *[baglanti(f"/duyuru/{i}", f"Duyuru {i}") for i in range(1, 9)]])),
        "/formlar": ("Formlar", "<ul>" + "".join(
            f'<li><a href="/depo/frm{i}.docx">TOGÜ.FRM.{100 + i} Form {i}</a></li>' for i in range(6)) + "</ul>"),
        "/mevzuat": ("TOGÜ Örnek Usul ve Esaslar", "<p>Amaç</p><p>MADDE 1 – (1) Bu Usul ve Esasların amacı örnek "
                     "düzenlemeleri belirlemektir.</p><p>Kapsam</p><p>MADDE 2 – (1) Bu Usul ve Esaslar tüm idari "
                     "birimleri kapsar ve 2547 sayılı Kanuna dayanılarak hazırlanmıştır.</p>"),
        "/oturum": ("Profil", f'<p>{UZUN}</p><form><input type="password" name="p"></form>'),
    }
    for i in range(1, 9):
        sayfalar[f"/duyuru/{i}"] = (f"Duyuru {i}", f"<p>Duyuru {i}: {UZUN}</p>" + baglanti(f"/duyuru/{i + 100}", "İlgili"))

    class Isleyici(BaseHTTPRequestHandler):
        istekler: list[str] = []

        def log_message(self, *a):
            return

        def _yaz(self, kod, govde, tur="text/html; charset=utf-8", ek=None):
            veri = govde.encode("utf-8")
            self.send_response(kod)
            self.send_header("Content-Type", tur)
            self.send_header("Content-Length", str(len(veri)))
            for k, v in (ek or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(veri)

        def do_GET(self):
            host = self.headers.get("Host", "").split(":")[0]
            Isleyici.istekler.append(f"{host}{self.path}")
            if host.startswith("ebys."):
                return self._yaz(200, SAYFA.format(baslik="EBYS", govde='<input type="password">'))
            yol = self.path.split("?")[0]
            if yol == "/robots.txt":
                return self._yaz(200, "User-agent: *\nDisallow: /gizli/\n", "text/plain")
            if yol == "/yonlendir":
                return self._yaz(302, "", ek={"Location": f"http://ebys.gop.edu.tr:{port}/"})
            if yol == "/spa":
                betik = ("<script>setTimeout(function(){document.querySelector('main').innerHTML="
                         "'<h1>Akademik takvim duyurusu</h1><p>Bu içerik sayfa betiğiyle sonradan yüklendi. "
                         + UZUN.replace("'", "") + "</p>';}, 150);</script>")
                return self._yaz(200, SAYFA.format(baslik="Yükleniyor", govde="<p>Yükleniyor…</p>") + betik)
            if yol in sayfalar:
                b, g = sayfalar[yol]
                return self._yaz(200, SAYFA.format(baslik=b, govde=g))
            return self._yaz(404, SAYFA.format(baslik="Sayfa bulunamadı", govde=f"<p>Bulunamadı. {UZUN}</p>"))

    return Isleyici


@pytest.fixture
def sahte_site():
    sunucu = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = sunucu.server_address[1]
    sunucu.RequestHandlerClass = _site(port)
    threading.Thread(target=sunucu.serve_forever, daemon=True).start()
    yield port, sunucu.RequestHandlerClass
    sunucu.shutdown()
    sunucu.server_close()


TARAYICI = tarayici_bul()
gercek_tarayici = pytest.mark.skipif(not TARAYICI, reason="Chrome/Edge yok")


def _fabrika():
    ek = ["--host-resolver-rules=MAP *.gop.edu.tr 127.0.0.1", "--no-proxy-server"]
    if sys.platform.startswith("linux"):
        ek.append("--no-sandbox")
    return lambda: BasliksizTarayici(ek_argumanlar=ek, durulma=0.5)


class SahteDosyaKuyrugu:
    def __init__(self):
        self.gelen = []

    def ekle(self, ogeler):
        self.gelen += ogeler
        return len(ogeler)

    def bekleyen(self):
        return 0


@gercek_tarayici
def test_basliksiz_tarayici_sayfa_okur_ve_profil_silinir(sahte_site):
    port, _ = sahte_site
    with _fabrika()() as t:
        profil = t.profil
        assert t.surum
        s = t.sayfa_oku(f"http://kalite.gop.edu.tr:{port}/spa")
        assert s["tur"] == "sayfa" and "sonradan yüklendi" in s["kayit"]["metin"]   # betikle gelen içerik okunur
        assert "Menü" not in s["kayit"]["metin"] and "©" not in s["kayit"]["metin"]
        assert t.sayfa_oku(f"http://kalite.gop.edu.tr:{port}/oturum")["tur"] == "engel"
        assert t.sayfa_oku(f"http://kalite.gop.edu.tr:{port}/yok")["neden"] == "HTTP 404"
        assert t.robots_getir(f"http://kalite.gop.edu.tr:{port}").startswith("User-agent")
    from pathlib import Path
    assert not Path(profil).exists()


@gercek_tarayici
def test_motor_siteyi_guvenli_tarar(kutuphane, sahte_site, monkeypatch):
    port, isleyici = sahte_site
    monkeypatch.setattr(motor_modulu, "bekleme", lambda hiz: 0.05)
    dosyalar = SahteDosyaKuyrugu()
    olaylar = []
    m = GozlemMotoru(GozlemDegerlendirici(kutuphane), dosyalar=dosyalar,
                     ayar=lambda: {"en_cok_sayfa": 60, "derinlik": 3}, bildir=olaylar.append,
                     tarayici_fabrikasi=_fabrika())
    try:
        assert m.ekle(f"http://kalite.gop.edu.tr:{port}/")[0]
        bitis = time.monotonic() + 120
        while time.monotonic() < bitis and not (m.etkin and m.etkin.durum == "bitti"):
            time.sleep(0.3)
        t = m.etkin
        assert t and t.durum == "bitti", (t.ozet() if t else m.son_hata)
    finally:
        m.kapat()

    istenen = isleyici.istekler
    for yasak in ("/sil", "/yazdir", "/gizli/", "/giris", ".docx", ".pdf"):
        assert not any(yasak in i for i in istenen), yasak
    # EBYS'ye doğrudan bağlantı izlenmez; yalnız /yonlendir'in yönlendirmesiyle bir kez ulaşılır ve okunmaz
    assert sum(1 for i in istenen if i.startswith("ebys.")) <= 1
    # yönlendirme ile EBYS'ye düşen sayfa okunmaz; oturum sayfası engellenir; 404 kaydedilmez
    assert t.sayac.get("yonlendirme", 0) + t.sayac.get("engel", 0) >= 2
    kimlikler = {r[0] for r in kutuphane.db.execute("SELECT kimlik FROM belgeler")}
    assert any(k.endswith("/spa") for k in kimlikler)                       # betikle yüklenen sayfa kütüphanede
    assert any("/mevzuat" in k for k in kimlikler)
    assert not any("/yok" in k or "/oturum" in k for k in kimlikler)
    assert kutuphane.madde_getir(next(k for k in kimlikler if "/mevzuat" in k), "2")   # madde yapısı korunur
    # dosya bağlantıları indirilmek üzere kuyruğa (6 form + rapor)
    assert {o["kod"] for o in dosyalar.gelen if o.get("kod")} >= {f"TOGÜ.FRM.{100 + i}" for i in range(6)}
    # benzer şablon süzgeci: 8 duyurunun hepsinin "ilgili" bağlantısı açılmaz
    ilgili = [i for i in istenen if "/duyuru/1" in i and len(i.rsplit("/", 1)[-1]) == 3]
    assert len(ilgili) <= 5 and t.sayac.get("benzer", 0) >= 1
    assert olaylar and olaylar[-1]["etkin"]["durum"] == "bitti"
    gecmis = m.gecmis()
    assert gecmis[0]["kok"] == f"http://kalite.gop.edu.tr:{port}/" and json.dumps(gecmis)


@gercek_tarayici
def test_motor_durdurulunca_kaldigi_yerden_surer(kutuphane, sahte_site, monkeypatch):
    port, _ = sahte_site
    monkeypatch.setattr(motor_modulu, "bekleme", lambda hiz: 0.3)
    d = GozlemDegerlendirici(kutuphane)
    m = GozlemMotoru(d, ayar=lambda: {"en_cok_sayfa": 40, "derinlik": 2}, tarayici_fabrikasi=_fabrika())
    kok = f"http://kalite.gop.edu.tr:{port}/"
    try:
        m.ekle(kok)
        bitis = time.monotonic() + 60
        while time.monotonic() < bitis and not (m.etkin and m.etkin.sayfa >= 3):
            time.sleep(0.1)
        m.durdur()
        bitis = time.monotonic() + 30
        while time.monotonic() < bitis and m.etkin.durum == "calisiyor":
            time.sleep(0.1)
        assert m.etkin.durum == "duraklatildi"
        okunan = m.etkin.sayfa
        assert m.ekle(kok)[0]
        bitis = time.monotonic() + 120
        while time.monotonic() < bitis and m.etkin.durum != "bitti":
            time.sleep(0.3)
        assert m.etkin.durum == "bitti" and m.etkin.sayfa > okunan
    finally:
        m.kapat()


def test_websocket_reddi_anlasilir_hata():
    import socket as _s
    so = _s.socket()
    so.bind(("127.0.0.1", 0))
    so.listen(1)
    port = so.getsockname()[1]

    def yanitla():
        c, _ = so.accept()
        c.recv(4096)
        c.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        c.close()

    threading.Thread(target=yanitla, daemon=True).start()
    with pytest.raises(Exception, match="reddedildi"):
        WebSoket(f"ws://127.0.0.1:{port}/devtools/browser/x")
    so.close()
