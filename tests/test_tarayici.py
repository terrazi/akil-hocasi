import io
import zipfile
from datetime import datetime, timedelta

import docx
import openpyxl

from akil_hocasi.crawler import beyaz_liste
from akil_hocasi.crawler.depo import BelgeDeposu, dosya_turu, makrosuz_kopya, makrolu_mu, metin_cikar
from akil_hocasi.crawler.indirici import Indirici
from akil_hocasi.crawler.kaynaklar import ResmiGazete, kod_bul
from akil_hocasi.crawler.tarayici import Tarayici
from akil_hocasi.crawler.zamanlayici import Zamanlayici
from akil_hocasi.library.db import Kutuphane


def _docx(metin: str) -> bytes:
    b = docx.Document()
    for satir in metin.split("\n"):
        b.add_paragraph(satir)
    t = io.BytesIO()
    b.save(t)
    return t.getvalue()


def _xlsm() -> bytes:
    k = openpyxl.Workbook()
    k.active["A1"] = "Ödeme emri kontrol listesi"
    t = io.BytesIO()
    k.save(t)
    # Makrolu dosyayı taklit et
    giris = zipfile.ZipFile(io.BytesIO(t.getvalue()))
    cikis_t = io.BytesIO()
    with zipfile.ZipFile(cikis_t, "w") as cikis:
        for o in giris.infolist():
            veri = giris.read(o.filename)
            if o.filename == "[Content_Types].xml":
                veri = veri.replace(
                    b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
                    b"application/vnd.ms-excel.sheet.macroEnabled.main+xml")
                veri = veri.replace(b"</Types>", b'<Override PartName="/xl/vbaProject.bin" '
                                    b'ContentType="application/vnd.ms-office.vbaProject"/></Types>')
            if o.filename == "xl/_rels/workbook.xml.rels":
                veri = veri.replace(b"</Relationships>", b'<Relationship Id="rIdVBA" '
                                    b'Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" '
                                    b'Target="vbaProject.bin"/></Relationships>')
            cikis.writestr(o, veri)
        cikis.writestr("xl/vbaProject.bin", b"\x00SAHTE-VBA")
    return cikis_t.getvalue()


# ------------------------------------------------------------------ depo

def test_dosya_turu_ve_makro(tmp_path):
    assert dosya_turu(b"%PDF-1.7 ...") == "pdf"
    d = _docx("Merhaba")
    assert dosya_turu(d) == "docx" and not makrolu_mu(d)
    x = _xlsm()
    assert dosya_turu(x) == "xlsm" and makrolu_mu(x)
    temiz, tur = makrosuz_kopya(x)
    assert tur == "xlsx" and not makrolu_mu(temiz)
    kitap = openpyxl.load_workbook(io.BytesIO(temiz))
    assert kitap.active["A1"].value == "Ödeme emri kontrol listesi"


def test_depo_kayit_surum_ve_kopya(tmp_path):
    depo = BelgeDeposu(tmp_path / "depo")
    url = "https://kalite.gop.edu.tr/depo/menuler/birim_1/formlar_234/form.docx"
    k1 = depo.kaydet(_docx("Sürüm 1"), url, kod="TOGÜ.FRM.396", ad="Aylıksız izin oluru", rv="1")
    assert k1 and k1["tur"] == "docx"
    assert depo.kaydet(_docx("Sürüm 1"), url, kod="TOGÜ.FRM.396")["id"] in (k1["id"], depo.bul("TOGÜ.FRM.396")["id"])
    k2 = depo.kaydet(_docx("Sürüm 2 — değişti"), url, kod="TOGÜ.FRM.396", ad="Aylıksız izin oluru", rv="2")
    surumler = depo.surumler("TOGÜ.FRM.396")
    assert [s["durum"] for s in surumler][:2] == ["guncel", "eski"]
    assert depo.bul("TOGÜ.FRM.396")["rv"] == "2"
    kopya = depo.kopya_ver(k2, tmp_path / "masaustu")
    assert kopya.exists() and "Sürüm 2" in metin_cikar(kopya.read_bytes())
    xk = depo.kaydet(_xlsm(), "https://strateji.gop.edu.tr/depo/x.xlsm", kod="TOGÜ.FRM.670", ad="Kontrol listesi")
    xkopya = depo.kopya_ver(xk, tmp_path / "masaustu")
    assert xkopya.suffix == ".xlsx" and "makrosuz" in xkopya.name
    assert depo.ara("aylıksız")[0]["kod"] == "TOGÜ.FRM.396"


# ------------------------------------------------------------------ zamanlayıcı

def test_zamanlayici():
    z = Zamanlayici({"aralik_dk": 60, "gece_saati": "00:30", "sabah_saati": "08:30"}, "pc-1")
    simdi = datetime(2026, 11, 9, 15, 20)
    ilk = z.bekleyenler(simdi, {})
    assert {"gece", "hafif", "sabah", "derin", "haftalik"} <= set(ilk)
    son = {g: simdi for g in ilk}
    assert z.bekleyenler(simdi + timedelta(minutes=5), son) == []
    sonra = z.bekleyenler(simdi + timedelta(minutes=70), son)
    assert sonra == ["hafif"]
    # Bilgisayar gece kapalıydı: sabah açılınca gece taraması telafi edilir
    ertesi = datetime(2026, 11, 10, 12, 0)            # son derin taramadan 20 saat 40 dk sonra
    telafi = z.bekleyenler(ertesi, son)
    assert "gece" in telafi and "sabah" in telafi and "hafif" in telafi
    assert "derin" not in telafi                      # boşta değil, 48 saat dolmadı
    assert "derin" in z.bekleyenler(ertesi, son, bostayken=True)
    assert z.bekleyenler(ertesi, son, olculu=True) == ["hafif", "sabah"]
    assert z.sonraki(simdi) > simdi
    assert 1 <= z.kaydirma.seconds // 60 <= 9


# ------------------------------------------------------------------ kaynaklar ve tarayıcı

def test_beyaz_liste():
    assert beyaz_liste.izinli_mi("https://kalite.gop.edu.tr/x.pdf")
    assert beyaz_liste.izinli_mi("https://www.resmigazete.gov.tr/eskiler/2026/11/20261109.htm")
    assert not beyaz_liste.izinli_mi("https://gop.edu.tr.kotu-site.com/x")
    assert not beyaz_liste.izinli_mi("ftp://gop.edu.tr/x")
    assert beyaz_liste.ikincil_mi("https://www.memurlar.net/haber/1")


def test_resmi_gazete_adres_ve_kod():
    rg = ResmiGazete()
    from datetime import date
    assert rg.gunluk_url(date(2026, 11, 9)).endswith("/eskiler/2026/11/20261109.htm")
    assert rg.gunluk_url(date(2026, 11, 9), 1).endswith("20261109M1.htm")
    assert rg.ilgili_mi("Devlet Memurlarının Aylıksız İzin Yönetmeliğinde Değişiklik")
    assert kod_bul("TOGÜ.FRM.396 Aylıksız İzin Oluru RV:2") == "TOGÜ.FRM.396"


class _Yanit:
    def __init__(self, durum, icerik=b"", basliklar=None, url=""):
        self.status_code = durum
        self._icerik = icerik
        self.headers = basliklar or {}
        self.text = icerik.decode("utf-8", "ignore")
        self.url = url

    def iter_content(self, n):
        for i in range(0, len(self._icerik), n):
            yield self._icerik[i:i + n]


class SahteOturum:
    def __init__(self, sayfalar):
        self.sayfalar = sayfalar
        self.headers = {}
        self.istekler = []

    def get(self, url, headers=None, timeout=None, stream=False):
        self.istekler.append((url, dict(headers or {})))
        if url.endswith("/robots.txt"):
            return _Yanit(404, url=url)
        if url not in self.sayfalar:
            return _Yanit(404, url=url)
        icerik, etag = self.sayfalar[url]
        if headers and headers.get("If-None-Match") == etag:
            return _Yanit(304, url=url)
        return _Yanit(200, icerik, {"ETag": etag, "Content-Type": "x"}, url=url)


def test_tarayici_derin_ve_kosullu_istek(tmp_path):
    kalite = "https://kalite.gop.edu.tr/DinamikFormlar.aspx?d=tr-TR&mk=43543&m=kalite_belgeleri"
    form_url = "https://kalite.gop.edu.tr/depo/menuler/birim_1/formlar/frm396.docx"
    html = (f'<html><table><tr><td>TOGÜ.FRM.396</td><td><a href="{form_url}">Aylıksız İzin Oluru</a></td>'
            f'<td>RV:2</td></tr></table></html>').encode()
    form = _docx("AYLIKSIZ İZİN OLURU\nMADDE 1 – (1) Personel aylıksız izin talebini bu form ile yapar.")
    oturum = SahteOturum({kalite: (html, '"k1"'), form_url: (form, '"f1"')})
    kut = Kutuphane(tmp_path / "k.db")
    depo = BelgeDeposu(tmp_path / "depo")
    tar = Tarayici(kut, depo, Indirici(istek_arasi_sn=0, oturum=oturum))

    rapor = tar.calistir("hafif")
    assert rapor.yeni == 1, rapor
    assert depo.bul("TOGÜ.FRM.396")["rv"] == "2"
    assert kut.ara("aylıksız izin talebi")[0].belge_kimlik == "TOGÜ.FRM.396"

    # İkinci tur: koşullu istek, değişmeyen belge yeniden indirilmez
    rapor2 = tar.calistir("derin")
    assert rapor2.yeni == 0 and rapor2.degismeyen >= 1
    assert any(h.get("If-None-Match") == '"f1"' for u, h in oturum.istekler if u == form_url)

    # Kaynak değişti: yeni sürüm
    oturum.sayfalar[form_url] = (_docx("AYLIKSIZ İZİN OLURU\nMADDE 1 – (1) Değişen metin, en geç 15 gün."), '"f2"')
    rapor3 = tar.calistir("derin")
    assert rapor3.guncellenen == 1
    assert "15 gün" in kut.ara("aylıksız izin oluru")[0].metin
    assert kut.zamanlayici_son("derin")


def test_indirici_beyaz_liste_disi(tmp_path):
    oturum = SahteOturum({})
    s = Indirici(istek_arasi_sn=0, oturum=oturum).getir("https://ornek-forum.com/x.pdf")
    assert s.durum == 0 and "Beyaz liste" in s.hata and not oturum.istekler
