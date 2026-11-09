"""Cevap veri modeli: her cümle kaynak kimliklerine bağlıdır."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..library.db import Pasaj


class Durum(str, Enum):
    DOGRULANDI = "Doğrulandı"
    CELISKILI = "Çelişkili"
    HUKUM_YOK = "Doğrudan hüküm yok"


@dataclass
class Kaynak:
    kid: str            # "K1"
    pasaj: Pasaj

    @property
    def etiket(self) -> str:
        return self.pasaj.etiket


@dataclass
class Cumle:
    metin: str
    kaynaklar: list[str] = field(default_factory=list)   # ["K1", "K3"]
    tur: str = "bilgi"     # bilgi, alinti, adim, yonlendirme
    notlar: list[str] = field(default_factory=list)


@dataclass
class Uyari:
    test: str
    mesaj: str
    seviye: str = "uyari"  # bilgi, uyari, hata


@dataclass
class BelgeRef:
    kod: str
    ad: str
    url: str = ""
    dosya_yolu: str = ""


@dataclass
class Cevap:
    soru: str
    durum: Durum = Durum.HUKUM_YOK
    kisa_cevap: list[Cumle] = field(default_factory=list)
    adimlar: list[Cumle] = field(default_factory=list)
    dikkat: list[Cumle] = field(default_factory=list)
    kaynaklar: list[Kaynak] = field(default_factory=list)
    belgeler: list[BelgeRef] = field(default_factory=list)
    acik_nokta: str = ""
    somut_yol: list[Cumle] = field(default_factory=list)
    uyarilar: list[Uyari] = field(default_factory=list)
    ilerleme: list[str] = field(default_factory=list)
    mod: str = "derin"
    model_kullanildi: bool = False
    takip_id: int | None = None
    olay_id: int | None = None
    cevrimdisi: bool = False
    sure_sn: float = 0.0

    def kaynak(self, kid: str) -> Kaynak | None:
        return next((k for k in self.kaynaklar if k.kid == kid), None)

    def tum_cumleler(self) -> list[Cumle]:
        return [*self.kisa_cevap, *self.adimlar, *self.dikkat, *self.somut_yol]

    @property
    def son_kontrol(self) -> str:
        tarihler = [k.pasaj.son_kontrol for k in self.kaynaklar if k.pasaj.son_kontrol]
        return min(tarihler) if tarihler else ""

    def duz_metin(self) -> str:
        """Panoya kopyalama için düz metin."""
        satirlar = [f"Soru: {self.soru}", f"Durum: {self.durum.value}", ""]

        def ek(cumleler: list[Cumle], baslik: str, numarali: bool = False) -> None:
            if not cumleler:
                return
            satirlar.append(baslik)
            for i, c in enumerate(cumleler, 1):
                ref = f" [{', '.join(c.kaynaklar)}]" if c.kaynaklar else ""
                satirlar.append(f"{i}. {c.metin}{ref}" if numarali else f"- {c.metin}{ref}")
            satirlar.append("")

        ek(self.kisa_cevap, "Kısa cevap:")
        if self.acik_nokta:
            satirlar += ["Açık kalan nokta:", self.acik_nokta, ""]
        ek(self.adimlar, "Adımlar:", numarali=True)
        ek(self.dikkat, "Dikkat:")
        ek(self.somut_yol, "Önerilen yol:")
        if self.kaynaklar:
            satirlar.append("Dayanak:")
            for k in self.kaynaklar:
                satirlar.append(f"[{k.kid}] {k.etiket} — {k.pasaj.kaynak_url}")
        return "\n".join(satirlar).strip()
