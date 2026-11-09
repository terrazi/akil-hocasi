"""Sürekli öğrenme: program kullanıldıkça daha iyi arar, anlar ve sunar — bilgi uydurmadan.

Öğrenilenler:   terim karşılıkları, işe yarayan kaynaklar, OCR düzeltmeleri, doğrulanmış örnek cevaplar
Kendini sınama: gece soru-cevap bankasını yeniden doğrular, altın soru setinde başarıyı ölçer
Paylaşım:       öğrenme paketleri ortak klasör üzerinden bilgisayarlar arasında taşınır;
                gelen her bilgi alıcı bilgisayarda yeniden doğrulanır
Model gelişimi: doğrulanmış etkileşimlerden ince ayar verisi; yeni model ancak daha başarılıysa devreye girer
"""

from .motor import OgrenmeMotoru

__all__ = ["OgrenmeMotoru"]
