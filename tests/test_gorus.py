"""Resmî görüş yazısından gerçek sınav öğesi: soru, dayanak, sonuç; kütüphaneye eşleme; eskimiş görüşün elenmesi."""

from akil_hocasi.ogrenme.gorus import dayanaklari_bul, gorus_ayristir, gorusten_sinav_ogesi

ORNEK = """T.C.
DEVLET PERSONEL BAŞKANLIĞI
Sayı : 12345678-000-1117                                                     11/02/2013
Konu : Refakat ve tetkik süreleri
İlgi : 01/01/2013 tarihli ve 55 sayılı yazınız.
İlgi yazınızda, Devlet memurlarının kendi hastalıkları nedeniyle sağlık kuruluşuna başvurdukları ve
bakmakla yükümlü oldukları yakınlarına refakat ettikleri sürelerin nasıl değerlendirileceği hususunda
Başkanlığımız görüşünün talep edildiği anlaşılmıştır.
Bilindiği üzere, 657 sayılı Devlet Memurları Kanununun 102, 104 ve 105 inci maddelerinde memurların
izinleri düzenlenmiş olup, anılan Kanunun 108 inci maddesinde aylıksız izin hükümlerine yer verilmiştir.
Aynı Kanunun 105 inci maddesinin son fıkrasında "memurun bakmakla yükümlü olduğu veya memur refakat
etmediği takdirde hayatı tehlikeye girecek olan ana, baba, eş ve çocukları ile kardeşlerinden birinin ağır
kaza geçirmesi veya ağır bir hastalığının bulunması" hâlinde refakat izni verilebileceği belirtilmiştir.
Ayrıca ilgili Yönetmeliğin 10 uncu maddesinde de usul ve esaslar belirlenmiştir.
Bu itibarla, sağlık kuruluşunda geçen muayene ve tetkik sürelerinin izinli sayılması, kötüye kullanımın
önlenmesi için belge istenebileceği mütalaa edilmektedir.
Bilgilerinize rica ederim.
"""


class _Pasaj:
    def __init__(self, metin):
        self.metin = metin


class _Kutuphane:
    def __init__(self, maddeler):
        self.maddeler = maddeler

    def madde_getir(self, kimlik, no, tarih=None):
        m = self.maddeler.get(f"{kimlik}/{no}")
        return _Pasaj(m) if m else None


def test_dayanaklar_ve_gonderme():
    d = dayanaklari_bul(ORNEK)
    assert ("657", "102") in d and ("657", "104") in d and ("657", "105") in d and ("657", "108") in d
    assert all(k == "657" for k, _ in d)                         # yönetmeliğin 10. maddesi kanuna bağlanmaz


def test_gorus_ayristir():
    g = gorus_ayristir(ORNEK, "https://ornek.edu.tr/g.pdf")
    assert g and g["tarih"] == "2013-02-11" and "refakat" in g["talep"].lower()
    assert g["sonuc"].startswith("Bu itibarla") and g["sonuc"].endswith("mütalaa edilmektedir")
    assert g["alintilar"] and "Sayı" not in g["talep"]


def test_esleme_ve_eskime():
    g = gorus_ayristir(ORNEK)
    guncel = "(Değişik) ... memurun bakmakla yükümlü olduğu veya memur refakat etmediği takdirde hayatı tehlikeye " \
             "girecek olan ana, baba, eş ve çocukları ile kardeşlerinden birinin ağır kaza geçirmesi ..."
    k = _Kutuphane({"MEV:1.5.657/105": guncel, "MEV:1.5.657/102": "yıllık izin", "MEV:1.5.657/108": "aylıksız"})
    o = gorusten_sinav_ogesi(k, g)
    assert o and "MEV:1.5.657/105" in o["beklenen_dayanak"] and "MEV:1.5.657/104" not in o["beklenen_dayanak"]
    eskimis = _Kutuphane({"MEV:1.5.657/105": "tamamen başka bir metin " * 10})
    assert gorusten_sinav_ogesi(eskimis, g) is None                # alıntı bugünkü metinde yok → elenir
    assert gorusten_sinav_ogesi(_Kutuphane({}), g) is None         # dayanak kütüphanede yok


def test_ogretmenle_soru_ve_varyasyon():
    import json

    from akil_hocasi.ogrenme.gorus import sinav_sorulari_kur

    class Ogretmen:
        def sohbet(self, mesajlar, **k):
            assert "KURUMUN SORUSU" in mesajlar[-1]["content"] and "[MEV:1.5.657/105]" in mesajlar[-1]["content"]
            return json.dumps({"soru": "Annem ameliyat olacak, refakat için izin alabilir miyim, kaç gün?",
                               "varyasyonlar": [
                                   {"soru": "sözleşmeliyim annem hastanede refakat izni var mı yıllıktan mı düşer",
                                    "degisiklik": "gundelik_dil", "ayni_dayanak": True, "beklenen_sonuc": "Verilir."},
                                   {"soru": "Kayınpederime refakat için hangi yönetmelik uygulanır?",
                                    "degisiklik": "iki_mevzuat", "ayni_dayanak": False, "beklenen_sonuc": "?"}]})

    k = _Kutuphane({"MEV:1.5.657/105": "refakat izni ..."})
    o = {"id": "abc", "talep": "refakat süreleri", "sonuc": "Bu itibarla ... mütalaa edilmektedir",
         "konu": "Refakat", "beklenen_dayanak": ["MEV:1.5.657/105"]}
    s = sinav_sorulari_kur(k, Ogretmen(), [o])
    assert [x["tur"] for x in s] == ["gercek", "varyasyon:gundelik_dil"]     # dayanağı değişen varyasyon alınmaz
    assert all(x["beklenen_dayanak"] == ["MEV:1.5.657/105"] and x["gorus_id"] == "abc" for x in s)


def test_kunye_tarihi_ve_on_ek():
    metin = ORNEK.replace("İlgi yazınızda, Devlet", "(10/7/2014-3512) Devlet").replace("11/02/2013", "")
    g = gorus_ayristir(metin)
    assert g and g["tarih"] == "2014-07-10" and g["talep"].startswith("Devlet memurlarının")
