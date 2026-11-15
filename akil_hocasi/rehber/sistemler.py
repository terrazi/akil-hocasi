"""Sistem kataloğu: TOGÜ personelinin kullandığı çevrim içi sistemler.

Bu katalog bilgi üretmez; yalnızca şunları tanımlar:
  · sistemin adı ve resmî giriş adresi (kullanıcının KENDİ tarayıcısında açılır; program giriş yapmaz),
  · kılavuzlarının arandığı herkese açık resmî sayfalar (tohumlar),
  · ekran görüntüsünden ve sorudan sistemi tanımak için kullanılan ayırt edici sözcükler.

"Nasıl yapılır" bilgisinin tamamı resmî kullanım kılavuzlarından (indirilen ya da kullanıcının eklediği) gelir.
Program bu sistemlere asla bağlanmaz, oturum açmaz, form doldurmaz ve veri göndermez.

Adresler 2026-11 itibarıyla resmî belgelerden doğrulanmıştır (bkz. tests/test_rehber.py). Doğrulanamayan
adres boş bırakılır; kullanıcı Ayarlar'dan kurumunun adresini girebilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.turkce import katla


@dataclass(frozen=True)
class Sistem:
    kimlik: str                         # "EBYS", "MYS", ...
    ad: str                             # tam ad
    kisa: str                           # ekranda kısa ad
    sahip: str                          # sistemi işleten kurum
    adres: str = ""                     # resmî giriş adresi (kullanıcının tarayıcısında açılır)
    kullananlar: tuple[str, ...] = ()
    tohumlar: tuple[str, ...] = ()      # kılavuzların listelendiği herkese açık sayfalar
    dosya_onekleri: tuple[str, ...] = ()  # sistem alan adında olsa bile indirilebilecek herkese açık dosya yolları
    anahtarlar: tuple[str, ...] = ()    # ekranda/soruda sistemi ayırt eden sözcükler (en ayırt edici başta)
    yayimlayan: tuple[str, ...] = ()    # kılavuzu yayımlayan kurumun belgede geçen adı
    alanlar: tuple[str, ...] = field(default=())  # sistemin kendi alan adları (adres çubuğu tanıma)
    anilis: str = ""                    # cümle içinde anılışı ("MYS ekranında"); boşsa kısa ad

    @property
    def ad_cumle(self) -> str:
        return self.anilis or self.kisa

    def anahtar_katli(self) -> list[str]:
        return [katla(a) for a in self.anahtarlar]


SISTEMLER: tuple[Sistem, ...] = (
    Sistem(
        "EBYS", "Elektronik Belge Yönetim Sistemi (TOGÜ, enVision)", "EBYS", "TOGÜ EBYS Ofisi / Bilgi İşlem",
        adres="https://ebys.gop.edu.tr",
        kullananlar=("Tüm personel", "Birim evrak sorumluları", "Yazı işleri"),
        tohumlar=("https://ebysyardim.gop.edu.tr/",),
        anahtarlar=("EBYS", "enVision", "Evrak Yaz", "Kurum İçi Gidecek Evrak", "Kurum Dışı Gidecek Evrak",
                    "Olur Evrakı", "E-İmzaya Sun", "Evrakın Gittiği Yer", "Gönderilen Makam", "Dosya Kodu",
                    "Paraf", "Amirimi Ekle", "Toplu Görev Tamamlama", "Detaylı Evrak Arama", "Gelen Evrak",
                    "Kep Gönderim Türü", "Vekalet"),
        yayimlayan=("Tokat Gaziosmanpaşa Üniversitesi", "TOGÜ"),
        alanlar=("ebys.gop.edu.tr", "ebysyardim.gop.edu.tr"),
    ),
    Sistem(
        "MYS", "Mali Yönetim Sistemi / Harcama Yönetim Sistemi (MYSV2)", "MYS (HYS)",
        "Hazine ve Maliye Bakanlığı Muhasebat Genel Müdürlüğü",
        adres="https://mysv2.hmb.gov.tr",
        kullananlar=("Strateji Geliştirme", "Harcama birimleri", "Gerçekleştirme görevlileri", "Harcama yetkilileri"),
        tohumlar=("https://muhasebat.hmb.gov.tr/e-uygulamalar", "https://muhasebat.hmb.gov.tr/",
                  "https://ms.hmb.gov.tr/"),
        anahtarlar=("MYSV2", "Harcama Yönetim Sistemi", "Mali Yönetim Sistemi", "Ödeme Emri Belgesi", "ÖEB",
                    "Harcama Talimatı Onay Belgesi", "Varlık İşlem Fişi", "e-Yolluk", "Taahhüt", "Emanet",
                    "Kamu Avans Kart", "Muhasebe İşlem Fişi", "Harcama Birimi Kimlik Yöneticisi"),
        yayimlayan=("Muhasebat Genel Müdürlüğü", "Hazine ve Maliye Bakanlığı"),
        alanlar=("mysv2.hmb.gov.tr", "mys.muhasebat.gov.tr"),
        anilis="MYS",
    ),
    Sistem(
        "KBS", "Kamu Harcama ve Muhasebe Bilişim Sistemi (maaş, ek ders, sosyal hak, fazla çalışma)", "KBS",
        "Hazine ve Maliye Bakanlığı Muhasebat Genel Müdürlüğü",
        adres="https://www.kbs.gov.tr",
        kullananlar=("Maaş mutemetleri", "Tahakkuk birimleri", "Strateji Geliştirme"),
        tohumlar=("https://www.kbs.gov.tr/", "https://muhasebat.hmb.gov.tr/"),
        anahtarlar=("KBS", "Kamu Harcama ve Muhasebe Bilişim Sistemi", "Maaş Uygulaması", "Maaş Bilgi Girişi",
                    "Ek Ders", "Sosyal Hak ve Yardım", "Fazla Çalışma", "Fiili Hizmet", "Matrah Birleştirme",
                    "Bireysel Emeklilik", "Bordro", "KPHYS", "Saymanlık İşlemleri", "Personel Listesi Yenile"),
        yayimlayan=("Muhasebat Genel Müdürlüğü", "Hazine ve Maliye Bakanlığı"),
        alanlar=("kbs.gov.tr", "kbs.muhasebat.gov.tr"),
    ),
    Sistem(
        "TKYS", "Taşınır Kayıt ve Yönetim Sistemi (KBS)", "Taşınır (TKYS)",
        "Hazine ve Maliye Bakanlığı Muhasebat Genel Müdürlüğü",
        adres="https://www.kbs.gov.tr/TMYS",
        kullananlar=("Taşınır kayıt ve kontrol yetkilileri", "Strateji Geliştirme"),
        tohumlar=("https://www.kbs.gov.tr/",),
        anahtarlar=("TKYS", "Taşınır Kayıt ve Yönetim Sistemi", "Taşınır Mallar Yönetim Sistemi",
                    "Taşınır İşlem Fişi", "TİF", "Zimmet", "Ambar", "Sayım", "Taşınır Kodu", "VİF"),
        yayimlayan=("Muhasebat Genel Müdürlüğü", "Hazine ve Maliye Bakanlığı"),
        alanlar=("kbs.gov.tr/TMYS",),
        anilis="KBS Taşınır (TKYS)",
    ),
    Sistem(
        "HITAP", "Hizmet Takip Programı (SGK, 4/c)", "HİTAP", "Sosyal Güvenlik Kurumu",
        adres="https://hitap.sgk.gov.tr/HitapWeb/",
        kullananlar=("Personel Daire Başkanlığı", "Özlük işleri"),
        tohumlar=("https://hitap.sgk.gov.tr/HitapWeb/",),
        dosya_onekleri=("https://hitap.sgk.gov.tr/HitapWeb/dosyalar/",),
        anahtarlar=("HİTAP", "Hizmet Takip Programı", "Hizmet Cetveli", "Özlük Bilgisi", "Tescil Yönetim Paneli",
                    "HİTAP Yönetim Paneli", "Borçlanma Başvuru", "Emeklilik Belgesi", "Açık Süre", "İtibari Hizmet",
                    "Unvan Bilgisi", "Tazminat Bilgisi"),
        yayimlayan=("Sosyal Güvenlik Kurumu", "Emeklilik Hizmetleri Genel Müdürlüğü"),
        alanlar=("hitap.sgk.gov.tr",),
    ),
    Sistem(
        "SGK", "SGK İşveren Uygulamaları (4/a işe giriş-çıkış, e-Bildirge, iş kazası bildirimi)", "SGK İşveren",
        "Sosyal Güvenlik Kurumu",
        adres="https://e.sgk.gov.tr/",
        kullananlar=("Personel Daire Başkanlığı", "Sözleşmeli/işçi personel işlemleri", "İSG"),
        tohumlar=("https://www.sgk.gov.tr/",),
        anahtarlar=("Sigortalı İşe Giriş", "İşten Ayrılış Bildirgesi", "e-Bildirge", "Aylık Prim ve Hizmet Belgesi",
                    "e-Sigorta", "İşyeri Sicil", "İş Kazası Bildirim", "Meslek Hastalığı", "4A", "4/a",
                    "Sigorta Primleri"),
        yayimlayan=("Sosyal Güvenlik Kurumu",),
        alanlar=("e.sgk.gov.tr", "uyg.sgk.gov.tr", "ebildirge.sgk.gov.tr"),
        anilis="SGK işveren uygulamaları",
    ),
    Sistem(
        "YOKSIS", "Yükseköğretim Bilgi Sistemi (YÖKSİS)", "YÖKSİS", "Yükseköğretim Kurulu",
        adres="https://yoksis.yok.gov.tr",
        kullananlar=("Personel Daire Başkanlığı", "Öğrenci İşleri", "Akademik personel"),
        tohumlar=("https://www.yok.gov.tr/",),
        anahtarlar=("YÖKSİS", "Personel İşlemleri", "Özgeçmiş İşlemleri", "Kullanıcı İşlemleri",
                    "Akademik Personel", "DOSAİ", "YÖK Akademik", "Yıllık Plan", "Kadro İşlemleri"),
        yayimlayan=("Yükseköğretim Kurulu",),
        alanlar=("yoksis.yok.gov.tr", "yoksis.gov.tr"),
    ),
    Sistem(
        "PBS", "YÖK Personel Bilgi Sistemi (idari personel, İGPS, becayiş)", "YÖK PBS", "Yükseköğretim Kurulu",
        adres="https://pbs.yok.gov.tr",
        kullananlar=("Personel Daire Başkanlığı", "İdari personel"),
        tohumlar=("https://www.yok.gov.tr/",),
        anahtarlar=("Personel Bilgi Sistemi", "İGPS", "Üniversite İdari Personel", "Becayiş",
                    "Karşılıklı Naklen Atanma", "pbs.yok"),
        yayimlayan=("Yükseköğretim Kurulu",),
        alanlar=("pbs.yok.gov.tr", "igps.yok.gov.tr"),
    ),
    Sistem(
        "EKAP", "Elektronik Kamu Alımları Platformu (EKAP)", "EKAP", "Kamu İhale Kurumu",
        adres="https://ekapv2.kik.gov.tr",
        kullananlar=("Satın alma birimleri", "İhale komisyonları", "Doğrudan temin görevlileri"),
        tohumlar=("https://www.kik.gov.tr/",),
        anahtarlar=("EKAP", "Elektronik Kamu Alımları Platformu", "İhale Kayıt Numarası", "İKN", "Doğrudan Temin",
                    "e-Fiyat Teklifi", "Platform Sorumlusu", "e-Teklif", "Elektronik Eksiltme", "Teklif Kabul"),
        yayimlayan=("Kamu İhale Kurumu",),
        alanlar=("ekapv2.kik.gov.tr", "ekap.kik.gov.tr"),
    ),
    Sistem(
        "KARIYER", "Kariyer Kapısı – Kamu İşe Alım", "Kariyer Kapısı", "Cumhurbaşkanlığı İnsan Kaynakları Ofisi",
        adres="https://isealimkariyerkapisi.cbiko.gov.tr",
        kullananlar=("Personel Daire Başkanlığı (sözleşmeli personel ve işe alım ilanları)",),
        tohumlar=("https://www.cbiko.gov.tr/",),
        anahtarlar=("Kariyer Kapısı", "Kamu İşe Alım", "İlan Yönetimi", "Başvurularım", "Başvuru Alındı",
                    "Aday Bilgileri", "cbiko"),
        yayimlayan=("Cumhurbaşkanlığı İnsan Kaynakları Ofisi",),
        alanlar=("isealimkariyerkapisi.cbiko.gov.tr", "kariyerkapisi.cbiko.gov.tr"),
    ),
    Sistem(
        "OSYM", "ÖSYM sistemleri (KPSS: Aday İşlemleri, Sonuç Açıklama, Sonuç Belgesi Doğrulama)", "ÖSYM / KPSS",
        "Ölçme, Seçme ve Yerleştirme Merkezi",
        adres="https://ais.osym.gov.tr",
        kullananlar=("Personel Daire Başkanlığı (KPSS ile alım ve yerleştirme)",),
        tohumlar=("https://www.osym.gov.tr/",),
        anahtarlar=("ÖSYM", "KPSS", "Aday İşlemleri Sistemi", "Sonuç Belgesi Doğrulama", "Sonuç Açıklama",
                    "Tercih Kılavuzu", "Yerleştirme", "KPSSP3", "KPSSP93", "KPSSP94"),
        yayimlayan=("Ölçme, Seçme ve Yerleştirme Merkezi", "ÖSYM"),
        alanlar=("ais.osym.gov.tr", "sonuc.osym.gov.tr", "osym.gov.tr"),
        anilis="ÖSYM sistemi",
    ),
    Sistem(
        "EIMZA", "Elektronik imza (Kamu SM nitelikli elektronik sertifika)", "e-İmza", "Kamu Sertifikasyon Merkezi",
        adres="https://onlineislemler.kamusm.gov.tr",
        kullananlar=("Tüm personel (EBYS ve MYS imzası)",),
        tohumlar=("https://kamusm.bilgem.tubitak.gov.tr/",),
        anahtarlar=("Kamu SM", "Nitelikli Elektronik Sertifika", "NES", "PIN", "Kart Okuyucu", "Cannot Encode",
                    "Sertifika Deposu", "Kilit Çözme", "Akis", "e-İmza"),
        yayimlayan=("Kamu Sertifikasyon Merkezi", "TÜBİTAK BİLGEM"),
        alanlar=("onlineislemler.kamusm.gov.tr", "kamusm.bilgem.tubitak.gov.tr"),
        anilis="e-İmza uygulaması",
    ),
    Sistem(
        "DETSIS", "Devlet Teşkilatı Merkezi Kayıt Sistemi (DETSİS)", "DETSİS", "Cumhurbaşkanlığı",
        kullananlar=("Personel Daire Başkanlığı", "Strateji Geliştirme"),
        anahtarlar=("DETSİS", "Devlet Teşkilatı Merkezi Kayıt Sistemi", "DETSİS Numarası", "Personel Ekle"),
    ),
    Sistem(
        "KEP", "Kayıtlı Elektronik Posta (KEP)", "KEP", "KEP hizmet sağlayıcısı",
        kullananlar=("Yazı işleri", "Birim evrak sorumluları"),
        anahtarlar=("Kayıtlı Elektronik Posta", "KEP", "hs03.kep.tr", "KEP Adresi", "Kep Gönderim"),
    ),
    Sistem(
        "TOGU", "TOGÜ birim sistemleri (OBS, PBS, BAP, e-posta ve diğerleri)", "TOGÜ sistemleri",
        "Tokat Gaziosmanpaşa Üniversitesi",
        kullananlar=("Tüm personel",),
        tohumlar=("https://www.gop.edu.tr/", "https://bidb.gop.edu.tr/", "https://personel.gop.edu.tr/",
                  "https://strateji.gop.edu.tr/"),
        anahtarlar=("Öğrenci Bilgi Sistemi", "OBS", "Personel Bilgi Sistemi", "BAP", "UBYS", "Eduroam", "VPN",
                    "gop.edu.tr", "Webmail"),
        yayimlayan=("Tokat Gaziosmanpaşa Üniversitesi", "TOGÜ"),
        alanlar=("obs.gop.edu.tr", "pbs.gop.edu.tr", "bap.gop.edu.tr", "mail.gop.edu.tr"),
    ),
)

_SOZLUK = {s.kimlik: s for s in SISTEMLER}

# Kılavuz bağlantısını seçerken bağlantı metninde/adresinde aranan sözcükler (katlanmış)
KILAVUZ_SOZCUKLERI = ("kilavuz", "klavuz", "kullanim", "kullanma", "rehber", "yardim", "sunum", "egitim dokuman",
                      "egitim sunu", "dokuman", "nasil", "adim adim", "sss", "sikca sorulan", "uygulama",
                      "user guide", "manual", "el kitab")


def sistem(kimlik: str) -> Sistem | None:
    return _SOZLUK.get((kimlik or "").upper())


def sistem_bul(metin: str, en_az_puan: float = 2.0) -> list[tuple[Sistem, float, list[str]]]:
    """Metinde (soru, ekran görüntüsü metni) geçen sistemleri puanlar; büyükten küçüğe döndürür.

    Alan adı (adres çubuğu) en güçlü işarettir; çok sözcüklü ayırt edici adlar tek sözcüklerden ağır basar.
    Kısa kısaltmalar (KBS, ÖEB, KEP...) yalnızca bütün sözcük olarak sayılır.
    """
    import re

    k = " " + katla(metin or "") + " "
    sonuc = []
    for s in SISTEMLER:
        puan, eslesen = 0.0, []
        for alan in s.alanlar:
            if katla(alan) in k:
                puan += 6.0
                eslesen.append(alan)
        for ham, a in zip(s.anahtarlar, s.anahtar_katli(), strict=True):
            if len(a) <= 5:
                bulundu = re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", k) is not None
            else:
                bulundu = a in k
            if bulundu:
                puan += 1.0 + min(len(a.split()), 4) * 0.75 + (0.5 if ham.isupper() and len(a) >= 3 else 0)
                eslesen.append(ham)
        if puan >= en_az_puan:
            sonuc.append((s, round(puan, 2), eslesen))
    sonuc.sort(key=lambda x: -x[1])
    return sonuc
