"""Gözlem değerlendiricisi: eklentiden gelen sayfayı kabul, ipucu ya da ret olarak sınıflandırır.

Sıra (her adım güvenli tarafta durur):
 1 Kamu sistemi / oturumlu uygulama engeli (KBS, EBYS, e-Devlet, giriş sayfaları...)  → ret
 2 Oturum işareti (parola alanı, çıkış bağlantısı)                                     → ret
 3 Beyaz liste: birincil → işlenir; ikincil (memurlar.net...) → yalnız başlık/soru ipucu; diğer → ret
 4 Maskeleme (TC, IBAN, cep telefonu), boyut sınırı
 5 Sınıflandırma: mevzuat (madde yapısı) / liste (form/dosya bağlantıları) / sss / sayfa
 6 Tekilleştirme (aynı içerik başka adreste zaten varsa) ve kütüphaneye kayıt (sürümlü)
 7 Resmî dosya bağlantıları (PDF, Word, Excel) doğrudan resmî siteden indirilmek üzere kuyruğa
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from ..core.maskeleme import metni_maskele
from ..core.turkce import bosluk_normalle, nfc
from ..crawler import beyaz_liste
from ..crawler.kaynaklar import DOSYA_UZANTILARI, kod_bul
from ..library.ayristirici import maddelere_bol
from ..library.db import Kutuphane

# Kamu sistemleri ve oturumlu uygulamalar: eklenti ve uygulama bunları asla gözlemez.
# (kbs.gov.tr takvimli tarayıcıda yalnız herkese açık duyuru/kılavuz için birincildir; gözlemde tamamen kapalıdır.)
SISTEM_ALANLARI = ["turkiye.gov.tr", "kbs.gov.tr", "muhasebat.gov.tr", "uyap.gov.tr", "kep.tr", "ekap.kik.gov.tr"]
SISTEM_ANAHTARLARI = ["ebys", "envision", "obs", "pbs", "hys", "mys", "kbs", "hitap", "ekap", "edevlet",
                      "giris", "login", "portal", "oturum", "webmail", "mail", "sso", "cas", "auth",
                      "uyap", "kep", "bank", "bordro", "intranet"]
SISTEM_YOLLARI = re.compile(r"/(?:login|giris|oturum|signin|sign-in|account|hesabim|auth|sso)(?:/|$|\?)", re.IGNORECASE)
ISTISNALAR = ["ebysyardim.gop.edu.tr"]          # herkese açık yardım/mevzuat sitesi

EN_AZ_METIN = 200
EN_COK_METIN = 2_000_000
_CEP = re.compile(r"(?<!\d)(?:\+?90[\s.-]?|0)?5\d{2}[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}(?!\d)")
_KART = re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)")

SEMA = """
CREATE TABLE IF NOT EXISTS gozlem_kayit (
    id INTEGER PRIMARY KEY, zaman TEXT NOT NULL, url TEXT NOT NULL, karar TEXT NOT NULL,
    neden TEXT DEFAULT '', tur TEXT DEFAULT '', kimlik TEXT DEFAULT '', mod TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS gozlem_ipucu (
    url TEXT PRIMARY KEY, baslik TEXT NOT NULL, sorular TEXT DEFAULT '[]', zaman TEXT NOT NULL
);
"""


def sistem_mi(url: str) -> bool:
    """Kamu sistemi veya oturumlu uygulama adresi mi? (istisnalar hariç)"""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if host in ISTISNALAR:
        return False
    if any(host == a or host.endswith("." + a) for a in SISTEM_ALANLARI):
        return True
    etiketler = host.split(".")
    if any(any(e == k or e.startswith(k + "-") or e.endswith("-" + k) for k in SISTEM_ANAHTARLARI) for e in etiketler[:-2]):
        return True
    return bool(SISTEM_YOLLARI.search(u.path or "/"))


def maskele(metin: str) -> str:
    """TC kimlik no, IBAN, kart numarası ve cep telefonunu maskeler (kurumsal e-posta ve sabit hat kalır)."""
    metin = metni_maskele(metin)
    metin = _KART.sub("[KART NO]", metin)
    return _CEP.sub("[CEP TELEFONU]", metin)


def siniflandir(metin: str, dosya_sayisi: int) -> str:
    maddeler = [p for p in maddelere_bol(metin) if p.madde_no != "Giriş"]
    if len(maddeler) >= 2:
        return "mevzuat"
    kodlar = len(set(re.findall(r"TOG[ÜU]\s*\.\s*[A-ZÇĞİÖŞÜ]{2,4}\s*\.\s*\d{3}", metin)))
    if kodlar >= 3 or dosya_sayisi >= 5:
        return "liste"
    if sum(1 for s in metin.splitlines() if s.strip().endswith("?") and len(s.strip()) > 15) >= 3:
        return "sss"
    return "sayfa"


def kimlik_ve_tur(url: str, tur_sinifi: str) -> tuple[str, str, str]:
    """(kimlik, belge türü, kaynak türü)"""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    q = parse_qs(u.query)
    if host.endswith("mevzuat.gov.tr") and "MevzuatNo" in q:
        no = q["MevzuatNo"][0]
        tur = q.get("MevzuatTur", ["1"])[0]
        tertip = q.get("MevzuatTertip", ["5"])[0]
        if tur == "1":
            return no, "kanun", "Mevzuat"
        return f"MEV:{tur}.{tertip}.{no}", "yonetmelik", "Mevzuat"
    if host.endswith("resmigazete.gov.tr"):
        return f"RG:{u.path}", "rg", "Mevzuat"
    sade = f"{host}{u.path}" + (f"?{u.query}" if u.query and len(u.query) < 120 else "")
    kimlik = "WEB:" + (sade if len(sade) <= 180 else sade[:120] + "#" + hashlib.sha1(sade.encode()).hexdigest()[:12])
    if host.endswith("gop.edu.tr"):
        return kimlik, ("sss" if tur_sinifi == "sss" else "togu"), "TOGÜ belgesi"
    if host.endswith("mevzuat.gov.tr"):
        return kimlik, "yonetmelik", "Mevzuat"
    return kimlik, ("sss" if tur_sinifi == "sss" else "web"), "Resmî görüş"


class GozlemDegerlendirici:
    def __init__(self, kutuphane: Kutuphane):
        self.k = kutuphane
        self._kilit = kutuphane._kilit          # kütüphaneyle aynı kilit: tek SQLite bağlantısı
        with self._kilit, self.k.db:
            self.k.db.executescript(SEMA)

    def _gunluk(self, url: str, karar: str, neden: str, tur: str = "", kimlik: str = "", mod: str = "") -> None:
        with self._kilit, self.k.db:
            self.k.db.execute(
                "INSERT INTO gozlem_kayit(zaman, url, karar, neden, tur, kimlik, mod) VALUES(?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), url[:500], karar, neden, tur, kimlik, mod))

    def degerlendir(self, kayit: dict) -> dict:
        url = str(kayit.get("url", ""))
        mod = str(kayit.get("mod", "pasif"))[:12]
        u = urlparse(url)
        if u.scheme not in ("https", "http") or not u.hostname:
            return self._ret(url, "geçersiz adres", mod)
        if sistem_mi(url):
            return self._ret(url, "kamu sistemi veya oturumlu uygulama; gözlenmez", mod)
        if kayit.get("parola_alani") or kayit.get("cikis_baglantisi"):
            return self._ret(url, "oturum açık sayfa; kişisel veri riski nedeniyle gözlenmez", mod)

        baslik = bosluk_normalle(str(kayit.get("baslik", "")))[:300] or url
        if beyaz_liste.ikincil_mi(url):
            return self._ipucu(url, baslik, str(kayit.get("metin", "")), mod)
        if not beyaz_liste.birincil_mi(url):
            beyaz_liste.oneri_ekle(url)
            return self._ret(url, "beyaz liste dışı alan (öneri listesine eklendi)", mod)

        metin = nfc(str(kayit.get("metin", "")))[:EN_COK_METIN]
        metin = maskele(metin)
        dosyalar = [d for d in kayit.get("dosyalar", []) if isinstance(d, dict)
                    and urlparse(str(d.get("url", ""))).path.lower().endswith(DOSYA_UZANTILARI)
                    and beyaz_liste.birincil_mi(str(d.get("url", ""))) and not sistem_mi(str(d.get("url", "")))]
        indirilecek = [{"url": d["url"], "metin": bosluk_normalle(str(d.get("metin", "")))[:200],
                        "kod": kod_bul(str(d.get("metin", ""))), "sayfa_url": url} for d in dosyalar[:200]]
        sinif = siniflandir(metin, len(dosyalar))
        kimlik, tur, kaynak_turu = kimlik_ve_tur(url, sinif)

        if sinif == "liste" or len(bosluk_normalle(metin)) < EN_AZ_METIN:
            neden = "dosya/form listesi; metin kaydedilmedi" if sinif == "liste" else "içerik çok kısa"
            self._gunluk(url, "liste" if indirilecek else "ret", neden, sinif, "", mod)
            return {"karar": "liste" if indirilecek else "ret", "neden": neden, "sinif": sinif,
                    "indirilecek": indirilecek}

        sha = hashlib.sha256(bosluk_normalle(metin).encode("utf-8")).hexdigest()
        baska = self.k.db.execute(
            "SELECT b.kimlik FROM surumler s JOIN belgeler b ON b.id=s.belge_id"
            " WHERE s.sha256=? AND s.gecerlilik_bitis IS NULL AND b.kimlik!=?", (sha, kimlik)).fetchone()
        if baska:
            self._gunluk(url, "tekrar", f"aynı içerik zaten var: {baska['kimlik']}", sinif, kimlik, mod)
            return {"karar": "tekrar", "neden": f"aynı içerik zaten kütüphanede ({baska['kimlik']})",
                    "sinif": sinif, "kimlik": baska["kimlik"], "indirilecek": indirilecek}

        sonuc = self.k.belge_kaydet(tur=tur, kimlik=kimlik, baslik=baslik, metin=metin, sha256=sha,
                                    kaynak_url=url, kaynak_turu=kaynak_turu,
                                    degistiren=f"tarayıcı gözlemi ({mod})")
        karar = "kabul" if sonuc in ("yeni", "guncellendi") else "ayni"
        self._gunluk(url, karar, sonuc, sinif, kimlik, mod)
        return {"karar": karar, "neden": sonuc, "sinif": sinif, "kimlik": kimlik, "indirilecek": indirilecek}

    def _ret(self, url: str, neden: str, mod: str) -> dict:
        self._gunluk(url, "ret", neden, "", "", mod)
        return {"karar": "ret", "neden": neden, "indirilecek": []}

    def _ipucu(self, url: str, baslik: str, metin: str, mod: str) -> dict:
        """İkincil site: içerik kopyalanmaz; yalnız başlık ve soru cümleleri ipucu olarak tutulur."""
        sorular = []
        for s in metin.splitlines():
            s = bosluk_normalle(s)
            if s.endswith("?") and 15 < len(s) <= 200 and maskele(s) not in sorular:
                sorular.append(maskele(s))
            if len(sorular) >= 10:
                break
        with self._kilit, self.k.db:
            self.k.db.execute(
                "INSERT INTO gozlem_ipucu(url, baslik, sorular, zaman) VALUES(?,?,?,?)"
                " ON CONFLICT(url) DO UPDATE SET baslik=excluded.baslik, sorular=excluded.sorular, zaman=excluded.zaman",
                (url, maskele(baslik), json.dumps(sorular, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))
        self._gunluk(url, "ipucu", "ikincil site: yalnız başlık ve sorular", "", "", mod)
        return {"karar": "ipucu", "neden": "ikincil site: içerik kopyalanmadı, başlık ve sorular ipucu olarak tutuldu",
                "indirilecek": []}

    def istatistik(self) -> dict:
        satirlar = self.k.db.execute(
            "SELECT karar, COUNT(*) AS n FROM gozlem_kayit WHERE date(zaman)=date('now','localtime') GROUP BY karar").fetchall()
        bugun = {r["karar"]: r["n"] for r in satirlar}
        return {"bugun": bugun, "toplam": self.k.db.execute("SELECT COUNT(*) FROM gozlem_kayit").fetchone()[0],
                "ipucu": self.k.db.execute("SELECT COUNT(*) FROM gozlem_ipucu").fetchone()[0]}
