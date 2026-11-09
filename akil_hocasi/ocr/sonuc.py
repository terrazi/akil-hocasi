"""OCR sonuç modeli: kelime kutuları, satırlar, metin ve tablo olarak dışa aktarım."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.turkce import nfc


@dataclass
class OcrKelime:
    metin: str
    x: int
    y: int
    w: int
    h: int
    guven: float = 1.0               # 0-1
    satir: int = 0
    alternatifler: list[str] = field(default_factory=list)
    oneri: str = ""                  # Türkçe düzeltme önerisi (otomatik uygulanmaz)

    @property
    def supheli(self) -> bool:
        return self.guven < 0.6 or bool(self.alternatifler)

    @property
    def merkez_y(self) -> float:
        return self.y + self.h / 2

    def kesisim_orani(self, o: "OcrKelime") -> float:
        x1, y1 = max(self.x, o.x), max(self.y, o.y)
        x2, y2 = min(self.x + self.w, o.x + o.w), min(self.y + self.h, o.y + o.h)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        kes = (x2 - x1) * (y2 - y1)
        return kes / float(self.w * self.h + o.w * o.h - kes)


@dataclass
class OcrSonuc:
    kelimeler: list[OcrKelime]
    motor: str
    genislik: int
    yukseklik: int
    sure_sn: float = 0.0
    notlar: list[str] = field(default_factory=list)

    def satirlara_ayir(self) -> list[list[OcrKelime]]:
        """Kelimeleri dikey konuma göre satırlara toplar ve satır numarası atar."""
        kalan = sorted(self.kelimeler, key=lambda k: (k.merkez_y, k.x))
        satirlar: list[list[OcrKelime]] = []
        for k in kalan:
            if satirlar:
                son = satirlar[-1]
                ort_h = sum(s.h for s in son) / len(son)
                ort_y = sum(s.merkez_y for s in son) / len(son)
                if abs(k.merkez_y - ort_y) <= max(4.0, ort_h * 0.55):
                    son.append(k)
                    continue
            satirlar.append([k])
        for i, s in enumerate(satirlar):
            s.sort(key=lambda k: k.x)
            for k in s:
                k.satir = i
        return satirlar

    def metin(self) -> str:
        return nfc("\n".join(" ".join(k.metin for k in s) for s in self.satirlara_ayir()))

    def tablo_metni(self) -> str:
        """Sekmeyle ayrılmış tablo: kelimeler arası büyük boşluk yeni hücre sayılır (Excel'e yapışır)."""
        satirlar_txt = []
        for s in self.satirlara_ayir():
            if not s:
                continue
            ort_h = sum(k.h for k in s) / len(s)
            hucreler, hucre = [], [s[0].metin]
            for onceki, k in zip(s, s[1:], strict=False):
                bosluk = k.x - (onceki.x + onceki.w)
                if bosluk > ort_h * 1.6:
                    hucreler.append(" ".join(hucre))
                    hucre = [k.metin]
                else:
                    hucre.append(k.metin)
            hucreler.append(" ".join(hucre))
            satirlar_txt.append("\t".join(hucreler))
        return nfc("\n".join(satirlar_txt))

    def ortalama_guven(self) -> float:
        return sum(k.guven for k in self.kelimeler) / len(self.kelimeler) if self.kelimeler else 0.0
