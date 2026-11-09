"""Çekirdek bilgi paketi: bütünlük denetimi, kütüphaneye işleme, tekrar çalıştırmada atlama."""

import hashlib
import json

from akil_hocasi.crawler.depo import BelgeDeposu
from akil_hocasi.crawler.tarayici import Tarayici
from akil_hocasi.library.bilgi_paketi import paketi_yukle

YONETMELIK = ("<html><body><h1>RESMÎ YAZIŞMALARDA UYGULANACAK USUL VE ESASLAR HAKKINDA YÖNETMELİK</h1>"
              "<p>Metin</p><p>MADDE 16 – (1) Metin, belgenin konusunu oluşturan bölümdür. "
              "Paragraf başlarına 1,25 cm içeriden başlanır.</p>"
              "<p>MADDE 17 – (1) İmza bölümü metnin bitiminden itibaren 2-4 satır boşluk bırakılarak yazılır.</p>"
              "</body></html>").encode("utf-8")


def _paket(klasor, icerik, sha=None):
    klasor.mkdir(parents=True, exist_ok=True)
    (klasor / "MEV_21.5.2646.html").write_bytes(icerik)
    (klasor / "manifest.json").write_text(json.dumps({"belgeler": [{
        "kimlik": "MEV:21.5.2646", "baslik": "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik",
        "tur": "yonetmelik", "url": "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=2646&MevzuatTur=21&MevzuatTertip=5",
        "dosya": "MEV_21.5.2646.html", "sha256": sha or hashlib.sha256(icerik).hexdigest()}]}), "utf-8")
    return klasor


def test_paket_islenir_ve_tekrarda_atlanir(kutuphane, tmp_path):
    t = Tarayici(kutuphane, BelgeDeposu(tmp_path / "depo"))
    klasor = _paket(tmp_path / "paket", YONETMELIK)
    s = paketi_yukle(t, klasor)
    assert s == {"yeni": 1, "atlanan": 0, "hata": []}
    m = kutuphane.madde_getir("MEV:21.5.2646", "16")
    assert m is not None and "1,25 cm" in m.metin
    assert paketi_yukle(t, klasor)["atlanan"] == 1


def test_bozuk_paket_reddedilir(kutuphane, tmp_path):
    t = Tarayici(kutuphane, BelgeDeposu(tmp_path / "depo"))
    s = paketi_yukle(t, _paket(tmp_path / "paket", YONETMELIK, sha="0" * 64))
    assert s["yeni"] == 0 and "bütünlük" in s["hata"][0]
    assert kutuphane.belge_bilgisi("MEV:21.5.2646") is None
