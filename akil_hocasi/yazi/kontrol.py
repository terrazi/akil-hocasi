"""Kontrol listesi, sınama ve otomatik düzeltme.

Her madde Yönetmelikteki bir maddeye ya da çekirdek ilkeye bağlıdır. Durumlar: tamam | uyari | hata | bilgi.
SINAMA (doğruluk ilkesi): metindeki her tarih, sayı, belge sayısı ve mevzuat atfı; gelen yazıda, kullanıcının
talimatında, ilgilerde ya da doğrulanmış dayanak metinlerinde geçmelidir. Geçmeyen cümle "hata" olarak işaretlenir
ve kullanıcı onaylamadan taslak "hazır" sayılmaz.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from ..core.turkce import katla, tr_lower
from .dil import kisi_adi, konu_bicimi, muhatap_bicimi, sayilari_grupla, tarih_bicimi, yonelme_eki_var_mi
from .kurallar import bitis_ifadesi, bitis_uyumlu_mu, ilgi_satirlari
from .model import YAZI_TURLERI, Paragraf, Yazi

_TC = re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)")
_IBAN = re.compile(r"\bTR\d{2}(?:\s?\d{4}){5}\s?\d{2}\b", re.I)
_TARIH = re.compile(r"(?<![\d.])\d{1,2}[./]\d{1,2}[./]\d{4}(?![\d])")
_BELGE_SAYI = re.compile(r"\b[EZO]-\d{3,}(?:-[\w.]+)*-\d+\b")
_KANUN = re.compile(r"(\d{2,5})\s+sayılı", re.I)
_MADDE = re.compile(r"(\d+)\s*(?:['’]?\s*(?:inci|ıncı|uncu|üncü|nci|ncı|ncu|ncü)|\.)\s+madde", re.I)
_SAYI = re.compile(r"(?<![\w.,-])\d+(?:[.,]\d+)*(?![\w-])")
# Tek haneli sayı bir miktar bildiriyorsa (3 personel, 5 gün) o da kaynakta olmalı
_MIKTAR = re.compile(r"\s*(?:\(\w+\)\s*)?(?:personel|kişi|adet|gün|iş günü|ay|yıl|saat|hafta|TL|lira|sayfa|kadro|"
                     r"öğrenci|akademisyen|memur|işçi|kat|puan|dosya|nüsha)\b", re.I)
_KISALTMA = re.compile(r"\b[A-ZÇĞİÖŞÜ]{2,}(?:-[A-ZÇĞİÖŞÜ]+)?\b")
_YAYGIN_KISALTMA = {"T.C.", "TC", "TL", "ABD", "AB", "EK", "KEP", "OLUR", "ACELE", "GÜNLÜDÜR"}
_FORMUL = re.compile(r"[^.]{0,60}(?:arz|rica)[^.]*ederim\.?|Saygılarımla\.?|İyi dileklerimle\.?|"
                     r"Bilgilerinize sunulur\.?", re.I)
_EK_ATIF = re.compile(r"\bek(?:te|li|teki|tedir|lerde|lerdeki|te\s+gönderil)|\bekte\b|\beki\b|ek[-‐]?\d", re.I)


@dataclass
class KontrolSonucu:
    madde: str          # "md. 13" ya da "İlke: Doğruluk"
    baslik: str
    durum: str          # tamam | uyari | hata | bilgi
    mesaj: str

    def sozluk(self) -> dict:
        return asdict(self)


def _sayilar(metin: str) -> set[str]:
    k = set()
    for m in _TARIH.finditer(metin):
        k.add(tarih_bicimi(m.group(0)))
    for m in _BELGE_SAYI.finditer(metin):
        k.add(m.group(0))
    for m in _SAYI.finditer(metin):
        k.add(m.group(0).replace(".", "") if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", m.group(0)) else m.group(0))
    return k


def sinama(y: Yazi, kaynak_metinler: list[str]) -> list[tuple[int, str]]:
    """(paragraf_no, neden) — kaynakta karşılığı olmayan tarih, sayı, belge sayısı ve mevzuat atıfları."""
    havuz = "\n".join(kaynak_metinler + ilgi_satirlari(y) + [i.tarih + " " + i.sayi for i in y.ilgiler]
                      + [y.cevap_suresi, " ".join(y.ekler)])
    izinli = _sayilar(havuz)
    havuz_k = katla(havuz)
    sorunlar = []
    for n, p in enumerate(y.paragraflar):
        if p.tur == "bitis" or not p.metin.strip():
            continue
        metin = p.metin
        bildirilen = set()
        for desen in (_KANUN, _MADDE):
            for m in desen.finditer(metin):
                if m.group(1) not in izinli:
                    sorunlar.append((n, f"“{m.group(0)}” atfı dayanaklarda yok"))
                bildirilen.add(m.group(1))
        for m in list(_TARIH.finditer(metin)) + list(_BELGE_SAYI.finditer(metin)) + list(_SAYI.finditer(metin)):
            s = m.group(0)
            sade = s.replace(".", "") if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", s) else s
            tek_hane = len(sade.strip(".,")) <= 1 and not _TARIH.fullmatch(s)
            if sade in bildirilen or (tek_hane and not _MIKTAR.match(metin[m.end():])):
                continue                             # atıf olarak bildirildi ya da tek haneli sıra/numara
            bildirilen.add(sade)
            if _TARIH.fullmatch(s):
                sade = tarih_bicimi(s)
            if sade in izinli or s in izinli or katla(s) in havuz_k:
                continue
            if any(sade in x for x in bildirilen if x != sade and len(x) > len(sade)):
                continue                             # daha uzun bir tarihin/sayının parçası
            sorunlar.append((n, f"“{s}” gelen yazıda, talimatta ya da dayanaklarda geçmiyor"))
    return sorunlar


_DOLGU = {"ilgi", "yazı", "yazi", "gerekmektedir", "istenmektedir", "talep", "edilmektedir", "bildirilmesi",
          "gönderilmesi", "başkanlığımıza", "başkanlığınızca", "müdürlüğümüze", "tarihine", "kadar", "olarak",
          "ilişkin", "konusunda", "kapsamında", "hususunda", "üzere", "bilgilerinizi", "gereğini", "ederim"}


def karsilaniyor_mu(istenen: str, metin: str) -> bool:
    """İstenen hususun anahtar sözcüklerinin (ilk 5 harf) en az %40'ı metinde geçiyor mu?"""
    sozcukler = {katla(s)[:5] for s in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]{5,}", istenen) if tr_lower(s) not in _DOLGU}
    if not sozcukler:
        return True
    metin_k = katla(metin)
    return sum(1 for s in sozcukler if s in metin_k) / len(sozcukler) >= 0.4


def kontrol_et(y: Yazi, kaynak_metinler: list[str] | None = None) -> list[KontrolSonucu]:
    s: list[KontrolSonucu] = []
    ekle = lambda madde, baslik, durum, mesaj: s.append(KontrolSonucu(madde, baslik, durum, mesaj))  # noqa: E731

    # Başlık (md. 10)
    dolu = [b for b in y.baslik if b.strip()]
    if len(dolu) >= 3:
        ekle("md. 10", "Başlık", "tamam", "T.C., idare adı (büyük harf) ve birim adı ortalı yazılır")
    else:
        ekle("md. 10", "Başlık", "hata", "Başlıkta T.C., idare adı ve birim adı olmalı (Ayarlar > Birim profili)")

    # Sayı ve tarih (md. 11–12)
    if y.dosya_kodu and not re.fullmatch(r"\d{3}(?:\.\d{1,3}){0,4}", y.dosya_kodu.strip()):
        ekle("md. 11", "Sayı", "uyari", f"Standart dosya planı kodu biçimi beklenmiyor: {y.dosya_kodu}")
    ekle("md. 11–12", "Sayı ve tarih", "bilgi", "Kayıt numarası ve tarih EBYS'de imza sırasında verilir; taslakta "
         "yer tutucu olarak durur")

    # Konu (md. 13)
    if not y.konu.strip():
        ekle("md. 13", "Konu", "hata", "Konu yazılmamış")
    else:
        bicimli = konu_bicimi(y.konu)
        if len(bicimli) > 80:
            ekle("md. 13", "Konu", "uyari", "Konu uzun; kısa ve öz olmalı ve dikey orta hizayı geçmemeli")
        else:
            ekle("md. 13", "Konu", "tamam", f"“{bicimli}” — sözcük başları büyük, sonda noktalama yok")

    # Muhatap (md. 14)
    m = y.muhatap.strip()
    if not m and not y.dagitimli:
        ekle("md. 14", "Muhatap", "hata", "Muhatap yazılmamış")
    elif y.kisiye or m.lower().startswith("sayın"):
        ekle("md. 14", "Muhatap", "tamam", f"Gerçek kişi: “Sayın {kisi_adi(m[5:] if m.lower().startswith('sayın') else m)}”")
    elif y.dagitimli and not m:
        ekle("md. 14", "Muhatap", "tamam", "“DAĞITIM YERLERİNE”")
    elif not yonelme_eki_var_mi(muhatap_bicimi(m)):
        ekle("md. 14", "Muhatap", "uyari", f"“{muhatap_bicimi(m)}” yönelme hâl ekiyle bitmiyor gibi; kontrol edin")
    else:
        ekle("md. 14", "Muhatap", "tamam", f"“{muhatap_bicimi(m)}” büyük harf ve yönelme hâli")

    # İlgi (md. 15)
    for i in y.ilgiler:
        if i.metin:
            continue
        if not i.kisi and (not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", i.tarih or "") or not i.sayi):
            ekle("md. 15", "İlgi", "uyari", "İlgide tarih (GG.AA.YYYY) ve sayı birlikte yazılmalı: "
                 f"{i.tarih or '—'} / {i.sayi or '—'}")
    if y.ilgiler and not any(x.durum != "tamam" for x in s if x.baslik == "İlgi"):
        ekle("md. 15", "İlgi", "tamam", f"{len(y.ilgiler)} ilgi, eskiden yeniye sıralı, “… tarihli ve … sayılı …” biçiminde")
    metin = "\n".join(p.metin for p in y.paragraflar)
    atiflar = set(re.findall(r"[İi]lgi\s*\(([a-zçğıöşü])\)", metin))
    if atiflar and len(y.ilgiler) < 2:
        ekle("md. 15", "İlgi", "hata", "Metinde ilgi (a), (b) diye atıf var ama ilgi listesinde yeterli satır yok")

    # Metin (md. 16)
    if not y.paragraflar:
        ekle("md. 16", "Metin", "hata", "Metin yok")
    else:
        yer_tutucu = [p.metin for p in y.paragraflar if "[" in p.metin and "]" in p.metin]
        if yer_tutucu:
            ekle("md. 16", "Metin", "uyari", f"{len(yer_tutucu)} paragrafta köşeli parantezli yer tutucu var; "
                 "birimin bilgisiyle doldurun")
        ok, neden = bitis_uyumlu_mu(y.paragraflar[-1].metin, y.makam)
        ekle("md. 16", "Bitiş ifadesi", "tamam" if ok else "hata",
             f"“{y.paragraflar[-1].metin.strip()[-60:]}”" if ok else neden)
        ilk_gecis = {}
        for k in _KISALTMA.finditer(metin):
            ilk_gecis.setdefault(k.group(0), k.start())
        aciklanmamis = [k for k, i in ilk_gecis.items() if k not in _YAYGIN_KISALTMA
                        and not re.search(r"\(\s*" + re.escape(k) + r"\s*\)", metin[: i + len(k) + 3])]
        if aciklanmamis:
            ekle("md. 16", "Kısaltmalar", "uyari", "İlk geçtiği yerde açık yazılıp parantezde verilmeli: "
                 + ", ".join(aciklanmamis[:6]))
        if any(p.metin != sayilari_grupla(p.metin) for p in y.paragraflar):
            ekle("md. 16", "Sayı yazımı", "uyari", "Dört ve daha fazla haneli tutarlar üçlü gruplanmalı (12.500 TL)")
        else:
            ekle("md. 16", "Paragraf düzeni", "tamam", "1,25 cm girinti, iki yana yaslı, paragraflar arasında boş satır yok")

    # Sınama (çekirdek: doğruluk ilkesi)
    sorunlar = sinama(y, kaynak_metinler or [])
    if sorunlar:
        for n, neden in sorunlar[:8]:
            ekle("İlke: Doğruluk", f"Sınama — {n + 1}. paragraf", "hata", neden + "; doğrulayın ya da çıkarın")
    elif y.paragraflar:
        ekle("İlke: Doğruluk", "Sınama", "tamam", "Metindeki tarih, sayı ve atıfların hepsi gelen yazıda, talimatta "
             "ya da dayanaklarda geçiyor")

    # Kapsam (çekirdek: çözüm odaklılık): gelen yazıda istenen her husus metinde karşılanmalı
    if y.istenenler and y.paragraflar:
        karsilanmayan = [x for x in y.istenenler if not karsilaniyor_mu(x, metin)]
        if karsilanmayan:
            ekle("İlke: Çözüm", "İstenenlerin karşılanması", "uyari",
                 f"Gelen yazıda istenen {len(y.istenenler)} husustan {len(karsilanmayan)} tanesi metinde karşılanmamış "
                 "görünüyor: " + " | ".join(k[:90] for k in karsilanmayan[:3]))
        else:
            ekle("İlke: Çözüm", "İstenenlerin karşılanması", "tamam",
                 f"Gelen yazıda istenen {len(y.istenenler)} husus metinde karşılanıyor")

    # İmza (md. 17)
    i = y.imza
    if not (i.ad and i.soyad and i.unvan):
        ekle("md. 17", "İmza", "hata", "İmza sahibinin adı, soyadı ve unvanı eksik (Ayarlar > Birim profili)")
    elif i.yetki and not re.search(r"\s(a|V)\.$", i.yetki.strip()):
        ekle("md. 17", "İmza", "uyari", f"Yetki devri “… a.”, vekâlet “… V.” biçiminde yazılır: {i.yetki}")
    else:
        ekle("md. 17", "İmza", "tamam", f"{kisi_adi(i.ad, i.soyad)}, {i.unvan}" + (f" ({i.yetki})" if i.yetki else ""))

    # Ek (md. 18)
    ek_var = any(e.strip() for e in y.ekler)
    if _EK_ATIF.search(metin) and not ek_var:
        ekle("md. 18", "Ek", "hata", "Metinde eke atıf var ama ek listesi boş")
    elif ek_var and not _EK_ATIF.search(metin):
        ekle("md. 18", "Ek", "uyari", "Ek listesi var ama metinde eke değinilmiyor")
    elif ek_var:
        ekle("md. 18", "Ek", "tamam", f"{len([e for e in y.ekler if e.strip()])} ek, sayfa/adet bilgisiyle")

    # Dağıtım (md. 19)
    if y.dagitimli and not (y.gereği or y.bilgi):
        ekle("md. 19", "Dağıtım", "hata", "Dağıtımlı yazıda Gereği/Bilgi listesi olmalı")
    elif y.gereği or y.bilgi:
        ekle("md. 19", "Dağıtım", "tamam", f"Gereği: {len(y.gereği)}, Bilgi: {len(y.bilgi)}")

    # Olur (md. 20)
    if y.tur == "olur" and not y.olur:
        ekle("md. 20", "Olur", "hata", "Olur yazısında oluru verecek makam (ad, soyad, unvan) yazılmalı")

    # Süreli yazı (md. 26)
    if y.ivedilik == "GÜNLÜDÜR" and not (y.cevap_suresi and (y.cevap_suresi in metin or _TARIH.search(metin))):
        ekle("md. 26", "Süreli yazı", "hata", "GÜNLÜDÜR yazılarda cevap süresi ya da tarihi metinde belirtilmeli")
    elif y.ivedilik:
        ekle("md. 26", "Süreli yazı", "tamam", f"{y.ivedilik}: sağ üst köşede kırmızı")

    # Gizlilik (md. 25)
    if y.gizlilik and tr_lower(y.gizlilik) not in ("hizmete özel",):
        ekle("md. 25", "Gizlilik", "uyari", "“Özel” ve üstü gizlilik dereceli belgeler fiziksel ortamda işlenir")

    # Kişisel veri (çekirdek: gizlilik ilkesi)
    if _TC.search(metin) or _IBAN.search(metin):
        ekle("İlke: Gizlilik", "Kişisel veri", "uyari", "Metinde T.C. kimlik no ya da IBAN var; gerçekten gerekli "
             "değilse çıkarın (KVKK)")
    return s


def duzelt(y: Yazi) -> list[str]:
    """Biçim kurallarını kendiliğinden uygular; yapılanları döndürür (içerik değiştirilmez)."""
    yapilan = []
    k = konu_bicimi(y.konu)
    if k != y.konu:
        y.konu, _ = k, yapilan.append("Konu biçimi düzeltildi (md. 13)")
    for i in y.ilgiler:
        t = tarih_bicimi(i.tarih)
        if t != i.tarih:
            i.tarih, _ = t, yapilan.append("İlgi tarihi GG.AA.YYYY yapıldı (md. 12)")
    for p in y.paragraflar:
        yeni = sayilari_grupla(tarih_bicimi(p.metin))
        if yeni != p.metin:
            p.metin, _ = yeni, yapilan.append("Tarih ve tutar yazımı düzeltildi (md. 12, 16)")
        temiz = re.sub(r"\s+([,.;:])", r"\1", re.sub(r"[ \t]{2,}", " ", p.metin)).strip()
        if temiz != p.metin:
            p.metin = temiz
    y.paragraflar = [p for p in y.paragraflar if p.metin.strip()]
    bitisler = [p for p in y.paragraflar if p.tur == "bitis" or _FORMUL.fullmatch(p.metin.strip())]
    if bitisler and (len(bitisler) > 1 or y.paragraflar[-1] is not bitisler[-1]):
        govde = [p for p in y.paragraflar if not any(p is b for b in bitisler)]
        y.paragraflar = govde + [bitisler[-1]]           # bitiş ifadesi tek ve metnin sonunda olur
        bitisler[-1].tur = "bitis"
        yapilan.append("Bitiş ifadesi metnin sonuna alındı (md. 16)")
    if y.paragraflar:
        son = y.paragraflar[-1]
        ok, _ = bitis_uyumlu_mu(son.metin, y.makam)
        if not ok:
            amac = YAZI_TURLERI.get(y.tur, {}).get("amac", "bilgi")
            mevcut = tr_lower(son.metin)
            if "bilgilerinizi ve gereğini" in mevcut or "bilgi ve gereğini" in mevcut:
                amac = "bilgi_ve_gereği"
            elif mevcut.startswith("gereğini"):
                amac = "gereği"
            elif mevcut.startswith("bilgilerinizi"):
                amac = "bilgi"
            dogru = bitis_ifadesi(y.makam, amac)
            if son.tur == "bitis" or _FORMUL.fullmatch(son.metin.strip()):
                son.metin, son.tur = dogru, "bitis"
            else:
                y.paragraflar.append(Paragraf(dogru, tur="bitis"))
            yapilan.append(f"Bitiş ifadesi “{dogru}” yapıldı (md. 16)")
    return yapilan
