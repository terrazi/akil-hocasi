"""Terim genişletme ve birim yönlendirme sözlüğü.

Personel aynı şeyi farklı adlarla sorar ("ücretsiz izin" / "aylıksız izin").
Bu sözlük aramayı genişletir; cevap yine madde metninden gelir.
Sözlük birim uzmanlarıyla zenginleştirilmelidir.
"""

from __future__ import annotations

from ..core.turkce import katla

ES_ANLAMLILAR: dict[str, list[str]] = {
    "ücretsiz izin": ["aylıksız izin"],
    "aylıksız izin": ["ücretsiz izin"],
    "yolluk": ["harcırah"],
    "harcırah": ["yolluk", "gündelik"],
    "maaş": ["aylık", "ödeme"],
    "görevlendirme": ["2547 39", "geçici görev"],
    "39. madde": ["2547 39", "görevlendirme"],
    "kıst": ["kıst aylık", "kısmi aylık"],
    "ek ders": ["ek ders ücreti", "2914 11"],
    "fazla mesai": ["fazla çalışma"],
    "fazla çalışma": ["fazla mesai"],
    "istifa": ["çekilme", "görevden çekilme"],
    "tayin": ["naklen atama", "nakil"],
    "nakil": ["naklen atama", "tayin"],
    "doğum izni": ["analık izni"],
    "babalık izni": ["mazeret izni"],
    "askerlik": ["askerlik hizmeti", "tecil"],
    "satın alma": ["doğrudan temin", "4734 22"],
    "doğrudan temin": ["4734 22", "satın alma"],
    "taşınır": ["taşınır mal", "demirbaş"],
    "demirbaş": ["taşınır"],
    "jüri ücreti": ["jüri üyeliği ücreti"],
    "aile yardımı": ["aile yardımı ödeneği"],
    "ödeme emri": ["ödeme emri belgesi", "harcama belgesi"],
    "resmi yazı": ["resmî yazışma"],
    "ebys": ["elektronik belge yönetim", "resmî yazışma"],
}

BIRIM_YONLENDIRME: list[tuple[list[str], str]] = [
    (["izin", "atama", "nakil", "tayin", "istifa", "görevlendirme", "kadro", "terfi", "askerlik",
      "sözleşme", "özlük", "emekli", "hitap"], "Personel Daire Başkanlığı"),
    (["maaş", "aylık", "ödeme", "harcırah", "yolluk", "ek ders", "fazla çalışma", "tahakkuk",
      "bütçe", "ödenek", "muhasebe", "ön mali kontrol", "jüri", "kbs", "mys"], "Strateji Geliştirme Daire Başkanlığı"),
    (["satın alma", "ihale", "doğrudan temin", "yaklaşık maliyet", "muayene", "taşınır", "demirbaş"],
     "İdari ve Mali İşler Daire Başkanlığı"),
    (["ebys", "envision", "yazışma", "imza yetkisi", "evrak"], "Genel Sekreterlik"),
    (["dava", "hukuki", "icra", "haciz", "nafaka", "disiplin", "soruşturma"], "Hukuk Müşavirliği"),
    (["öğrenci", "kayıt", "diploma", "mezuniyet"], "Öğrenci İşleri Daire Başkanlığı"),
]


def genislet(soru: str) -> list[str]:
    """Sorudaki ifadeler için ek arama terimleri döndürür."""
    k = katla(soru)
    ek: list[str] = []
    for ifade, karsiliklar in ES_ANLAMLILAR.items():
        if katla(ifade) in k:
            ek.extend(karsiliklar)
    return ek


def birim_oner(soru: str) -> str:
    """Sorunun konusuna göre danışılacak TOGÜ birimini önerir."""
    k = katla(soru)
    en_iyi, puan = "Genel Sekreterlik", 0
    for anahtarlar, birim in BIRIM_YONLENDIRME:
        p = sum(1 for a in anahtarlar if katla(a) in k)
        if p > puan:
            en_iyi, puan = birim, p
    return en_iyi
