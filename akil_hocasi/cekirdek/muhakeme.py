"""Muhakeme döngüsü: her iş aynı yolu izler ve izlediği yol kaydedilir ("Nasıl düşündüm").

  ANLA → NETLEŞTİR → PLANLA → ARAŞTIR → UYGULA → DENETLE → SUN → ÖĞREN

Bu modül döngünün ortak parçalarını sağlar: durum çözümlemesi (olgular, personel türü, tarih, alt sorular,
eksik bilgiler), sohbet bağlamı (önceki sorular), düşünce kaydı. Dil modeli yoksa kurallarla çalışır.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field

from ..core.turkce import katla
from .ilkeler import sistem_cekirdegi

ASAMALAR = {
    "anla": "Anla", "netlestir": "Netleştir", "planla": "Planla", "arastir": "Araştır",
    "uygula": "Uygula", "denetle": "Denetle", "sun": "Sun", "ogren": "Öğren",
}

PERSONEL_TURLERI = ("657/4-A memur", "657/4-B sözleşmeli", "2547 akademik", "4857 işçi", "sözleşmeli/diğer", "belirsiz")

_TUR_DESENLERI = [
    (r"\b4\s*/\s*b\b|\b4b\b|sözleşmeli personel|sozlesmeli personel", "657/4-B sözleşmeli"),
    (r"\b4\s*/\s*a\b|kadrolu|devlet memur|\bmemur", "657/4-A memur"),
    (r"öğretim üyesi|ogretim uyesi|öğretim görevlisi|ogretim gorevlisi|araştırma görevlisi|arastirma gorevlisi|"
     r"akademik personel|doçent|docent|profesör|profesor|dr\. öğr|2547", "2547 akademik"),
    (r"\bişçi|\bisci|4857", "4857 işçi"),
]
_TARIH = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
_YAZI_NIYETI = re.compile(r"\b(yazı|yazi|yazısı|yazisi|üst yazı|ust yazi|cevap yaz|cevabi yaz|cevabını yaz|"
                          r"dilekçe|dilekce|olur yaz|resmi yaz|resmî yaz|taslak hazırla|taslak hazirla)\b", re.I)
_HESAP_NIYETI = re.compile(r"\b(hesapla|hesabı|hesabi|kaç gün|kac gun|ne kadar ödenir|tutar[ıi]? ne)\b", re.I)


@dataclass
class DusunceAdimi:
    asama: str
    baslik: str
    ayrinti: str = ""
    sure_sn: float = 0.0


@dataclass
class DusunceKaydi:
    adimlar: list[DusunceAdimi] = field(default_factory=list)
    _bas: float = field(default_factory=time.monotonic, repr=False)

    def ekle(self, asama: str, baslik: str, ayrinti: str = "") -> None:
        simdi = time.monotonic()
        self.adimlar.append(DusunceAdimi(asama, baslik, ayrinti, round(simdi - self._bas, 2)))
        self._bas = simdi

    def satirlar(self) -> list[str]:
        return [f"{ASAMALAR.get(a.asama, a.asama)} · {a.baslik}" + (f" — {a.ayrinti}" if a.ayrinti else "")
                for a in self.adimlar]


@dataclass
class EksikBilgi:
    bilgi: str
    soru: str
    neden: str = ""


@dataclass
class DurumCozumlemesi:
    konu: str = ""
    niyet: str = "bilgi"                 # bilgi | islem | yazi | hesap | kontrol
    personel_turu: str = "belirsiz"
    olgular: list[str] = field(default_factory=list)
    olay_tarihi: str = ""
    alt_sorular: list[str] = field(default_factory=list)
    terimler: list[str] = field(default_factory=list)
    eksik: list[EksikBilgi] = field(default_factory=list)
    zorluk: str = "orta"                 # kolay | orta | zor
    model_ile: bool = False

    def sozluk(self) -> dict:
        return asdict(self)


COZUMLEME_SEMASI = {
    "type": "object",
    "properties": {
        "konu": {"type": "string"},
        "niyet": {"type": "string", "enum": ["bilgi", "islem", "yazi", "hesap", "kontrol"]},
        "personel_turu": {"type": "string", "enum": list(PERSONEL_TURLERI)},
        "olgular": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "olay_tarihi": {"type": "string"},
        "alt_sorular": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "terimler": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "eksik": {"type": "array", "maxItems": 2, "items": {"type": "object", "properties": {
            "bilgi": {"type": "string"}, "soru": {"type": "string"}, "neden": {"type": "string"}},
            "required": ["bilgi", "soru"]}},
        "zorluk": {"type": "string", "enum": ["kolay", "orta", "zor"]},
    },
    "required": ["konu", "niyet", "personel_turu", "olgular", "alt_sorular", "terimler", "eksik", "zorluk"],
}

COZUMLEME_GOREVI = (
    "Kullanıcının isteğini bir danışman gibi çözümle; cevap verme. Olguları (kim, ne, ne zaman, hangi statü) "
    "ayrı ayrı yaz. Soruyu cevaplamak için araştırılması gereken alt soruları ve arama terimlerini (mevzuat dilinde, "
    "eş anlamlılarıyla) çıkar. Cevabı gerçekten değiştiren ve kullanıcının söylemediği bilgi varsa 'eksik' alanına "
    "en fazla iki kısa soru yaz; cevabı değiştirmeyen ayrıntıyı sorma. Önceki konuşma verildiyse kısaltmaları ve "
    "'peki o zaman', 'bu durumda' gibi göndermeleri ona göre çöz. Yalnızca istenen JSON'u döndür.")


@dataclass
class SohbetBaglami:
    """Aynı konuşmadaki önceki turlar (en çok 4): devam sorularını doğru anlamak için."""
    turlar: list[dict] = field(default_factory=list)

    def ekle(self, soru: str, ozet: str, cozumleme: DurumCozumlemesi | dict | None) -> None:
        coz = cozumleme.sozluk() if isinstance(cozumleme, DurumCozumlemesi) else (cozumleme or {})
        self.turlar.append({"soru": soru, "ozet": ozet[:600], "olgular": list(coz.get("olgular") or []),
                            "personel_turu": coz.get("personel_turu") or "belirsiz"})
        self.turlar = self.turlar[-4:]

    def metin(self) -> str:
        if not self.turlar:
            return ""
        return "ÖNCEKİ KONUŞMA:\n" + "\n".join(
            f"- Soru: {t['soru']}\n  Verilen cevabın özeti: {t['ozet']}" for t in self.turlar)

    def bilinen_personel_turu(self) -> str:
        for t in reversed(self.turlar):
            if t.get("personel_turu") and t["personel_turu"] != "belirsiz":
                return t["personel_turu"]
        return "belirsiz"


# ============================================================================ ANLA
def kurallarla_coz(istek: str, baglam: SohbetBaglami | None = None) -> DurumCozumlemesi:
    """Dil modeli yokken: desenlerle personel türü, tarih, niyet."""
    k = istek.lower()
    tur = next((t for desen, t in _TUR_DESENLERI if re.search(desen, k)), "belirsiz")
    if tur == "belirsiz" and baglam:
        tur = baglam.bilinen_personel_turu()
    niyet = "yazi" if _YAZI_NIYETI.search(istek) else "hesap" if _HESAP_NIYETI.search(istek) else "bilgi"
    m = _TARIH.search(istek)
    tarih = f"{int(m.group(1)):02d}.{int(m.group(2)):02d}.{m.group(3)}" if m else ""
    return DurumCozumlemesi(konu=istek[:120], niyet=niyet, personel_turu=tur, olay_tarihi=tarih,
                            alt_sorular=[istek], terimler=[], eksik=_kurala_gore_eksik(istek, tur))


# Cevabı değiştiren eksik bilgi: kişiye özel hak sorularında personel türü
_KISIYE_OZEL = re.compile(r"\b(izin|izn|aylık|aylik|maaş|maas|ücret|ucret|terfi|kademe|derece|emekl|görevlendir|"
                          r"gorevlendir|nöbet|nobet|fazla çalışma|fazla calisma|ek ders|hakk|alabilir mi|alır mı|"
                          r"alir mi|yararlan)", re.I)


def _kurala_gore_eksik(istek: str, tur: str) -> list[EksikBilgi]:
    if tur == "belirsiz" and _KISIYE_OZEL.search(istek):
        return [EksikBilgi("personel türü",
                           "Söz konusu personel hangi statüde: 657/4-A kadrolu memur, 4/B sözleşmeli, 2547 akademik "
                           "personel mi, yoksa işçi mi?", "Hak ve süreler statüye göre farklı mevzuata tabidir")]
    return []


def durumu_coz(istek: str, model=None, baglam: SohbetBaglami | None = None,
               dersler: list[str] | None = None) -> DurumCozumlemesi:
    """ANLA aşaması. Model varsa yapılandırılmış çözümleme, yoksa kurallar."""
    temel = kurallarla_coz(istek, baglam)
    if model is None or not getattr(model, "hazir", False):
        return temel
    from ..answer.llm import json_cikar
    kullanici = (baglam.metin() + "\n\n" if baglam and baglam.turlar else "") + f"İSTEK: {istek}"
    if dersler:
        kullanici += "\n\nGEÇMİŞ DERSLER (yalnızca yöntem için):\n" + "\n".join(f"- {d}" for d in dersler)
    try:
        cikti = model.sohbet([{"role": "system", "content": sistem_cekirdegi(COZUMLEME_GOREVI)},
                              {"role": "user", "content": kullanici}],
                             max_tokens=500, sicaklik=0.1, json_mod=True, json_sema=COZUMLEME_SEMASI)
    except TypeError:                                   # json_sema desteklemeyen eski model sınıfları
        cikti = model.sohbet([{"role": "system", "content": sistem_cekirdegi(COZUMLEME_GOREVI)},
                              {"role": "user", "content": kullanici}], max_tokens=500, sicaklik=0.1, json_mod=True)
    except Exception:  # noqa: BLE001 - model hatasında kurallarla devam
        return temel
    v = json_cikar(cikti) or {}
    if not v:
        return temel
    tur = v.get("personel_turu") if v.get("personel_turu") in PERSONEL_TURLERI else temel.personel_turu
    if tur == "belirsiz" and temel.personel_turu != "belirsiz":
        tur = temel.personel_turu
    eksik = [EksikBilgi(str(e.get("bilgi", ""))[:80], str(e.get("soru", ""))[:240], str(e.get("neden", ""))[:200])
             for e in (v.get("eksik") or []) if isinstance(e, dict) and e.get("soru")][:2]
    if tur != "belirsiz":
        eksik = [e for e in eksik if "statü" not in katla(e.bilgi + e.soru) and "personel tur" not in katla(e.bilgi)]
    return DurumCozumlemesi(
        konu=str(v.get("konu") or temel.konu)[:160],
        niyet=v.get("niyet") if v.get("niyet") in ("bilgi", "islem", "yazi", "hesap", "kontrol") else temel.niyet,
        personel_turu=tur, olgular=[str(x)[:200] for x in v.get("olgular") or []][:8],
        olay_tarihi=str(v.get("olay_tarihi") or temel.olay_tarihi)[:20],
        alt_sorular=[str(x)[:240] for x in v.get("alt_sorular") or []][:5] or [istek],
        terimler=[str(x)[:60] for x in v.get("terimler") or []][:10], eksik=eksik,
        zorluk=v.get("zorluk") if v.get("zorluk") in ("kolay", "orta", "zor") else "orta", model_ile=True)
