"""OCR hattı: iyileştirme → bir veya iki motor → oylama → Türkçe öneri → orijinal koordinatlar.

Yeniden okuma düzeyleri: sayfa (seviye artırarak), bölge (kırp + büyüt), kelime (alternatifler),
çoklu okuma oylaması (iki motor + farklı ön işlemler).
"""

from __future__ import annotations

import time

import numpy as np

from .duzeltme import TurkceDuzeltici
from .iyilestirme import iyilestir
from .motorlar import OcrMotoru
from .sonuc import OcrKelime, OcrSonuc


def _geri_esle(sonuc: OcrSonuc, kat: float, kenar: int = 10, ox: int = 0, oy: int = 0) -> None:
    for k in sonuc.kelimeler:
        k.x = int((k.x - kenar) / kat) + ox
        k.y = int((k.y - kenar) / kat) + oy
        k.w = max(1, int(k.w / kat))
        k.h = max(1, int(k.h / kat))


def oyla(birincil: OcrSonuc, ikincil: OcrSonuc) -> OcrSonuc:
    """İki motorun sonucunu kutu örtüşmesiyle eşleştirir; anlaşmazlıkları alternatif olarak işaretler."""
    for k in birincil.kelimeler:
        eslesen = max(ikincil.kelimeler, key=lambda o: k.kesisim_orani(o), default=None)
        if eslesen is None or k.kesisim_orani(eslesen) < 0.3:
            continue
        if eslesen.metin != k.metin:
            # Güveni yüksek olan öne geçer, diğeri alternatif olur
            if eslesen.guven > k.guven + 0.15:
                k.alternatifler.append(k.metin)
                k.metin, k.guven = eslesen.metin, eslesen.guven
            else:
                k.alternatifler.append(eslesen.metin)
        else:
            k.guven = min(1.0, max(k.guven, eslesen.guven) + 0.1)
    birincil.motor = f"{birincil.motor} + {ikincil.motor}"
    return birincil


class OcrHatti:
    def __init__(self, motorlar: list[OcrMotoru], duzeltici: TurkceDuzeltici | None = None,
                 oylama: bool = True):
        self.motorlar = motorlar
        self.duzeltici = duzeltici or TurkceDuzeltici()
        self.oylama = oylama

    @property
    def hazir(self) -> bool:
        return bool(self.motorlar)

    def oku(self, img: np.ndarray, seviye: int = 1, bolge: tuple[int, int, int, int] | None = None) -> OcrSonuc:
        """img: BGR/BGRA/gri numpy. bolge: (x, y, w, h) — yalnızca bu alan okunur (bölge yeniden okuma)."""
        if not self.motorlar:
            return OcrSonuc([], "OCR motoru yok", img.shape[1], img.shape[0],
                            notlar=["Kurulu OCR motoru bulunamadı; README'deki kurulum adımlarına bakınız"])
        bas = time.time()
        ox = oy = 0
        kaynak = img
        if bolge:
            x, y, w, h = bolge
            kaynak = img[y:y + h, x:x + w]
            ox, oy = x, y
        islenmis, kat = iyilestir(kaynak, seviye)
        sonuc = self.motorlar[0].oku(islenmis)
        if self.oylama and len(self.motorlar) > 1:
            sonuc = oyla(sonuc, self.motorlar[1].oku(islenmis))
        _geri_esle(sonuc, kat, 10, ox, oy)
        sonuc.genislik, sonuc.yukseklik = img.shape[1], img.shape[0]
        for k in sonuc.kelimeler:
            k.oneri = self.duzeltici.oner(k.metin)
        sonuc.satirlara_ayir()
        sonuc.sure_sn = time.time() - bas
        return sonuc

    def coklu_oku(self, img: np.ndarray, bolge: tuple[int, int, int, int] | None = None,
                  seviyeler: tuple[int, ...] = (1, 2, 3)) -> OcrSonuc:
        """Aynı alanı farklı ön işlemlerle okur; en güvenli sonucu seçer, diğer okumaları
        kelime düzeyinde alternatif olarak ekler (çoklu okuma oylaması)."""
        adaylar = [self.oku(img, seviye=s, bolge=bolge) for s in seviyeler]
        en_iyi = max(adaylar, key=lambda s: s.ortalama_guven())
        for diger in adaylar:
            if diger is en_iyi:
                continue
            for k in en_iyi.kelimeler:
                eslesen = max(diger.kelimeler, key=lambda o: k.kesisim_orani(o), default=None)
                if (eslesen is not None and k.kesisim_orani(eslesen) >= 0.3 and eslesen.metin != k.metin
                        and eslesen.metin not in k.alternatifler):
                    k.alternatifler.append(eslesen.metin)
        en_iyi.sure_sn = sum(a.sure_sn for a in adaylar)
        return en_iyi

    def bolgeyi_yeniden_oku(self, img: np.ndarray, onceki: OcrSonuc, bolge: tuple[int, int, int, int]) -> OcrSonuc:
        """Seçilen alanı çoklu okumayla tekrar okur ve önceki sonuca yerleştirir."""
        yeni = self.coklu_oku(img, bolge=bolge)
        x, y, w, h = bolge

        def icinde(k: OcrKelime) -> bool:
            cx, cy = k.x + k.w / 2, k.y + k.h / 2
            return x <= cx <= x + w and y <= cy <= y + h

        kalan = [k for k in onceki.kelimeler if not icinde(k)]
        birlesik = OcrSonuc(kalan + yeni.kelimeler, yeni.motor, onceki.genislik, onceki.yukseklik,
                            onceki.sure_sn + yeni.sure_sn)
        birlesik.satirlara_ayir()
        return birlesik
