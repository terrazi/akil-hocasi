"""Tarayıcı gözlemcisi: Akıl Hocası Gözlemci eklentisinin gördüğü herkese açık resmî sayfaları
değerlendirip kütüphanede sağlam kaynak havuzuna dönüştürür.

Eklenti yalnızca okur: tıklamaz, form göndermez, oturum açık sayfaları ve kamu sistemlerini
(KBS, MYS, HYS, EBYS, HİTAP, e-Devlet) gözlemez. Uygulama aynı kuralları ayrıca kendisi uygular.
"""

from .degerlendirici import GozlemDegerlendirici

__all__ = ["GozlemDegerlendirici"]
