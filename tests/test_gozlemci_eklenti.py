"""Eklenti ile uygulama aynı kuralları kullanmalı: listeler ve manifest izinleri eşit, izinler en az düzeyde."""

import json
import re
from pathlib import Path

from akil_hocasi.crawler import beyaz_liste
from akil_hocasi.gozlem import degerlendirici as d

EKLENTI = Path(__file__).resolve().parents[1] / "gozlemci_eklenti"
KURALLAR = (EKLENTI / "kurallar.js").read_text(encoding="utf-8")
MANIFEST = json.loads((EKLENTI / "manifest.json").read_text(encoding="utf-8"))


def _js_liste(ad: str) -> list[str]:
    m = re.search(rf"const {ad} = (\[[^\]]*\]);", KURALLAR)
    assert m, ad
    return json.loads(m.group(1))


def test_listeler_uygulamayla_ayni():
    assert _js_liste("SISTEM_ALANLARI") == d.SISTEM_ALANLARI
    assert _js_liste("SISTEM_ANAHTARLARI") == d.SISTEM_ANAHTARLARI
    assert _js_liste("ISTISNALAR") == d.ISTISNALAR
    assert _js_liste("IKINCIL") == beyaz_liste.IKINCIL
    # kbs.gov.tr takvimli tarayıcıda birincil, gözlemde tamamen kapalı
    assert _js_liste("BIRINCIL") == [a for a in beyaz_liste.BIRINCIL if a != "kbs.gov.tr"]


def test_manifest_izinleri_en_az_duzeyde():
    assert MANIFEST["manifest_version"] == 3
    assert sorted(MANIFEST["permissions"]) == ["alarms", "storage"]
    izinler = MANIFEST["host_permissions"]
    assert "<all_urls>" not in izinler and not any("*://*/*" in i for i in izinler)
    for yasak in ("debugger", "downloads", "cookies", "webRequest", "tabs", "history", "scripting"):
        assert yasak not in MANIFEST["permissions"]
    alanlar = {re.sub(r"^https?://(\*\.)?", "", i).split("/")[0] for i in izinler}
    beklenen = set(_js_liste("BIRINCIL")) | set(_js_liste("IKINCIL")) | {"127.0.0.1"}
    assert alanlar == beklenen
    icerik = MANIFEST["content_scripts"][0]
    assert {re.sub(r"^https?://(\*\.)?", "", i).split("/")[0] for i in icerik["matches"]} == beklenen - {"127.0.0.1"}
    assert icerik["js"] == ["kurallar.js", "icerik.js"] and icerik["all_frames"] is False


def test_eklenti_dosyalari_tam():
    for ad in ("manifest.json", "kurallar.js", "icerik.js", "arka_plan.js", "acilir.html", "acilir.js",
               "ayarlar.html", "ayarlar.js", "stil.css", "simgeler/simge16.png", "simgeler/simge128.png"):
        assert (EKLENTI / ad).is_file(), ad
    # içerik betiği hiçbir öğeye tıklamaz, form göndermez
    icerik = (EKLENTI / "icerik.js").read_text(encoding="utf-8")
    for yasak in (".click(", ".submit(", "dispatchEvent", ".value =", "innerHTML ="):
        assert yasak not in icerik, yasak


def test_eklenti_kurulumu_ve_anahtar(tmp_path):
    from akil_hocasi.config import Ayarlar
    from akil_hocasi.gozlem.kurulum import anahtari_hazirla, eklentiyi_hazirla
    hedef = eklentiyi_hazirla(tmp_path)
    assert (hedef / "manifest.json").is_file() and (hedef / "simgeler" / "simge48.png").is_file()
    (hedef / "icerik.js").write_text("bozuk", encoding="utf-8")           # değişen/bozulan dosya yenilenir
    eklentiyi_hazirla(tmp_path)
    assert (hedef / "icerik.js").read_bytes() == (EKLENTI / "icerik.js").read_bytes()
    a = Ayarlar(tmp_path / "ayarlar.json")
    anahtar = anahtari_hazirla(a)
    assert len(anahtar) >= 30 and anahtari_hazirla(Ayarlar(tmp_path / "ayarlar.json")) == anahtar
