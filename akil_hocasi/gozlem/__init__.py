"""Tarayıcı gözlemi ve gömülü tarama: eklentinin ve programın kendi görünmez tarayıcısının gördüğü herkese açık
resmî sayfaları değerlendirip kütüphanede sağlam kaynak havuzuna dönüştürür.

Hiçbir yol tıklamaz, form göndermez, oturum açık sayfaları ve kamu sistemlerini (KBS, MYS, HYS, EBYS, HİTAP,
e-Devlet) okumaz. Alt modüller ayrı ayrı içe aktarılır; köprü exe'si yalnız eslestirme modülünü kullanır.
"""


def __getattr__(ad: str):
    if ad == "GozlemDegerlendirici":
        from .degerlendirici import GozlemDegerlendirici
        return GozlemDegerlendirici
    raise AttributeError(ad)
