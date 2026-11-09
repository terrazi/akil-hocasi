"""Resmî yazının yapısı (Yönetmelik md. 10–27) ve yazı türleri."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

YONETMELIK = "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik (RG 10.06.2020/31151)"

# Yazı türleri: amaç → varsayılan bitiş amacı ve dil modeline verilen yönerge
YAZI_TURLERI: dict[str, dict] = {
    "cevap": {"ad": "Gelen yazıya cevap", "amac": "bilgi",
              "yonerge": "İlgi yazıda istenen hususa birimin cevabını ver: istenen bilgiyi/görüşü dayanağıyla bildir."},
    "bilgi_isteme": {"ad": "Bilgi / belge isteme", "amac": "gereği",
                     "yonerge": "İstenen bilgi veya belgeyi, gerekçesini ve varsa süresini açıkça yaz."},
    "gorus": {"ad": "Görüş bildirme", "amac": "bilgi",
              "yonerge": "Konuya ilişkin mevzuat hükmünü ve birimin görüşünü gerekçesiyle bildir; görüşün yetkili makamca "
                         "değerlendirileceğini dikkate al."},
    "talep": {"ad": "Talep / teklif (üst makama)", "amac": "gereği",
              "yonerge": "Talebi, gerekçesini ve dayanağını yaz; uygun görülmesini iste."},
    "duyuru": {"ad": "Duyuru / dağıtımlı yazı", "amac": "bilgi_ve_gereği",
               "yonerge": "Duyurulacak hususu, uygulama tarihini ve yapılması gerekenleri açıkça yaz."},
    "ek_gonderme": {"ad": "Ek gönderme (üst yazı)", "amac": "bilgi",
                    "yonerge": "Ekte gönderilen belgeleri ve gönderilme nedenini kısaca yaz."},
    "olur": {"ad": "Olur (onay) yazısı", "amac": "olur",
             "yonerge": "Onaya sunulan işlemi, dayanağını ve gerekçesini yaz; son paragraf 'Makamlarınızca da uygun "
                        "görülmesi hâlinde olurlarınıza arz ederim.' biçiminde biter."},
}

# Muhatabın gönderen makama göre konumu → bitiş ifadesi (md. 16)
MAKAM_ILISKILERI = {
    "ust": "Üst makama",
    "ayni": "Aynı düzey makama",
    "alt": "Alt makama",
    "karisik": "Hem üst hem alt makama (dağıtımlı)",
    "kisi": "Gerçek kişiye",
}


@dataclass
class Ilgi:
    tarih: str = ""                 # GG.AA.YYYY
    sayi: str = ""                  # E-... (gelen belgedeki sayı, olduğu gibi)
    idare: str = ""                 # gönderen idare (muhatap idarenin kendisiyse boş bırakılır)
    tur: str = "yazı"               # yazı | başlıklı yazı | e-posta | başvuru | dilekçe | olur
    kisi: str = ""                  # gerçek kişi başvurusunda ad soyad
    metin: str = ""                 # elle yazılmış ilgi satırı (doluysa öncelikli)


@dataclass
class Imza:
    ad: str = ""
    soyad: str = ""
    unvan: str = ""
    on_unvan: str = ""              # akademik unvan ya da rütbe (Prof. Dr.)
    yetki: str = ""                 # yetki devri: "Rektör a." / vekâlet: "Rektör V."


@dataclass
class Iletisim:
    adres: str = ""
    telefon: str = ""
    faks: str = ""
    eposta: str = ""
    kep: str = ""
    internet: str = ""
    bilgi_ad: str = ""
    bilgi_unvan: str = ""
    bilgi_telefon: str = ""


@dataclass
class Paragraf:
    metin: str
    kaynaklar: list[str] = field(default_factory=list)     # danışma hattının kaynak kimlikleri (K1, K2…)
    tur: str = "metin"                                     # metin | dayanak | bitis | yer_tutucu


@dataclass
class Yazi:
    tur: str = "cevap"
    baslik: list[str] = field(default_factory=lambda: ["T.C."])   # T.C. / İDARE ADI / Birim adı
    dosya_kodu: str = ""                     # standart dosya planı kodu (biliniyorsa); sayının kalanını EBYS verir
    konu: str = ""
    muhatap: str = ""                        # idare adı (yalın ya da yönelme hâlinde) veya "Sayın Ad SOYAD"
    muhatap_birim: str = ""                  # parantez içindeki birim satırı
    muhatap_adres: list[str] = field(default_factory=list)
    kisiye: bool = False
    dagitimli: bool = False
    makam: str = "ayni"
    ilgiler: list[Ilgi] = field(default_factory=list)
    paragraflar: list[Paragraf] = field(default_factory=list)
    imza: Imza = field(default_factory=Imza)
    ekler: list[str] = field(default_factory=list)
    gereği: list[str] = field(default_factory=list)
    bilgi: list[str] = field(default_factory=list)
    olur: Imza | None = None                 # olur yazısında oluru verecek makam
    ivedilik: str = ""                       # "" | ACELE | GÜNLÜDÜR
    cevap_suresi: str = ""                   # GÜNLÜDÜR ise metinde yazılması gereken süre/tarih
    gizlilik: str = ""                       # "" | HİZMETE ÖZEL
    iletisim: Iletisim = field(default_factory=Iletisim)
    yazi_tipi: str = "Times New Roman"
    logo: bool = False
    dayanaklar: list[dict] = field(default_factory=list)   # [{kid, etiket, url, alinti}] doğrulanmış kaynaklar
    eksikler: list[str] = field(default_factory=list)      # kullanıcının tamamlaması gereken bilgiler
    istenenler: list[str] = field(default_factory=list)    # gelen yazıda istenen hususlar (karşılanmalı)

    def sozluk(self) -> dict:
        return asdict(self)

    @classmethod
    def sozlukten(cls, v: dict) -> Yazi:
        v = dict(v)
        v["ilgiler"] = [Ilgi(**i) for i in v.get("ilgiler", [])]
        v["paragraflar"] = [Paragraf(**p) for p in v.get("paragraflar", [])]
        v["imza"] = Imza(**v.get("imza", {}))
        v["olur"] = Imza(**v["olur"]) if v.get("olur") else None
        v["iletisim"] = Iletisim(**v.get("iletisim", {}))
        return cls(**{k: v[k] for k in v if k in cls.__dataclass_fields__})
