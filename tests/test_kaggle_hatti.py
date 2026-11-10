"""Kaggle eğitim hattı: veri aşamasının bağlantıları (öğretmen sahte sunucuyla) ve rapor."""

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parents[1]


@pytest.fixture
def hat_modulu(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("akilhocasi_kaggle", KOK / "kaggle" / "akilhocasi_kaggle.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "CALISMA", tmp_path / "working")
    monkeypatch.setattr(m, "GECICI", tmp_path / "gecici")
    return m


def test_veri_asamasi_uctan_uca(hat_modulu, kutuphane, tmp_path, monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    sys.path.insert(0, str(Path(__file__).parent))
    import test_damitma
    from test_damitma import IYI

    class Isleyici(BaseHTTPRequestHandler):
        def log_message(self, *a):
            return

        def do_POST(self):
            govde = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            b = json.dumps({"choices": [{"message": {"content": test_damitma._ogretmen_cevabi(govde)}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    sunucu = ThreadingHTTPServer(("127.0.0.1", 0), Isleyici)
    threading.Thread(target=sunucu.serve_forever, daemon=True).start()
    monkeypatch.setattr(hat_modulu, "kutuphane_hazirla",
                        lambda veri, dk: (kutuphane, [{"id": "k1", "soru": IYI, "dayanak": ["9999/2"]}]))
    (tmp_path / "gecici").mkdir()
    arg = Namespace(sure_saat=0.3, soru=10, paralel=2, yuva_baglami=4096, ogretmen="Q4_K_M",
                    ogretmen_adres=f"http://127.0.0.1:{sunucu.server_address[1]}", anlamsiz=True, tarama_dk=0, dusunme=False,
                    yazi_orani=0.2)
    hat_modulu.veri(arg)
    sunucu.shutdown()
    cikti = tmp_path / "working" / "akilhocasi_veri"
    manifest = json.loads((cikti / "manifest.json").read_text("utf-8"))
    assert manifest["ornek_toplam"] > 0 and (cikti / "ornekler.jsonl").is_file()
    assert manifest["bu_oturum"]["soru"] >= 1


def test_egitim_raporu(hat_modulu, tmp_path):
    karne = {"notlar": {"dogruluk": 0.8, "muhakeme": 0.5}, "ornek": {"dogruluk": 10}, "basari": 0.6, "kritik": 1,
             "toplam": 10, "ortalama": 0.65}
    yeni = dict(karne, notlar={"dogruluk": 0.9, "muhakeme": 0.7}, basari=0.7, kritik=0)
    bilgi = {"ad": "Akıl Hocası 4B", "temel": "qwen3.5-4b", "egitim": {
        "ornek": 100, "adim": 20, "kayip": [1.2, 0.6], "kapi": True, "gerekce": "iyileşme", "karne_temel": karne,
        "karne_yeni": yeni}}
    hat_modulu.rapor_yaz(tmp_path / "r.md", bilgi, [{"gorev": "sentez"}, {"gorev": "cozumleme"}])
    metin = (tmp_path / "r.md").read_text("utf-8")
    assert "geçti" in metin and "| Doğruluk | 0.8 | 0.9 |" in metin and "%60 → %70" in metin


def test_egitim_paketi_kisisel_veriyi_disarida_tutar(kutuphane, tmp_path):
    import sqlite3
    import zipfile

    from akil_hocasi.ogrenme.motor import OgrenmeMotoru
    from akil_hocasi.yz.kaggle_paketi import paket_olustur
    OgrenmeMotoru(kutuphane, "test")
    with kutuphane.db:
        kutuphane.db.execute("INSERT INTO ogr_olaylar(zaman, soru, durum) VALUES('2026', "
                             "'TC 12345678901 olan personelin izni ne kadar?', 'Doğrulandı')")
        kutuphane.db.execute("INSERT INTO ogr_altin(soru, beklenen_dayanak) VALUES('Aylıksız izin süresi?', '[\"9999/2\"]')")
    m = paket_olustur(kutuphane, tmp_path / "p.zip")
    with zipfile.ZipFile(tmp_path / "p.zip") as z:
        z.extract("kutuphane.db", tmp_path)
        sorular = [json.loads(x) for x in z.read("sorular.jsonl").decode().splitlines()]
    assert m["soru"] == 1 and sorular[0]["kaynak"] == "altin"
    db = sqlite3.connect(tmp_path / "kutuphane.db")
    assert db.execute("SELECT COUNT(*) FROM ogr_olaylar").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM maddeler").fetchone()[0] > 0
    m2 = paket_olustur(kutuphane, tmp_path / "p2.zip", gercek_sorular=True)
    with zipfile.ZipFile(tmp_path / "p2.zip") as z:
        metin = z.read("sorular.jsonl").decode()
    assert m2["soru"] == 2 and "12345678901" not in metin                 # izinle bile maskelenmiş


def test_ozel_model_ekleme_ve_secim(tmp_path, monkeypatch):
    from akil_hocasi.config import Ayarlar, Yollar
    from akil_hocasi.library.db import Kutuphane
    from akil_hocasi.yz.yonetici import YZYoneticisi
    yollar = Yollar(tmp_path / "veri").olustur()
    yz = YZYoneticisi(yollar, Ayarlar(yollar.ayarlar), Kutuphane(yollar.veritabani))
    monkeypatch.setattr("akil_hocasi.yz.yonetici.bellek_gb", lambda: (8.0, 4.0))
    klasor = yz.model_klasoru()
    (klasor / "qwen3.5-4b.gguf").write_bytes(b"GGUF" + b"0" * 10)
    (klasor / "qwen3.5-4b.json").write_text(json.dumps({"kimlik": "qwen3.5-4b", "tur": "sohbet", "ad": "Qwen3.5 4B"}))
    disari = tmp_path / "indirilen"
    disari.mkdir()
    (disari / "akilhocasi-4b-20261110.gguf").write_bytes(b"GGUF" + b"1" * 10)
    (disari / "akilhocasi-4b-20261110.json").write_text(json.dumps({
        "kimlik": "akilhocasi-4b-20261110", "ad": "Akıl Hocası 4B", "tur": "sohbet", "temel": "qwen3.5-4b",
        "en_az_bellek_gb": 7.5, "oncelik": 80, "egitim": {"kapi": True}}))
    b = yz.ozel_model_ekle(disari / "akilhocasi-4b-20261110.gguf")
    assert b["kimlik"] == "akilhocasi-4b-20261110" and Path(b["yol"]).is_file()
    assert yz.secili("sohbet")["kimlik"] == "akilhocasi-4b-20261110"          # kapıyı geçen eğitilmiş model öncelikli
    yz.ust_bilgi_guncelle(b["kimlik"], yerel_sinav={"sonuc": "reddedildi"})
    assert yz.secili("sohbet")["kimlik"] == "qwen3.5-4b"                       # yerel sınavda kötü çıkarsa temel
    (disari / "kapisiz.gguf").write_bytes(b"GGUF" + b"2" * 10)
    (disari / "kapisiz.json").write_text(json.dumps({"kimlik": "kapisiz", "tur": "sohbet", "egitim": {"kapi": False}}))
    yz.ozel_model_ekle(disari / "kapisiz.gguf")
    assert yz.secili("sohbet")["kimlik"] == "qwen3.5-4b"                       # kapıyı geçmeyen kendiliğinden seçilmez
    assert yz.sil("kapisiz")
    yz.ust_bilgi_guncelle(b["kimlik"], yerel_sinav={})
    for ad, tarih in (("akilhocasi-4b-20261117", "2026-11-17T02:00:00"), ("akilhocasi-4b-20261103", "2026-11-03")):
        (disari / f"{ad}.gguf").write_bytes(b"GGUF" + b"3" * 10)
        (disari / f"{ad}.json").write_text(json.dumps({"kimlik": ad, "tur": "sohbet", "oncelik": 80,
                                                       "egitim": {"kapi": True, "tarih": tarih}}))
        yz.ozel_model_ekle(disari / f"{ad}.gguf")
    assert yz.secili("sohbet")["kimlik"] == "akilhocasi-4b-20261117"           # eşit öncelikte en yeni eğitim
    sahte = disari / "sahte.gguf"
    sahte.write_bytes(b"XXXX")
    with pytest.raises(Exception, match="GGUF"):
        yz.ozel_model_ekle(sahte)


def test_defterler_gecerli_ve_betigi_cagirir():
    for ad, komut in (("1_veri_uretimi.ipynb", "akilhocasi_kaggle.py veri"),
                      ("2_egitim_ve_sinama.ipynb", "akilhocasi_kaggle.py egit")):
        d = json.loads((KOK / "kaggle" / ad).read_text("utf-8"))
        kod = "".join("".join(h["source"]) for h in d["cells"] if h["cell_type"] == "code")
        assert komut in kod and "git clone --depth 1 https://github.com/terrazi/akil-hocasi" in kod
        assert d["metadata"]["kaggle"]["isInternetEnabled"] is True
    assert "Eğitilmiş modeli ekle" in (KOK / "kaggle" / "BENIOKU.md").read_text("utf-8")


def test_veri_turlari_birlestirilir(hat_modulu, tmp_path):
    t1, t2, hedef = tmp_path / "t1", tmp_path / "t2", tmp_path / "h"
    for d, satir in ((t1, ["a", "b"]), (t2, ["b", "c"])):
        d.mkdir()
        (d / "ornekler.jsonl").write_text("\n".join(satir) + "\n", "utf-8")
        (d / "kutuphane.db").write_text(d.name, "utf-8")
    hat_modulu.birlestir([t1, t2], hedef)
    assert (hedef / "ornekler.jsonl").read_text("utf-8").split() == ["a", "b", "c"]
    assert (hedef / "kutuphane.db").read_text("utf-8") == "t2"                 # en yeni turun kütüphanesi


def test_kaggle_api_defter_ayarlarini_yazar():
    spec = importlib.util.spec_from_file_location("kaggle_api", KOK / "kaggle" / "kaggle_api.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    d = m.defter_hazirla("egit", {"OGRENCI": "2B", "SURE_SAAT": 9.5, "EPOCH": 1})
    kod = "".join("".join(h["source"]) for h in d["cells"] if h["cell_type"] == "code")
    assert "OGRENCI = '2B'" in kod and "SURE_SAAT = 9.5" in kod and "EPOCH = 1" in kod
    assert "# 8 GB bilgisayarlar" in kod                                      # açıklamalar korunur
