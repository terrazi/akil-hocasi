"""Kaggle'da eğitilen modelin GitHub sürümü olarak yayımlanması (parçalama) ve programdan indirilmesi."""

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from akil_hocasi.yz import surum_modeli
from akil_hocasi.yz.indirici import IndirmeHatasi

KOK = Path(__file__).resolve().parents[1]


def _yayinla_modulu():
    spec = importlib.util.spec_from_file_location("surum_yayinla", KOK / "kaggle" / "surum_yayinla.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def yayin(tmp_path, monkeypatch):
    """Sahte Kaggle çıktısını parçalara böler ve sahte GitHub API'siyle sunar."""
    y = _yayinla_modulu()
    monkeypatch.setattr(y, "PARCA", 1000)
    cikti = tmp_path / "kaggle_cikti" / "akilhocasi_model"
    cikti.mkdir(parents=True)
    veri = b"GGUF" + bytes(range(256)) * 10                    # 2564 bayt → 3 parça
    (cikti / "akilhocasi-4b-20261111.gguf").write_bytes(veri)
    (cikti / "akilhocasi-4b-20261111.json").write_text(json.dumps(
        {"kimlik": "akilhocasi-4b-20261111", "ad": "Akıl Hocası 4B", "egitim": {"kapi": True}}), "utf-8")
    bildirim, dosyalar, _ = y.hazirla(tmp_path / "kaggle_cikti", tmp_path / "surum")
    assert len(bildirim["parcalar"]) == 3 and bildirim["boyut"] == len(veri)
    sunulan = {d.name: d.read_bytes() for d in dosyalar}

    class Isleyici(BaseHTTPRequestHandler):
        bozuk = False

        def log_message(self, *a):
            return

        def do_GET(self):
            adres = f"http://127.0.0.1:{self.server.server_address[1]}"
            if self.path.startswith("/repos/"):
                govde = json.dumps([
                    {"tag_name": "v0.3.0", "assets": []},
                    {"tag_name": "model-akilhocasi-4b-20261111", "published_at": "2026-11-11T00:00:00Z",
                     "assets": [{"name": a, "browser_download_url": f"{adres}/d/{a}"} for a in sunulan]}]).encode()
            elif self.path.startswith("/d/"):
                govde = sunulan[self.path[3:]]
                if Isleyici.bozuk and self.path.endswith(".002"):
                    govde = govde[:-1] + b"X"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(govde)))
            self.end_headers()
            self.wfile.write(govde)

    s = ThreadingHTTPServer(("127.0.0.1", 0), Isleyici)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}", veri, Isleyici
    s.shutdown()


def test_surumden_bul_indir_birlestir_dogrula(yayin, tmp_path):
    api, veri, _ = yayin
    b = surum_modeli.son_egitilmis(api=api)
    assert b and b["etiket"] == "model-akilhocasi-4b-20261111" and b["bilgi"]["kimlik"] == "akilhocasi-4b-20261111"
    ilerleme = []
    gguf = surum_modeli.indir(b, tmp_path / "modeller", lambda a, t, m: ilerleme.append((a, t, m)))
    assert gguf.read_bytes() == veri and ilerleme
    assert json.loads(gguf.with_suffix(".json").read_text("utf-8"))["egitim"]["kapi"] is True
    assert not list((tmp_path / "modeller").glob("*.00*"))                          # parçalar silindi


def test_bozuk_parca_reddedilir(yayin, tmp_path):
    api, _, isleyici = yayin
    isleyici.bozuk = True
    b = surum_modeli.son_egitilmis(api=api)
    with pytest.raises(IndirmeHatasi):
        surum_modeli.indir(b, tmp_path / "modeller")
    assert not list((tmp_path / "modeller").glob("*.gguf"))


def test_surum_yoksa_none():
    assert surum_modeli.son_egitilmis(api="http://127.0.0.1:9") is None


def test_on_surum_onerilmez(yayin, monkeypatch):
    """Kaggle kapısını geçemeyen model ön sürüm olarak yayımlanır; program onu önermez."""
    import json as _json
    api, _, _ = yayin
    asil = surum_modeli._istek

    def sahte(url, *a, **k):
        y = asil(url, *a, **k)
        if "/releases" not in url:
            return y
        veri = _json.loads(y.read().decode())
        for s in veri:
            s["prerelease"] = True

        class Y:
            def __enter__(self):
                return self

            def __exit__(self, *e):
                return False

            def read(self):
                return _json.dumps(veri).encode()
        return Y()
    monkeypatch.setattr(surum_modeli, "_istek", sahte)
    assert surum_modeli.son_egitilmis(api=api) is None
