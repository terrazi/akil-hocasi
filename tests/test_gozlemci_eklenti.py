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
    assert sorted(MANIFEST["permissions"]) == ["alarms", "nativeMessaging", "storage"]
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


def test_eklenti_kimligi_manifest_anahtarindan():
    import base64
    import hashlib

    from akil_hocasi.gozlem.eslestirme import EKLENTI_KIMLIGI
    der = base64.b64decode(MANIFEST["key"])
    kimlik = "".join(chr(ord("a") + int(c, 16)) for c in hashlib.sha256(der).hexdigest()[:32])
    assert kimlik == EKLENTI_KIMLIGI


def test_kopru_iletisi_ve_cevabi(tmp_path, monkeypatch):
    import io

    from akil_hocasi.config import Ayarlar
    from akil_hocasi.gozlem import eslestirme as e
    akis = io.BytesIO()
    e.ileti_yaz(akis, {"tur": "eslestir", "not": "ğüşıöç"})
    akis.seek(0)
    assert e.ileti_oku(akis) == {"tur": "eslestir", "not": "ğüşıöç"}
    assert e.ileti_oku(io.BytesIO(b"")) is None

    a = Ayarlar(tmp_path / "ayarlar.json")
    kaynak = f"chrome-extension://{e.EKLENTI_KIMLIGI}/"
    y = e.yanit_hazirla({"tur": "eslestir"}, kaynak, a)
    assert y["ok"] and len(y["anahtar"]) >= 30 and y["port"] == 47231 and y["uygulama_acik"] is False
    assert e.yanit_hazirla({"tur": "eslestir"}, kaynak, Ayarlar(tmp_path / "ayarlar.json"))["anahtar"] == y["anahtar"]
    assert e.yanit_hazirla({"tur": "eslestir"}, "chrome-extension://baskaeklenti/", a) == {"ok": False, "hata": "tanınmayan eklenti"}
    assert not e.yanit_hazirla({"tur": "sil"}, kaynak, a)["ok"]
    a.ayarla("gozlem.acik", False)
    assert not e.yanit_hazirla({"tur": "eslestir"}, kaynak, a)["ok"]
    b = e.ana_bilgisayar_bildirimi(r"C:\Program\AkilHocasiKopru.exe")
    assert b["name"] == "com.akilhocasi.gozlemci" and b["allowed_origins"] == [kaynak] and b["type"] == "stdio"


def test_kopru_sureci_tarayici_gibi(tmp_path):
    """Köprü, tarayıcının yaptığı gibi ayrı süreç olarak çalıştırılır: stdin'e ileti, stdout'tan cevap."""
    import os
    import struct
    import subprocess
    import sys

    from akil_hocasi.gozlem.eslestirme import EKLENTI_KIMLIGI
    veri = json.dumps({"tur": "eslestir"}).encode()
    ortam = dict(os.environ, AKILHOCASI_VERI=str(tmp_path), PYTHONPATH=str(EKLENTI.parent))
    s = subprocess.run([sys.executable, "-m", "akil_hocasi.gozlem.eslestirme", f"chrome-extension://{EKLENTI_KIMLIGI}/"],
                       input=struct.pack("<I", len(veri)) + veri, capture_output=True, env=ortam, timeout=30)
    assert s.returncode == 0, s.stderr.decode()
    n = struct.unpack("<I", s.stdout[:4])[0]
    cevap = json.loads(s.stdout[4:4 + n])
    assert cevap["ok"] and cevap["anahtar"] and (tmp_path / "ayarlar.json").is_file()
    # köprü ağır modülleri yüklemez (küçük exe)
    s2 = subprocess.run([sys.executable, "-c", "import sys, akil_hocasi.gozlem.eslestirme as e; "
                         "print(any(m in sys.modules for m in ('sqlite3','numpy','PySide6','requests')))"],
                        capture_output=True, env=ortam, timeout=30, text=True)
    assert s2.stdout.strip() == "False"


def test_kurulum_betigi_kopruyu_kaydeder():
    from akil_hocasi.gozlem.eslestirme import ANA_BILGISAYAR_ADI, EKLENTI_KIMLIGI
    iss = (EKLENTI.parent / "paketleme" / "akilhocasi.iss").read_text(encoding="utf-8-sig")
    assert f'#define EklentiKimligi "{EKLENTI_KIMLIGI}"' in iss
    for tarayici in ("Google\\Chrome", "Microsoft\\Edge"):
        assert f"Software\\{tarayici}\\NativeMessagingHosts\\{ANA_BILGISAYAR_ADI}" in iss
    assert "uninsdeletekey" in iss and "KopruBildiriminiYaz" in iss
    spec = (EKLENTI.parent / "paketleme" / "kopru.spec").read_text(encoding="utf-8")
    assert 'name="AkilHocasiKopru"' in spec and "console=True" in spec
