"""İlke karnesi ve gelişim kapısı.

Karne: bir soru setindeki cevaplardan her temel ilke için 0–1 arası not (yüksek iyi) + genel başarı.
Kapı: bir değişiklik (yeni ders, yöntem, sıralayıcı, model) ancak
  - hiçbir ilkenin notu tolerans payından fazla düşmüyorsa,
  - kritik hata (yanlışken 'Doğrulandı' demek) artmıyorsa,
  - genel başarı ya da ilke ortalaması gerçekten artıyorsa
benimsenir. Ölçülemeyen ilke (o sette örneği yok) kararı etkilemez.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ilkeler import ILKE_KODLARI

_TC = re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)")
_IBAN = re.compile(r"\bTR\d{2}(?:\s?\d{4}){5}\s?\d{2}\b", re.IGNORECASE)


@dataclass
class Karne:
    notlar: dict[str, float] = field(default_factory=dict)      # ilke kodu → 0..1
    ornek: dict[str, int] = field(default_factory=dict)         # ilke kodu → ölçülen cevap sayısı
    basari: float = 0.0                                          # beklenen cevabı veren soru oranı
    kritik: int = 0
    toplam: int = 0
    dogrulanan: int = 0                                          # 'Doğrulandı' denen (güvenle verilen) cevap sayısı

    def kesinlik(self) -> float | None:
        """Güvenle verilen cevapların isabeti: 'Doğrulandı' denenlerden beklenen cevabı verenlerin oranı."""
        return (self.dogrulanan - self.kritik) / self.dogrulanan if self.dogrulanan else None

    def ortalama(self) -> float:
        degerler = [v for k, v in self.notlar.items() if self.ornek.get(k)]
        return sum(degerler) / len(degerler) if degerler else 0.0

    def sozluk(self) -> dict:
        return {"notlar": {k: round(v, 3) for k, v in self.notlar.items()}, "ornek": self.ornek,
                "basari": round(self.basari, 3), "kritik": self.kritik, "toplam": self.toplam,
                "dogrulanan": self.dogrulanan,
                "ortalama": round(self.ortalama(), 3)}


def _say(cevap, test: str, seviye: str | None = None) -> int:
    return sum(1 for u in cevap.uyarilar if u.test == test and (seviye is None or u.seviye == seviye))


def cevap_puanlari(cevap, beklenti: dict | None = None) -> dict[str, float]:
    """Tek bir cevabın ilke puanları (ölçülemeyen ilke anahtarı yer almaz)."""
    from ..answer.modeller import Durum
    p: dict[str, float] = {}
    beklenti = beklenti or {}
    denetim = getattr(cevap, "denetim", {}) or {}
    uretilen = max(1, int(denetim.get("uretilen", 0)) or len(cevap.tum_cumleler()) or 1)
    cikarilan = int(denetim.get("dogruluk_cikarilan", _say(cevap, "Alıntı", "hata") + _say(cevap, "Çapraz kontrol", "hata")
                                + _say(cevap, "Kaynak")))
    p["dogruluk"] = max(0.0, 1.0 - cikarilan / uretilen)
    p["guncellik"] = 0.0 if _say(cevap, "Güncellik", "hata") else 1.0
    p["hiyerarsi"] = 0.0 if _say(cevap, "Hiyerarşi", "hata") else 1.0
    p["somutluk"] = max(0.0, 1.0 - _say(cevap, "Somutluk") / uretilen)
    metin = cevap.duz_metin()
    p["gizlilik"] = 0.0 if (_TC.search(metin) or _IBAN.search(metin)) else 1.0
    if beklenti.get("netlestirme"):
        p["durum"] = 1.0 if getattr(cevap, "netlestirme", None) else 0.0
    if cevap.durum != Durum.HUKUM_YOK:
        p["muhakeme"] = 1.0 if getattr(cevap, "uygulama", None) else 0.0
    else:
        p["cozum"] = 1.0 if (cevap.somut_yol and (cevap.dikkat or cevap.kaynaklar)) else 0.0
    guven = getattr(cevap, "guven", "")
    if guven:
        tutarli = (guven == "hukum_yok") == (cevap.durum == Durum.HUKUM_YOK)
        if guven == "kesin" and cevap.durum != Durum.DOGRULANDI:
            tutarli = False
        p["guven"] = 1.0 if tutarli else 0.0
    return p


def karne_hesapla(sonuclar: list[tuple[object, dict | None, bool, bool]]) -> Karne:
    """sonuclar: (cevap, beklenti, geçti_mi, kritik_mi) listesi."""
    toplamlar: dict[str, float] = {k: 0.0 for k in ILKE_KODLARI}
    sayilar: dict[str, int] = {k: 0 for k in ILKE_KODLARI}
    gecen = kritik = dogrulanan = 0
    for cevap, beklenti, gecti, krt in sonuclar:
        for k, v in cevap_puanlari(cevap, beklenti).items():
            toplamlar[k] += v
            sayilar[k] += 1
        gecen += int(gecti)
        kritik += int(krt)
        dogrulanan += int(getattr(getattr(cevap, "durum", None), "value", "") == "Doğrulandı")
    n = len(sonuclar)
    return Karne(notlar={k: (toplamlar[k] / sayilar[k] if sayilar[k] else 1.0) for k in ILKE_KODLARI},
                 ornek=sayilar, basari=(gecen / n if n else 0.0), kritik=kritik, toplam=n, dogrulanan=dogrulanan)


def kapi(eski: Karne, yeni: Karne, tolerans: float = 0.02, en_az_artis: float = 0.005) -> tuple[bool, str]:
    """Gelişim kapısı: (benimse_mi, gerekçe)."""
    if yeni.toplam == 0:
        return False, "Sınama seti boş; değişiklik benimsenmedi"
    dusen = [k for k in ILKE_KODLARI
             if yeni.ornek.get(k) and eski.ornek.get(k) and yeni.notlar[k] < eski.notlar[k] - tolerans]
    if dusen:
        return False, "İlke notu düştü: " + ", ".join(dusen)
    if yeni.kritik > eski.kritik:
        # Kritik sayısı, daha çok soruya güvenle cevap veren modelde kendiliğinden artabilir. Bu yalnız güvenle
        # verilen cevapların isabeti düşmediyse, başarı belirgin arttıysa ve set yeterince büyükse kabul edilir.
        ek, yk = eski.kesinlik(), yeni.kesinlik()
        if not (ek is not None and yk is not None and yk >= ek and yeni.toplam >= 20
                and yeni.basari - eski.basari >= 0.10):
            return False, f"Kritik hata arttı ({eski.kritik} → {yeni.kritik})"
    if yeni.basari < eski.basari - 1e-9:
        return False, f"Başarı düştü ({eski.basari:.0%} → {yeni.basari:.0%})"
    artis = (yeni.basari - eski.basari) + (yeni.ortalama() - eski.ortalama())
    if artis >= en_az_artis or yeni.kritik < eski.kritik:
        return True, (f"Başarı {eski.basari:.0%} → {yeni.basari:.0%}, ilke ortalaması "
                      f"{eski.ortalama():.2f} → {yeni.ortalama():.2f}, kritik {eski.kritik} → {yeni.kritik}")
    return False, "Anlamlı bir iyileşme yok; mevcut durum korunuyor"
