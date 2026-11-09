"""YZ çekirdeği: katalog, model indirici (sahte Hugging Face), llama-server yönetimi (sahte sunucu), anlam dizini,
YZ yöneticisi ve cevap hattıyla bütünleşme. Gerçek model, derleme sunucusunda gerçek llama-server ile sınanır."""

import hashlib
import json
import os
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

from akil_hocasi.yz.anlam import AnlamDizini
from akil_hocasi.yz.indirici import IndirmeHatasi, ModelIndirici, kurulu_modeller
from akil_hocasi.yz.katalog import Katalog, ModelTanimi
from akil_hocasi.yz.sunucu import LlamaSunucusu, ModelHatasi, SunucuModeli

SAHTE = Path(__file__).with_name("sahte_llama_server.py")


@pytest.fixture(scope="module")
def sahte_exe(tmp_path_factory):
    """Sahte llama-server'ı çalıştırılabilir bir betik olarak hazırlar."""
    if sys.platform == "win32":
        pytest.skip("sahte sunucu betiği Windows'ta exe olarak çalıştırılamaz (gerçek sunucu öz testte sınanır)")
    d = tmp_path_factory.mktemp("llama")
    exe = d / "llama-server"
    exe.write_text(f"#!/bin/sh\nexec {sys.executable} {SAHTE} \"$@\"\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(exe)


def _model_dosyasi(klasor: Path, kimlik: str, tur: str) -> Path:
    gguf = klasor / f"{kimlik}.gguf"
    gguf.write_bytes(b"GGUF sahte")
    gguf.with_suffix(".json").write_text(json.dumps({"kimlik": kimlik, "ad": kimlik, "tur": tur, "baglam": 4096}))
    return gguf


# ------------------------------------------------------------------ katalog
def test_katalog_donanima_gore_oneri_ve_uzak_guncelleme():
    k = Katalog()
    assert k.onerilen("sohbet", 32).kimlik == "qwen3.5-9b"
    assert k.onerilen("sohbet", 16).kimlik == "qwen3.5-9b"
    assert k.onerilen("sohbet", 8).kimlik == "qwen3.5-4b"
    assert k.onerilen("sohbet", 6).kimlik == "qwen3.5-2b"
    assert k.onerilen("sohbet", 2).kimlik == "qwen3.5-0.8b"           # hiçbiri sığmazsa en küçüğü
    assert k.onerilen("anlam", 8).kimlik == "qwen3-embedding-0.6b"
    assert all(not m.aday for m in [k.onerilen("sohbet", g) for g in (4, 8, 12, 16)])
    assert [m.kimlik for m in k.yarisma_adaylari("sohbet", 12, "qwen3.5-4b")] == ["gemma-4-e4b", "qwen3.5-4b"][:1]
    n = k.birlestir(json.dumps({"modeller": [{"kimlik": "yeni-model", "ad": "Yeni", "tur": "sohbet", "depo": "kurum/yeni",
                                              "desen": r"Q4_K_M\.gguf$", "yaklasik_gb": 3, "en_az_bellek_gb": 8,
                                              "oncelik": 95}, {"kimlik": "bozuk", "tur": "uydurma"}]}))
    assert n == 1 and k.onerilen("sohbet", 8).kimlik == "yeni-model"
    m = k.getir("qwen3.5-4b")
    assert m.dosya_eslesir("Qwen3.5-4B-Q4_K_M.gguf") and not m.dosya_eslesir("mmproj-Q4_K_M.gguf")


# ------------------------------------------------------------------ indirici (sahte Hugging Face)
@pytest.fixture
def sahte_hf(tmp_path):
    icerik = os.urandom(300_000)
    sha = hashlib.sha256(icerik).hexdigest()
    durum = {"kes": True, "range": []}

    class Isleyici(BaseHTTPRequestHandler):
        def log_message(self, *a):
            return

        def do_GET(self):
            if self.path.startswith("/api/models/kurum/model-GGUF/tree/main"):
                veri = json.dumps([{"type": "file", "path": "README.md", "size": 10},
                                   {"type": "file", "path": "mmproj-Q4_K_M.gguf", "size": 5},
                                   {"type": "file", "path": "Model-Q4_K_M.gguf", "size": len(icerik),
                                    "lfs": {"oid": sha, "size": len(icerik)}},
                                   {"type": "file", "path": "Model-Q8_0.gguf", "size": 99}]).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(veri)))
                self.end_headers()
                return self.wfile.write(veri)
            if self.path == "/kurum/model-GGUF/resolve/main/Model-Q4_K_M.gguf":
                bas = 0
                if self.headers.get("Range"):
                    bas = int(self.headers["Range"].split("=")[1].split("-")[0])
                    durum["range"].append(bas)
                parca = icerik[bas:]
                self.send_response(206 if bas else 200)
                self.send_header("Content-Length", str(len(parca)))
                self.end_headers()
                if durum["kes"]:                             # ilk denemede bağlantı yarıda kopar
                    durum["kes"] = False
                    self.wfile.write(parca[:100_000])
                    self.wfile.flush()
                    self.connection.close()
                    return
                return self.wfile.write(parca)
            self.send_response(404)
            self.end_headers()

    s = ThreadingHTTPServer(("127.0.0.1", 0), Isleyici)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}", icerik, durum
    s.shutdown()


def test_indirici_cozumler_kaldigi_yerden_surer_ve_dogrular(tmp_path, sahte_hf, monkeypatch):
    import akil_hocasi.yz.indirici as ind
    monkeypatch.setattr(ind.time, "sleep", lambda s: None)
    taban, icerik, durum = sahte_hf
    m = ModelTanimi("deneme", "Deneme", "sohbet", "kurum/model-GGUF", r"Q4_K_M\.gguf$", 0.1, 1)
    indirici = ModelIndirici(tmp_path / "modeller", ayna=taban)
    bilgi = indirici.cozumle(m)
    assert bilgi["dosya"] == "Model-Q4_K_M.gguf" and bilgi["boyut"] == len(icerik)
    olaylar = []
    yol = indirici.indir(m, lambda a, b, c: olaylar.append(c))
    assert yol.read_bytes() == icerik and durum["range"]                   # kopan indirme Range ile sürdü
    assert "Doğrulanıyor" in olaylar and not yol.with_suffix(yol.suffix + ".part").exists()
    k = kurulu_modeller(tmp_path / "modeller")
    assert k[0]["kimlik"] == "deneme" and k[0]["sha256"] == hashlib.sha256(icerik).hexdigest()
    assert indirici.indir(m) == yol                                          # zaten var: yeniden indirilmez


def test_indirici_bozuk_dosyayi_reddeder_ve_ortak_klasor(tmp_path, sahte_hf):
    taban, icerik, _ = sahte_hf
    m = ModelTanimi("deneme", "Deneme", "sohbet", "kurum/model-GGUF", r"Q4_K_M\.gguf$", 0.1, 1)
    ortak = tmp_path / "ortak"
    ortak.mkdir()
    (ortak / "Model-Q4_K_M.gguf").write_bytes(b"x" * len(icerik))             # boyut doğru, içerik bozuk
    with pytest.raises(IndirmeHatasi, match="doğrulanamadı"):
        ModelIndirici(tmp_path / "m1", ayna=taban, ortak_klasor=str(ortak)).indir(m)
    (ortak / "Model-Q4_K_M.gguf").write_bytes(icerik)
    yol = ModelIndirici(tmp_path / "m2", ayna=taban, ortak_klasor=str(ortak)).indir(m)
    assert yol.read_bytes() == icerik
    with pytest.raises(IndirmeHatasi, match="desenine uyan"):
        ModelIndirici(tmp_path / "m3", ayna=taban).indir(
            ModelTanimi("yok", "Yok", "sohbet", "kurum/model-GGUF", r"IQ1\.gguf$", 0.1, 1))


# ------------------------------------------------------------------ llama-server yönetimi
def test_llama_sunucusu_sohbet_akis_ve_vektor(tmp_path, sahte_exe):
    model = _model_dosyasi(tmp_path, "sohbet", "sohbet")
    s = LlamaSunucusu(str(model), "sohbet", exe=sahte_exe, gunluk_klasoru=tmp_path)
    s.baslat(zaman_asimi=20)
    try:
        assert s.calisiyor()
        assert s.sohbet([{"role": "user", "content": "başkent?"}]) == "Ankara"         # <think> ayıklanır
        parcalar = []
        assert s.sohbet([{"role": "user", "content": "x"}], akis=parcalar.append) == "Ankara" and len(parcalar) > 2
        m = SunucuModeli(s, "sahte")
        assert m.hazir and m.hiz_olc()["cikti"] == "Ankara"
        with pytest.raises(ModelHatasi):
            s.vektor(["deneme"])                                               # gömme kapalı sunucu
    finally:
        s.durdur()
    assert not s.calisiyor()
    a = LlamaSunucusu(str(model), "anlam", exe=sahte_exe)
    a.baslat(zaman_asimi=20)
    try:
        v = a.vektor(["aylıksız izin", "aylıksız izin süresi", "harcırah"])
        assert v.shape == (3, 64) and np.allclose(np.linalg.norm(v, axis=1), 1.0)
        assert v[0] @ v[1] > v[0] @ v[2]
    finally:
        a.durdur()


def test_llama_sunucusu_eksik_model_ve_exe(tmp_path):
    with pytest.raises(ModelHatasi):
        LlamaSunucusu(str(tmp_path / "yok.gguf"), exe=sys.executable).baslat()
    s = LlamaSunucusu(str(tmp_path / "yok.gguf"), exe="")
    s.exe = ""
    with pytest.raises(ModelHatasi, match="bulunamadı"):
        s.baslat()


# ------------------------------------------------------------------ anlam dizini ve bütünleşme
def test_anlam_dizini_ve_hibrit_arama(kutuphane, tmp_path, sahte_exe):
    from akil_hocasi.answer.dogrulama import DogrulamaMotoru
    from akil_hocasi.answer.hat import CevapHatti
    from akil_hocasi.crawler.beyaz_liste import BIRINCIL
    s = LlamaSunucusu(str(_model_dosyasi(tmp_path, "anlam", "anlam")), "anlam", exe=sahte_exe)
    s.baslat(zaman_asimi=20)
    try:
        d = AnlamDizini(kutuphane, s, "anlam")
        assert d.ilerleme()[1] > 0 and d.ilerleme()[0] == 0
        assert d.eksikleri_isle() == d.ilerleme()[1]
        assert d.eksikleri_isle() == 0                                          # ikinci kez işlenmez
        sonuc = d.ara("yıllık izin süresi hizmet", 3)
        ilk = kutuphane.pasaj_getir(sonuc[0][0])
        assert ilk.madde_no == "3"                                              # "Yıllık izin" maddesi
        hat = CevapHatti(kutuphane, DogrulamaMotoru(kutuphane, BIRINCIL), anlam=d)
        c = hat.cevapla("hizmet süresine göre yıllık izin kaç gün", kayit=False)
        assert any(k.pasaj.madde_no == "3" for k in c.kaynaklar)
    finally:
        s.durdur()


def test_yz_yoneticisi_secer_baslatir_ve_degistirir(kutuphane, tmp_path, sahte_exe):
    from akil_hocasi.config import Ayarlar, Yollar
    from akil_hocasi.yz.yonetici import YZYoneticisi
    yollar = Yollar(tmp_path / "veri").olustur()
    ayarlar = Ayarlar(yollar.ayarlar)
    ayarlar.ayarla("yz.sunucu_yolu", sahte_exe)
    yz = YZYoneticisi(yollar, ayarlar, kutuphane)
    assert {m.tur for m in yz.eksik_kurulum()} == {"sohbet", "anlam"}
    _model_dosyasi(yollar.modeller, "qwen3.5-0.8b", "sohbet")
    _model_dosyasi(yollar.modeller, "qwen3-embedding-0.6b", "anlam")
    _model_dosyasi(yollar.modeller, "qwen3.5-2b", "sohbet")
    assert not yz.eksik_kurulum()
    try:
        d = yz.baslat()
        assert d["sohbet_calisiyor"] and d["anlam_calisiyor"] and yz.model.hazir
        assert yz.secili("sohbet")["kimlik"] == "qwen3.5-2b"                    # kurulu olanların en iyisi
        assert yz.anlam.hazir and yz.anlam.eksikleri_isle() > 0
        with pytest.raises(ModelHatasi):
            yz.sil("qwen3.5-2b")                                                 # çalışan model silinmez
        yz.model_degistir("qwen3.5-0.8b")
        assert yz.secili("sohbet")["kimlik"] == "qwen3.5-0.8b" and yz.model.hazir
        assert yz.sil("qwen3.5-2b")
    finally:
        yz.durdur()
    assert not yz.model.hazir


def test_istekler_onbellek_dostu_siralanir():
    from akil_hocasi.cekirdek.ilkeler import sistem_cekirdegi
    from akil_hocasi.yz.sunucu import onbellek_dostu
    m1 = onbellek_dostu([{"role": "system", "content": sistem_cekirdegi("Taslak yaz.")},
                         {"role": "user", "content": "KAYNAKLAR: uzun blok"}])
    m2 = onbellek_dostu([{"role": "system", "content": sistem_cekirdegi("Taslağı eleştir.")},
                         {"role": "user", "content": "KAYNAKLAR: uzun blok"}])
    assert m1[0] == m2[0] and "GÖREV" not in m1[0]["content"]            # sabit önek aynı
    assert m1[1]["content"].startswith("KAYNAKLAR: uzun blok") and m1[1]["content"].endswith("GÖREV: Taslak yaz.")
    sade = [{"role": "user", "content": "x"}]
    assert onbellek_dostu(sade) is sade
