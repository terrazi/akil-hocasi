"""Gerçek sınav soruları: resmî görüş yazıları.

Mülga Devlet Personel Başkanlığı, Cumhurbaşkanlığı İdari İşler Başkanlığı ve bakanlık hukuk müşavirlikleri
kurumların sorduğu gerçek sorulara görüş yazısıyla cevap verir; üniversiteler bunları sitelerinde yayımlar.
Bir görüş yazısında üç şey birlikte bulunur: gerçek soru (kurumun tereddüdü), dayanak maddeler ve resmî sonuç.
Böylece programın sınavı, öğretmenin maddelerden ürettiği sorular yerine gerçek sorularla ve doğrulanmış
dayanakla yapılabilir.

Kurallar:
- Yazının yalnız soru, dayanak ve sonuç kısmı çıkarılır; kişisel veriler maskelenir (TC, IBAN, ad-soyad
  içeren satırlar alınmaz).
- Dayanak maddeler kütüphanedeki yürürlükteki maddeye eşlenir; eşlenemeyen dayanak sınava girmez.
- Yazının alıntıladığı madde metni bugünkü metinde yoksa (madde sonradan değişmiş olabilir) görüş eskimiş
  sayılır ve elenir.
- Bu sorular ve onlardan türetilen varyasyonlar eğitime hiç girmez (yalnız sınav).
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from urllib.parse import urljoin, urlparse

log = logging.getLogger("akilhocasi")

# Bilinen görüş yazıları (resmî kurum sitelerinde yayımlanmış) ve görüş bağlantısı aranacak sayfalar.
TOHUM_BELGELER = [
    "https://personeldb.ege.edu.tr/files/personeldb/icerik/_thumbs/dpb_gorusler/22dd.pdf",
    "https://personel.karabuk.edu.tr/yuklenen/dosyalar/1266032025170403.pdf",
    "https://cdn.bartin.edu.tr/personel/ae8f57c8ad4254b5019c6fb31b079871/16_YzQp7Pk.pdf",
    "https://hukukmusavirligi.diyanet.gov.tr/Documents/22.11.2019-E.768604.pdf",
    "https://hukukmusavirligi.diyanet.gov.tr/Documents/mehil-muddeti-27.pdf",
]
TOHUM_SAYFALAR = [
    "https://personeldb.ege.edu.tr/",
    "https://personel.karabuk.edu.tr/",
    "https://hukukmusavirligi.diyanet.gov.tr/",
    "https://personel.gop.edu.tr/",
]
GORUS_BAGLANTI = re.compile(r"g[öo]r[üu][şs]|dpb|m[üu]talaa|ictihat|i[çc]tihat", re.I)

_SIRA = r"(?:['’]?\s*(?:inci|nci|ncı|üncü|uncu|ıncı|ncü|ü|u|ı|i))?"
_KANUN = re.compile(r"(\d{2,4})\s*sayılı\s+(?:[^.;()\n]{0,140}?)(Kanun\s+Hükmünde\s+Kararname|Kanun|KHK)", re.I)
_MADDE = re.compile(r"((?:\d{1,3}(?:/[A-ZÇĞİÖŞÜ])?\s*(?:,|ve|ile|-)\s*)*\d{1,3})(?:/[A-ZÇĞİÖŞÜ])?\s*" + _SIRA
                    + r"\s*(?:ve\s+)?(?:ek\s+)?madde", re.I)
_GONDERME = re.compile(r"(anılan|aynı|söz\s*konusu|sözü\s*edilen|bahse\s*konu|mezkûr|mezkur)\s+(Kanun|KHK|Kararname)", re.I)
_SONUC_BASI = re.compile(r"(Bu\s+itibarla|Bu\s+çerçevede|Buna\s+göre|Bu\s+durumda|Sonuç\s+olarak|"
                         r"Yukarıda\s+yer\s+verilen|Yukarıda\s+belirtilen|Anılan\s+hükümler\s+çerçevesinde)", re.I)
_SONUC_SONU = re.compile(r"(mütalaa\s+edilmektedir|değerlendirilmektedir|uygun\s+görülmektedir|"
                         r"mümkün\s+(?:bulunmamaktadır|görülmemektedir|bulunmaktadır|görülmektedir)|gerekmektedir|"
                         r"düşünülmektedir|bulunmamaktadır)", re.I)
_TALEP = re.compile(r"([^.]{20,700}?)(?:hususunda|konusunda|ile\s+ilgili\s+olarak|hakkında)\s+"
                    r"(?:Başkanlığımız|Bakanlığımız|Müşavirliğimiz|Genel\s+Müdürlüğümüz)\w*\s+görüş\w*\s+"
                    r"(?:talep\s+edil|sorul|isten)", re.I)
_KONU = re.compile(r"Konu\s*:\s*([^\n]{5,200})", re.I)
_TARIH = re.compile(r"\b(\d{2})[./](\d{2})[./](\d{4})\b")
_KISISEL = re.compile(r"\b\d{11}\b|\bTR\d{2}[\d ]{20,}|\bIBAN\b", re.I)


def _temiz(metin: str) -> str:
    metin = re.sub(r"-\n(?=\w)", "", metin)                       # satır sonu heceleme
    metin = re.sub(r"[ \t]+", " ", metin)
    return re.sub(r"\s*\n\s*", "\n", metin).strip()


def dayanaklari_bul(metin: str) -> list[tuple[str, str]]:
    """Metindeki kanun/KHK madde atıfları: [(kanun_no, madde_no)]. 'Anılan Kanunun 108 inci maddesi' gibi
    göndermeler en son anılan kanuna bağlanır; kanunu belli olmayan madde (yönetmelik vb.) alınmaz."""
    sonuc: list[tuple[str, str]] = []
    son_kanun = None
    for cumle in re.split(r"(?<=[.;:])\s+", metin.replace("\n", " ")):
        kanunlar = [(m.start(), m.group(1)) for m in _KANUN.finditer(cumle)]
        gonderme = [m.start() for m in _GONDERME.finditer(cumle)]
        for m in _MADDE.finditer(cumle):
            onceki = [k for k in kanunlar if k[0] < m.start()]
            if onceki:
                kanun = onceki[-1][1]
            elif kanunlar:
                continue                                          # madde kanundan önce: başka belgeye ait
            elif son_kanun and (any(g < m.start() for g in gonderme) or re.search(r"Kanun\w*\s*$",
                                                                                cumle[:m.start()].strip())):
                kanun = son_kanun
            else:
                continue
            for no in re.findall(r"\d{1,3}", m.group(1)):
                if (kanun, no) not in sonuc and 0 < int(no) < 400:
                    sonuc.append((kanun, no))
        if kanunlar:
            son_kanun = kanunlar[-1][1]
    return sonuc


def gorus_ayristir(metin: str, kaynak: str = "") -> dict | None:
    """Görüş yazısından soru, dayanak ve sonuç. Eksikse None."""
    metin = _temiz(metin)
    if len(metin) < 300 or "görüş" not in metin.lower():
        return None
    satirlar = [s for s in metin.split("\n") if not _KISISEL.search(s)]
    metin = "\n".join(satirlar)
    duz = metin.replace("\n", " ")
    talep = None
    m = _TALEP.search(duz)
    if m:
        talep = re.sub(r"^.*?\b(?:İlgi\s*(?:\([a-zçğıöşü]\))?\s*(?:yazı\w*|\w*)\s*(?:ile|ve)?\s*,?)\s*", "",
                       m.group(1).strip(), flags=re.I).strip(" ,;")
    konu = (_KONU.search(metin).group(1).strip() if _KONU.search(metin) else "")
    sonuc = None
    for b in reversed(list(_SONUC_BASI.finditer(duz))):
        son = _SONUC_SONU.search(duz, b.start())
        if son and son.end() - b.start() < 1800:
            sonuc = duz[b.start():son.end()].strip()
            break
    dayanaklar = dayanaklari_bul(metin)
    if not (talep or konu) or not sonuc or not dayanaklar:
        return None
    tarih = ""
    t = _TARIH.search(metin[:1500])
    if t:
        tarih = f"{t.group(3)}-{t.group(2)}-{t.group(1)}"
    alintilar = [a.strip() for a in re.findall(r"[\"“]([^\"”]{40,600})[\"”]", duz)]
    return {"id": hashlib.sha1((sonuc + (talep or konu)).encode("utf-8")).hexdigest()[:16], "kaynak": kaynak,
            "tarih": tarih, "konu": konu, "talep": talep or konu, "sonuc": sonuc, "dayanaklar": dayanaklar,
            "alintilar": alintilar[:6]}


def kutuphane_anahtari(kutuphane, kanun_no: str, madde_no: str) -> str | None:
    """(657, 105) → kütüphanede yürürlükteki maddenin anahtarı ('MEV:1.5.657/105'); yoksa None."""
    for tur in (1, 4):                                            # kanun, KHK
        for tertip in (5, 4, 3):
            kimlik = f"MEV:{tur}.{tertip}.{kanun_no}"
            if kutuphane.madde_getir(kimlik, madde_no) is not None:
                return f"{kimlik}/{madde_no}"
    return None


def _katla(s: str) -> str:
    s = s.lower().translate(str.maketrans("çğıöşüâîû", "cgiosuaiu"))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def alintilar_guncel_mi(kutuphane, anahtarlar: list[str], alintilar: list[str]) -> bool:
    """Yazının alıntıladığı madde metinlerinden en az biri bugünkü dayanak maddelerde geçiyorsa (ya da alıntı
    yoksa) güncel sayılır; alıntı var ama hiçbiri geçmiyorsa madde değişmiş olabilir → eskimiş."""
    if not alintilar:
        return True
    metinler = []
    for a in anahtarlar:
        kimlik, no = a.rsplit("/", 1)
        p = kutuphane.madde_getir(kimlik, no)
        if p is not None:
            metinler.append(_katla(p.metin))
    birlesik = " ".join(metinler)
    for a in alintilar:
        parca = _katla(a)
        kelimeler = parca.split()
        if len(kelimeler) < 6:
            continue
        orta = " ".join(kelimeler[: min(14, len(kelimeler))])
        if orta in birlesik:
            return True
    return False


def gorusten_sinav_ogesi(kutuphane, gorus: dict) -> dict | None:
    """Görüşü kütüphaneye bağlar: dayanakları eşler, eskimişse eler. Sınav öğesi (soru öğretmence doğal dile
    çevrilmeden önceki hâli) ya da None."""
    anahtarlar = [a for k, m in gorus["dayanaklar"] if (a := kutuphane_anahtari(kutuphane, k, m))]
    if not anahtarlar:
        return None
    if not alintilar_guncel_mi(kutuphane, anahtarlar, gorus.get("alintilar", [])):
        log.info("Görüş eskimiş olabilir (alıntı bugünkü metinde yok): %s", gorus.get("kaynak"))
        return None
    return {**gorus, "beklenen_dayanak": anahtarlar}


def pdf_metni(veri: bytes) -> str:
    import fitz  # PyMuPDF
    with fitz.open(stream=veri, filetype="pdf") as belge:
        return "\n".join(s.get_text() for s in belge)


class GorusToplayici:
    """Tohum belgeleri indirir; tohum sayfalarda görüş bağlantısı arar (aynı alan adında, iki adım)."""

    def __init__(self, oturum=None, bekleme: float = 1.0, zaman_asimi: float = 30):
        import requests
        self.oturum = oturum or requests.Session()
        self.oturum.headers.setdefault("User-Agent", "AkilHocasi/1.0 (yerel mevzuat asistani; gorus derleme)")
        self.bekleme, self.zaman_asimi = bekleme, zaman_asimi

    def _al(self, url: str):
        time.sleep(self.bekleme)
        try:
            y = self.oturum.get(url, timeout=self.zaman_asimi)
            return y if y.status_code == 200 else None
        except Exception as e:  # noqa: BLE001
            log.info("Alınamadı %s: %s", url, e)
            return None

    def baglantilari_bul(self, sayfa: str, derinlik: int = 2, sinir: int = 300) -> list[str]:
        alan = urlparse(sayfa).netloc
        gorulen, kuyruk, pdfler = set(), [(sayfa, 0)], []
        while kuyruk and len(gorulen) < sinir:
            url, d = kuyruk.pop(0)
            if url in gorulen:
                continue
            gorulen.add(url)
            y = self._al(url)
            if y is None or "html" not in y.headers.get("Content-Type", ""):
                continue
            for href, yazi in re.findall(r'<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', y.text, re.S | re.I):
                tam = urljoin(url, href)
                if urlparse(tam).netloc != alan:
                    continue
                isaret = GORUS_BAGLANTI.search(tam) or GORUS_BAGLANTI.search(re.sub(r"<[^>]+>", " ", yazi))
                if tam.lower().endswith(".pdf") and isaret:
                    pdfler.append(tam)
                elif d + 1 <= derinlik and isaret and not tam.lower().endswith((".pdf", ".doc", ".docx", ".jpg")):
                    kuyruk.append((tam, d + 1))
        return list(dict.fromkeys(pdfler))

    def topla(self, sinir: int = 400, sure_sn: float = 1800, sayfalar: list[str] | None = None,
              belgeler: list[str] | None = None) -> list[dict]:
        bitis = time.monotonic() + sure_sn
        adaylar = list(belgeler if belgeler is not None else TOHUM_BELGELER)
        for s in (sayfalar if sayfalar is not None else TOHUM_SAYFALAR):
            if time.monotonic() > bitis:
                break
            adaylar += self.baglantilari_bul(s)
        gorusler, kimlikler = [], set()
        for url in dict.fromkeys(adaylar):
            if time.monotonic() > bitis or len(gorusler) >= sinir:
                break
            y = self._al(url)
            if y is None or not y.content.startswith(b"%PDF"):
                continue
            try:
                g = gorus_ayristir(pdf_metni(y.content), url)
            except Exception as e:  # noqa: BLE001
                log.info("PDF okunamadı %s: %s", url, e)
                continue
            if g and g["id"] not in kimlikler:
                kimlikler.add(g["id"])
                gorusler.append(g)
        log.info("Görüş yazısı: %d aday, %d ayrıştırıldı", len(adaylar), len(gorusler))
        return gorusler


# ------------------------------------------------------------------ öğretmenle soruya çevirme ve zorlaştırma
DEGISIKLIKLER = ("eksik_bilgi", "statu", "istisna", "iki_mevzuat", "sure_hesabi", "yaniltici_ayrinti", "gundelik_dil")
VARYASYON_SEMASI = {
    "type": "object",
    "properties": {
        "soru": {"type": "string"},
        "varyasyonlar": {"type": "array", "maxItems": 4, "items": {
            "type": "object",
            "properties": {"soru": {"type": "string"}, "degisiklik": {"type": "string", "enum": list(DEGISIKLIKLER)},
                           "ayni_dayanak": {"type": "boolean"}, "beklenen_sonuc": {"type": "string"}},
            "required": ["soru", "degisiklik", "ayni_dayanak", "beklenen_sonuc"]}},
    },
    "required": ["soru", "varyasyonlar"],
}
VARYASYON_GOREVI = (
    "GÖREV: Aşağıda bir kamu kurumunun sorduğu ve resmî görüşle cevaplanmış gerçek bir mevzuat sorusu var. "
    "(1) 'soru': Bunu bir üniversite idari personelinin danışmana soracağı gibi, kendi sözlerinle, doğal bir soru "
    "olarak yaz. Madde numarası, kanun adı ya da cevabın kendisi soruda geçmesin; görüş yazısındaki cümleleri "
    "kopyalama; kişi ve kurum adı kullanma. (2) 'varyasyonlar': aynı konuda daha zor 3-4 soru yaz; her biri tek bir "
    "zorlaştırma taşısın: eksik_bilgi (cevabı değiştiren bilgi, ör. personel türü, verilmesin), statu (4/A yerine "
    "4/B ya da sözleşmeli/aday memur), istisna (kuralın istisnasına giren bir durum), iki_mevzuat (iki düzenlemenin "
    "birlikte uygulanması), sure_hesabi (gün/ay hesabı gerektirsin), yaniltici_ayrinti (cevabı etkilemeyen ama "
    "yanıltabilecek ayrıntı), gundelik_dil (yazım hatalı, kısaltmalı gündelik dil). 'ayni_dayanak': cevabın dayanağı "
    "verilen maddelerle aynı kalıyorsa true. 'beklenen_sonuc': verilen maddelere ve resmî sonuca göre doğru cevap, "
    "bir-iki cümle; maddeler yetmiyorsa bunu söyle. Yalnızca istenen JSON'u döndür.")


def sinav_sorulari_kur(kutuphane, ogretmen, ogeler: list[dict], bitis: float | None = None) -> list[dict]:
    """Görüş öğelerini öğretmenle doğal soruya ve zorlaştırılmış varyasyonlara çevirir. Dayanağı değişen
    varyasyon (otomatik doğrulanamaz) alınmaz. Çıktı: sınav satırları (yalnız sınav; eğitime girmez)."""
    import json
    sorular = []
    for o in ogeler:
        if bitis and time.monotonic() > bitis:
            break
        maddeler = []
        for a in o["beklenen_dayanak"][:4]:
            kimlik, no = a.rsplit("/", 1)
            p = kutuphane.madde_getir(kimlik, no)
            if p is not None:
                maddeler.append(f"[{a}] {p.metin[:1500]}")
        girdi = (f"KONU: {o.get('konu', '')}\nKURUMUN SORUSU: {o['talep']}\nRESMÎ SONUÇ: {o['sonuc']}\n"
                 f"DAYANAK MADDELER:\n" + "\n".join(maddeler) + f"\n\n{VARYASYON_GOREVI}")
        try:
            ham = ogretmen.sohbet([{"role": "system", "content": "Türk kamu personel mevzuatı uzmanısın."},
                                   {"role": "user", "content": girdi}], max_tokens=1400, sicaklik=0.4,
                                  json_sema=VARYASYON_SEMASI)
            v = json.loads(re.search(r"\{.*\}", ham, re.S).group(0))
        except Exception as e:  # noqa: BLE001
            log.info("Görüş soruya çevrilemedi (%s): %s", o.get("id"), e)
            continue
        ortak = {"beklenen_dayanak": o["beklenen_dayanak"], "kaynak": o.get("kaynak", ""), "gorus_id": o["id"],
                 "resmi_sonuc": o["sonuc"]}
        if len(str(v.get("soru", ""))) >= 20:
            sorular.append({"id": f"g-{o['id']}", "soru": v["soru"].strip(), "tur": "gercek", **ortak})
        for i, x in enumerate(v.get("varyasyonlar", [])[:4]):
            if x.get("ayni_dayanak") and len(str(x.get("soru", ""))) >= 20 and x.get("degisiklik") in DEGISIKLIKLER:
                sorular.append({"id": f"g-{o['id']}-{i}", "soru": x["soru"].strip(), "tur": f"varyasyon:{x['degisiklik']}",
                                "beklenen_sonuc": str(x.get("beklenen_sonuc", ""))[:600], **ortak})
    return sorular
