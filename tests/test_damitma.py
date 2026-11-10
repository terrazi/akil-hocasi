"""Damıtma: öğretmen modelle programın kendi yordamları üzerinden eğitim verisi üretme ve süzme."""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from akil_hocasi.answer.dogrulama import DogrulamaMotoru
from akil_hocasi.answer.hat import CevapHatti
from akil_hocasi.cekirdek.dersler import DersHafizasi
from akil_hocasi.cekirdek.strateji import StratejiDeposu
from akil_hocasi.crawler.beyaz_liste import BIRINCIL
from akil_hocasi.yz import damitma
from akil_hocasi.yz.damitma import (Damitici, OgretmenModeli, dengele, egitim_metinleri, gorev_turu,
                                    ornekleri_oku)

IYI = "Memur isteği üzerine aylıksız izin en fazla ne kadar verilebilir?"
UYDURMA = "Görevde yükselme sınavında başarı için kaç puan gerekir?"
SINAV = "Bir memur aylıksız izni hangi formla ister, sınav sorusu olarak?"


def _ogretmen_cevabi(govde: dict) -> str:
    metin = "\n".join(m["content"] for m in govde["messages"])
    kullanici = govde["messages"][-1]["content"]
    sema = (govde.get("response_format") or {}).get("json_schema", {}).get("schema", {})
    ozellik = sema.get("properties", {})
    if not ozellik:                       # düşünen görevlerde şema gönderilmez; görev istemden anlaşılır
        ozellik = {"sentez": {"kisa_cevap": 1}, "duzeltme": {"kisa_cevap": 1}, "yazi": {"paragraflar": 1},
                   "yazi_duzeltme": {"paragraflar": 1}}.get(gorev_turu(govde["messages"]), {})
    kanun = re.search(r"\[(K\d+)\] 9999 sayılı Örnek Personel Kanunu, md\. 2\b", kullanici)
    k = kanun.group(1) if kanun else "K1"
    if "gelen_yazi" in ozellik:
        return json.dumps({"tur": "cevap", "talimat": "Başkanlığımızda aylıksız izin kullanan personel bulunmamaktadır.",
                           "gelen_yazi": "T.C.\nTOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ\nStrateji Geliştirme Daire Başkanlığı\n\n"
                                         "Sayı : E-12345678-841-123456   05.11.2026\nKonu : Aylıksız izin kullanan personel\n\n"
                                         "PERSONEL DAİRE BAŞKANLIĞINA\n\nAylıksız izin kullanan personelin "
                                         "Başkanlığımıza bildirilmesi gerekmektedir.\nBilgilerinizi rica ederim.\n"})
    if "paragraflar" in ozellik:
        return json.dumps({"konu": "", "eksik_bilgiler": [], "ekler": [], "paragraflar": [
            {"metin": "İlgi yazı ile aylıksız izin kullanan personel bilgisi istenmiştir.", "kaynaklar": []},
            {"metin": "Başkanlığımızda aylıksız izin kullanan personel bulunmamaktadır.", "kaynaklar": []}]})
    if "dersler" in ozellik:
        return json.dumps({"dersler": [{"yordam": "sentez", "ders": "Süre ve puan sorularında yalnız kaynakta yazan "
                                        "değeri yaz; kaynakta yoksa hüküm bulunamadığını söyle.",
                                        "kosul_terimleri": ["puan", "süre"], "ilke": "dogruluk"}]})
    if "sorular" in ozellik:
        return json.dumps({"sorular": [{"soru": IYI}]})
    if "çözümle" in metin and "personel_turu" in ozellik:
        return json.dumps({"konu": "izin", "niyet": "bilgi", "personel_turu": "657/4-A memur", "olgular": ["memur"],
                           "alt_sorular": ["Süre ne kadar?"], "terimler": ["aylıksız izin"], "eksik": [],
                           "zorluk": "orta"})
    if "karar" in ozellik:
        return json.dumps({"karar": "uygun", "sorunlar": []})
    if "kisa_cevap" in ozellik:
        soru = re.search(r"SORU: (.*)", kullanici)
        if soru and "aylıksız" in soru.group(1).lower():
            return json.dumps({"dogrudan_cevap": True, "guven": "kesin", "acik_nokta": "",
                               "kisa_cevap": [{"metin": "Memura isteği üzerine en fazla 6 ay aylıksız izin verilebilir.",
                                               "kaynaklar": [k]}],
                               "uygulama": [{"metin": "Şart: isteğin memurdan gelmesi — Bu durumda: talep memurdan geliyor.",
                                             "kaynaklar": [k]}],
                               "adimlar": [], "dikkat": [], "degerlendirme": []})
        return json.dumps({"dogrudan_cevap": True, "guven": "kesin", "acik_nokta": "",
                           "kisa_cevap": [{"metin": "Başarı için en az 85 puan gerekir.", "kaynaklar": [k]}],
                           "uygulama": [], "adimlar": [], "dikkat": [], "degerlendirme": []})
    return "{}"


@pytest.fixture
def ogretmen():
    class Isleyici(BaseHTTPRequestHandler):
        def log_message(self, *a):
            return

        def do_POST(self):
            govde = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            icerik = _ogretmen_cevabi(govde)
            dusunce = "Önce durumu çözümlüyorum." if govde["chat_template_kwargs"]["enable_thinking"] else ""
            b = json.dumps({"choices": [{"message": {"content": icerik, "reasoning_content": dusunce}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    sunucu = ThreadingHTTPServer(("127.0.0.1", 0), Isleyici)
    threading.Thread(target=sunucu.serve_forever, daemon=True).start()
    yield OgretmenModeli(f"http://127.0.0.1:{sunucu.server_address[1]}")
    sunucu.shutdown()


def _servisler(k):
    dersler = DersHafizasi(k)
    hat = CevapHatti(k, DogrulamaMotoru(k, BIRINCIL), strateji=StratejiDeposu(k), dersler=dersler)
    return SimpleNamespace(hat=hat, kutuphane=k, dersler=dersler, yz=None, ayarlar=None)


def test_gorev_turu_tanima():
    from akil_hocasi.cekirdek.ilkeler import sistem_cekirdegi
    from akil_hocasi.cekirdek.muhakeme import COZUMLEME_GOREVI
    from akil_hocasi.yz.sunucu import onbellek_dostu
    m = onbellek_dostu([{"role": "system", "content": sistem_cekirdegi(COZUMLEME_GOREVI)},
                        {"role": "user", "content": "İSTEK: x"}])
    assert gorev_turu(m) == "cozumleme" and gorev_turu([{"role": "user", "content": "selam"}]) == "diger"


def test_damitma_suzer_ve_kaydeder(kutuphane, ogretmen, tmp_path, monkeypatch):
    monkeypatch.setattr(damitma, "bolum_sec", lambda s: "sinav" if "sınav sorusu" in s else "egitim")
    s = _servisler(kutuphane)
    d = Damitici(s, ogretmen, tmp_path / "cikti")
    rapor = d.calistir(sure_dk=3, soru_hedefi=10, yazi_orani=0.3, paralel=2, ek_sorular=[
        {"id": "k-iyi", "soru": IYI + " (gerçek)", "dayanak": ["9999/2"]},
        {"id": "k-uyd", "soru": UYDURMA, "dayanak": []},
        {"id": "k-sinav", "soru": SINAV, "dayanak": ["9999/2"]}])
    assert s.hat.model.ad != "öğretmen"                                 # öğretmen yalnız damıtma sırasında
    satirlar = [json.loads(x) for x in (tmp_path / "cikti" / "ornekler.jsonl").read_text("utf-8").splitlines()]
    gorevler = {x["gorev"] for x in satirlar}
    assert {"soru", "cozumleme", "sentez", "ders", "yazi"} <= gorevler, gorevler
    sentezler = [x for x in satirlar if x["gorev"] == "sentez"]
    assert sentezler and all("85 puan" not in x["cevap"] for x in sentezler)      # uydurma cevap eğitime girmez
    assert all(x["soru_id"] != "k-sinav" for x in satirlar)                         # sınav sorusu eğitime girmez
    sinav = [json.loads(x) for x in (tmp_path / "cikti" / "sinav.jsonl").read_text("utf-8").splitlines()]
    assert [x["id"] for x in sinav] == ["k-sinav"]
    # istem, programın çalışırken gönderdiğiyle aynı biçimde: sabit çekirdek başta, görev kullanıcı içeriğinin sonunda
    ornek = sentezler[0]["messages"]
    assert ornek[0]["role"] == "system" and "GÖREV:" not in ornek[0]["content"] and "GÖREV:" in ornek[1]["content"]
    assert rapor.gecen_cevap >= 1 and rapor.yazi >= 1 and ogretmen.sayac["hata"] == 0
    # kaldığı yerden sürer: aynı sorular yeniden işlenmez
    d2 = Damitici(s, ogretmen, tmp_path / "cikti")
    assert not [h for h in d2.soru_havuzu([{"id": "k-iyi", "soru": "x"}]) if h["id"] == "k-iyi"]


def test_egitim_verisi_dengeleme_ve_uzunluk(tmp_path):
    dosya = tmp_path / "o.jsonl"
    satirlar = []
    for i in range(30):
        satirlar.append({"gorev": "sentez", "bolum": "egitim", "messages": [{"role": "user", "content": f"s{i}"}],
                         "cevap": "{}"})
    for i in range(5):
        satirlar.append({"gorev": "cozumleme", "bolum": "egitim", "messages": [{"role": "user", "content": f"c{i}"}],
                         "cevap": "{}"})
    satirlar.append({"gorev": "sentez", "bolum": "sinav", "messages": [{"role": "user", "content": "x"}], "cevap": "{}"})
    satirlar.append(dict(satirlar[0]))                                   # yineleme
    dosya.write_text("\n".join(json.dumps(x) for x in satirlar), "utf-8")
    ornekler = ornekleri_oku([dosya])
    assert len(ornekler) == 35                                           # sınav ve yineleme ayıklandı
    secilen = dengele(ornekler, toplam=20)
    assert sum(1 for o in secilen if o["gorev"] == "sentez") <= 13       # pay sınırı (%32 × 2)
    assert sum(1 for o in secilen if o["gorev"] == "cozumleme") == 5     # payının altındaki görev kırpılmaz
    metinler, atilan = egitim_metinleri(secilen + [{"gorev": "sentez", "messages": [{"role": "user", "content": "u" * 999}],
                                                    "cevap": "{}"}],
                                        lambda m: "".join(x["content"] for x in m), len, 200)
    assert atilan == 1 and all(set(x) == {"prompt", "completion", "gorev"} for x in metinler)


def test_dusunce_ayirma():
    from akil_hocasi.yz.damitma import dusunceyi_ayir
    assert dusunceyi_ayir('<think>a</think>\n{"x": 1}') == ('{"x": 1}', "a")
    assert dusunceyi_ayir('uzun düşünce</think>\n\n{"x": 1}') == ('{"x": 1}', "uzun düşünce")   # açılışı istemde
    assert dusunceyi_ayir('{"x": 1}') == ('{"x": 1}', "")


def test_kisa_yaz_notu_yalniz_istekte():
    from akil_hocasi.yz.damitma import kisa_yaz_notu
    m = [{"role": "system", "content": "s"}, {"role": "user", "content": "soru"}]
    g = kisa_yaz_notu(m, 500)
    assert m[-1]["content"] == "soru" and "Uzunluk sınırı" in g[-1]["content"] and "1050 karakter" in g[-1]["content"]


def test_dogrulanmis_taslak_ve_sik_sema():
    from akil_hocasi.yz.damitma import _cumle_anahtari, dogrulanmis_taslak, sik_sema
    v = {"dogrudan_cevap": True, "kisa_cevap": [{"metin": "Doğru cümle.", "kaynaklar": ["K1"]},
                                                {"metin": "Uydurma  85 puan.", "kaynaklar": ["K1"]}],
         "uygulama": [{"metin": "Şart: x — Bu durumda: y.", "kaynaklar": ["K1"]}], "guven": "kesin"}
    temiz, toplam, atilan = dogrulanmis_taslak(v, {_cumle_anahtari("Uydurma 85 puan.")})
    assert (toplam, atilan) == (3, 1) and [o["metin"] for o in temiz["kisa_cevap"]] == ["Doğru cümle."]
    assert v["kisa_cevap"][1]["metin"].startswith("Uydurma")                     # asıl taslak değişmez
    s = sik_sema({"type": "object", "properties": {"a": {"type": "array", "maxItems": 8}, "b": {"type": "array",
                                                                                              "maxItems": 2}}})
    assert s["properties"]["a"]["maxItems"] == 4 and s["properties"]["b"]["maxItems"] == 2
