"""Sistem Rehberi: TOGÜ personelinin kullandığı çevrim içi sistemlerde (EBYS, MYS, KBS, HİTAP, SGK, YÖKSİS, YÖK PBS,
EKAP, Kariyer Kapısı, ÖSYM/KPSS, e-İmza, TOGÜ birim sistemleri) adım adım yol gösterme.

İlke: program bu sistemlere bağlanmaz, giriş yapmaz, ekranlarına dokunmaz. Yol göstermenin tek kaynağı resmî
kullanım kılavuzlarıdır (resmî sitelerden kendisi bulur ya da kullanıcı ekler). Her adım ve her ekran/düğme adı
kılavuzun ilgili sayfasıyla birlikte verilir; kılavuzda olmayan ekran adı söylenmez.
"""

from __future__ import annotations

import re

from ..core.turkce import katla
from .ekran import EkranAnalizi, ekrani_coz
from .kilavuz import KILAVUZ_TURLERI, KilavuzBelgesi, ayristir, kilavuz_etiketi, sayfa_goruntusu
from .sistemler import SISTEMLER, Sistem, sistem, sistem_bul

__all__ = ["SISTEMLER", "Sistem", "SistemRehberi", "EkranAnalizi", "KilavuzBelgesi", "KILAVUZ_TURLERI", "ayristir",
           "kilavuz_sorulari", "kilavuz_kaydi_yukle",
           "ekrani_coz", "kilavuz_etiketi", "sayfa_goruntusu", "sistem", "sistem_bul", "kullanim_sorusu_mu"]

_KULLANIM = re.compile(
    r"\b(nas[ıi]l|nereden|nerede|hangi\s+(?:men[üu]|ekran|sekme|d[üu]ğme|buton)|ekran|men[üu]|sekme|d[üu]ğme|"
    r"buton|t[ıi]kla|giri[şs]\s+yap|[şs]ifre|hata\s+al|hata\s+veriyor|uyar[ıi]|imzala(?:yam|nm)|kaydedemi|"
    r"g[öo]nderemi|g[öo]r[üu]nm[üu]yor|a[çc][ıi]lm[ıi]yor|yetki|rol\s+tan[ıi]m|y[üu]kle(?:yemi)?|"
    r"onaya\s+g[öo]nder|adım|ad[ıi]m)", re.IGNORECASE)

_GOREV_BASLIGI = re.compile(
    r"(?<![a-zçğıöşüA-ZÇĞİÖŞÜ])(olu[şs]tur|giri[şs]i|ekle|yaz|g[öo]nder|imzala|onay|sorgula|listele|d[üu]zenle|"
    r"g[üu]ncelle|iptal|sil|aktar|y[üu]kle|tan[ıi]mla|hesapla|ba[şs]vur|i[şs]lem|raporla|yazd[ıi]r|arama|kayd|"
    r"kay[ıi]t|giri[şs] yap|[şs]ifre|sevk|havale|teslim|devir|zimmet|ödeme|tahakkuk)", re.IGNORECASE)
_GOREV_DEGIL = re.compile(r"^(?:şekil|sekil|tablo|resim|ek[-\s]?\d|doküman|dokuman|sayfa|not\b)|kılavuzun sonuna|"
                          r"sürüm numarası|yayın tarihi|garanti|sorumluluk|yükümlülük", re.IGNORECASE)


def gorev_basligi(baslik: str) -> str:
    """Kılavuz bölüm başlığından görev adı ("Ödeme Emri Belgesi Oluşturma"); görev değilse boş.

    Numara ve işaretler atılır; "A — B" birleşik başlıkta görev bildiren en uzun parça seçilir; küçük harfle başlayan
    (cümle parçası), çok uzun ya da tek sözcüklük genel başlıklar görev sayılmaz. Metin kılavuzdaki gibi kalır.
    """
    parcalar = []
    for p in re.split(r"\s+—\s+", baslik or ""):
        p = re.sub(r"^[\s\-–—•:]*(?:\d{1,2}(?:[.)-]\d{0,2})*[.)-]?\s*|[A-HIVX]{1,4}[.)]\s+)?", "", p).strip(" .:;-–—")
        if len(p) >= 6 and p[:1].isupper() and len(p.split()) <= 9 and katla(p) not in ("not", "uyari", "dikkat") \
                and not _GOREV_DEGIL.search(p) and p.count(":") == 0:
            parcalar.append(p)
    adaylar = [p for p in dict.fromkeys(parcalar) if _GOREV_BASLIGI.search(p) and len(p) <= 80]
    return max(adaylar, key=len) if adaylar else ""


def kullanim_sorusu_mu(soru: str) -> tuple[Sistem | None, bool]:
    """Soru bir sistemin kullanımıyla mı ilgili? (sistem, kullanım kalıbı var mı)."""
    bulunan = sistem_bul(soru, en_az_puan=1.75)
    s = bulunan[0][0] if bulunan else None
    return s, bool(_KULLANIM.search(soru or ""))


def _terimler(soru: str, s: Sistem | None) -> list[str]:
    from ..library.db import _terim_kok

    durak = {"nasil", "nedir", "hangi", "icin", "olan", "olarak", "yapilir", "yaparim", "ederim", "nerede",
             "nereden", "gerekir", "ekraninda", "ekrani", "sistem", "sisteminde", "sistemde", "takildim"}
    sistem_k = set(" ".join(s.anahtar_katli()).split()) if s else set()
    return [_terim_kok(w) for w in re.findall(r"[a-z0-9]+", katla(soru))
            if len(w) >= 3 and w not in durak and w not in sistem_k]


class SistemRehberi:
    def __init__(self, kutuphane, depo=None):
        self.kutuphane = kutuphane
        self.depo = depo
        self._toplayici = None

    # ------------------------------------------------------------------ katalog ve kılavuzlar
    def sistemler(self) -> list[dict]:
        kilavuzlar = self.kutuphane.belgeleri_listele("KLV:", KILAVUZ_TURLERI) if self.kutuphane else []
        sonuc = []
        for s in SISTEMLER:
            ait = [k for k in kilavuzlar if k["kimlik"].startswith(f"KLV:{s.kimlik}:")]
            son = max((k["indirme_tarihi"] or "" for k in ait), default="")
            sonuc.append({"kimlik": s.kimlik, "ad": s.ad, "kisa": s.kisa, "sahip": s.sahip, "adres": s.adres,
                          "kullananlar": list(s.kullananlar), "kilavuz": len(ait),
                          "bolum": sum(k["bolum"] or 0 for k in ait), "son_guncelleme": son,
                          "kendi_bulur": bool(s.tohumlar)})
        return sonuc

    def kilavuzlar(self, sistem_kimlik: str) -> list[dict]:
        return self.kutuphane.belgeleri_listele(f"KLV:{sistem_kimlik}:", KILAVUZ_TURLERI)

    def bolumler(self, belge_kimlik: str) -> list:
        return self.kutuphane.belge_maddeleri(belge_kimlik)

    def sik_islemler(self, sistem_kimlik: str, n: int = 14) -> list[dict]:
        """Kılavuz başlıklarından "nasıl yapılır" listesi (ör. "Kurum İçi Gidecek Evrak Yaz", "Ödeme Emri Belgesi
        Oluşturma"). Başlıklar kılavuzdan gelir; program başlık uydurmaz."""
        sonuc, goruldu = [], set()
        for k in self.kilavuzlar(sistem_kimlik):
            for p in self.bolumler(k["kimlik"]):
                b = gorev_basligi(p.baslik)
                anahtar = katla(b)
                if not b or anahtar in goruldu:
                    continue
                if any(x in anahtar for x in ("icindekiler", "amac", "kapsam", "tanimlar")):
                    continue
                goruldu.add(anahtar)
                sonuc.append({"baslik": b, "belge": k["kimlik"], "madde_id": p.madde_id, "sayfa": p.madde_no,
                              "kaynak": k["baslik"]})
        return sonuc[:n]

    def ara(self, soru: str, sistem_kimlik: str | None = None, limit: int = 8) -> list:
        s = sistem(sistem_kimlik) if sistem_kimlik else kullanim_sorusu_mu(soru)[0]
        adaylar = self.kutuphane.ara(soru, limit=limit * 4, turler=KILAVUZ_TURLERI)
        if s is not None:
            sistemin = [p for p in adaylar if p.belge_kimlik.startswith(f"KLV:{s.kimlik}:")]
            adaylar = sistemin or adaylar
        # bölüm başlığı soruyla örtüşen ("ödeme emri belgesi oluşturma") öne geçer: kılavuzlar görev başlıklıdır
        terimler = _terimler(soru, s)
        if terimler:
            taban = max((p.skor for p in adaylar), default=1.0) or 1.0
            for p in adaylar:
                b, m = katla(p.baslik), katla(p.metin)
                p.skor += taban * (1.5 * sum(t in b for t in terimler) + 0.5 * sum(t in m for t in terimler)) \
                    / len(terimler)
            adaylar.sort(key=lambda p: -p.skor)
        return adaylar[:limit]

    def sayfa_goruntusu(self, belge_kimlik: str, sayfa: int | str, olcek: float = 1.6) -> bytes | None:
        try:
            no = int(str(sayfa).split("-")[0])
        except ValueError:
            return None
        for k in self.kutuphane.belgeleri_listele(belge_kimlik):
            if k["kimlik"] == belge_kimlik and k["dosya_yolu"]:
                return sayfa_goruntusu(k["dosya_yolu"], no, olcek)
        return None

    # ------------------------------------------------------------------ ekran
    def ekran(self, ocr_metni: str, soru: str = "") -> EkranAnalizi:
        return ekrani_coz(ocr_metni, self.kutuphane, soru)

    # ------------------------------------------------------------------ öğrenme
    def toplayici(self):
        if self._toplayici is None:
            from .toplayici import KilavuzToplayici
            self._toplayici = KilavuzToplayici(self.kutuphane, self.depo)
        return self._toplayici


_SORU_KALIPLARI = (
    "{kisa} üzerinde “{baslik}” işlemini adım adım nasıl yaparım?",
    "“{baslik}” işlemi için {kisa} içinde hangi menüden başlamalıyım ve hangi adımları izlemeliyim?",
    "{kisa} ekranında “{baslik}” işlemini nasıl tamamlarım?",
)
_ILETI = re.compile(r"[“\"]([^”\"]{12,140})[”\"]\s*(?:hatası|uyarısı|mesajı|iletisi|ibaresi|ifadesi)", re.IGNORECASE)


def kilavuz_sorulari(kutuphane, sinir: int = 400) -> list[dict]:
    """Kılavuz bölümlerinden sistem kullanımı soruları: bölüm başlığı (görev) ve kılavuzda geçen hata/uyarı iletileri.

    Sorunun içeriği kılavuzun kendi metninden gelir (başlık ya da ileti birebir); dayanağı o bölümdür. Eğitim verisinde
    ve sınavda (dayanak bulundu mu?) kullanılır; sınava ayrılanlar eğitime girmez (damitma.bolum_sec).
    """
    import hashlib

    sorular, goruldu = [], set()
    for k in kutuphane.belgeleri_listele("KLV:", KILAVUZ_TURLERI):
        s = sistem(k["kimlik"].split(":")[1])
        if s is None:
            continue
        for p in kutuphane.belge_maddeleri(k["kimlik"]):
            dayanak = [f"{p.belge_kimlik}/{p.madde_no}"]
            b = gorev_basligi(p.baslik)
            adim_sayisi = len(re.findall(r"(?m)^\s*(?:\d{1,2}\s*[-.)]|[•●▪\-–]\s)", p.metin))
            if b and (adim_sayisi >= 2 or len(p.metin) >= 200):
                anahtar = (s.kimlik, katla(b))
                if anahtar not in goruldu:
                    goruldu.add(anahtar)
                    i = int(hashlib.md5(f"{s.kimlik}{b}".encode()).hexdigest(), 16) % len(_SORU_KALIPLARI)
                    sorular.append({"id": f"klv-{hashlib.sha1((p.belge_kimlik + b).encode()).hexdigest()[:10]}",
                                    "soru": _SORU_KALIPLARI[i].format(kisa=s.ad_cumle, baslik=b), "dayanak": dayanak,
                                    "tur": "kilavuz_islem", "sistem": s.kimlik})
            for m in _ILETI.finditer(p.metin):
                ileti = re.sub(r"\s+", " ", m.group(1)).strip(" .")
                anahtar = (s.kimlik, katla(ileti))
                if anahtar in goruldu:
                    continue
                goruldu.add(anahtar)
                tur = "uyarısı" if "uyar" in katla(m.group(0)) else "hatası"
                sorular.append({"id": f"klv-{hashlib.sha1((p.belge_kimlik + ileti).encode()).hexdigest()[:10]}",
                                "soru": f"{s.ad_cumle} ekranında “{ileti}” {tur} alıyorum. Ne yapmalıyım?",
                                "dayanak": dayanak, "tur": "kilavuz_hata", "sistem": s.kimlik})
    return sorular[:sinir]


def kilavuz_kaydi_yukle(kutuphane, kayit: dict) -> str:
    """kilavuz_topla çıktısındaki bir kılavuzu (bölümleriyle) kütüphaneye yazar (Kaggle veri turu)."""
    from ..library.ayristirici import MaddeParcasi
    import hashlib

    bolumler = [MaddeParcasi(madde_no=str(b["no"]), metin=b["metin"], baslik=b.get("baslik", ""))
                for b in kayit.get("bolumler", []) if b.get("metin")]
    if not bolumler:
        return "bos"
    metin = "\n\n".join(f"{b.baslik}\n{b.metin}" for b in bolumler)
    return kutuphane.belge_kaydet(
        tur="kilavuz", kimlik=kayit["kimlik"], baslik=kayit["baslik"], metin=metin,
        sha256=hashlib.sha256(metin.encode("utf-8")).hexdigest(), kaynak_url=kayit.get("url", ""),
        kaynak_turu="Kullanım kılavuzu", birim=kayit.get("sistem", ""), rv=kayit.get("surum", ""),
        yayin_tarihi=kayit.get("tarih", ""), maddeler=bolumler)
