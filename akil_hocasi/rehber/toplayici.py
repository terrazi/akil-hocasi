"""Kılavuz toplayıcı: sistemlerin resmî kullanım kılavuzlarını kendisi bulur, indirir, ayrıştırır ve günceller.

Güvenlik kuralları (testle denetlenir):
  · Yalnız beyaz listedeki resmî alanlar (ve kılavuz için tanımlı ek resmî alanlar) okunur; yalnız GET, çerez yok.
  · Giriş/oturum adresleri (login, giris, oturum, sso...) ve riskli eylem adresleri hiç istenmez.
  · Sistem alan adlarında (kbs.gov.tr, hitap.sgk.gov.tr, ebys...) yalnızca katalogdaki tohum sayfası ve oradan
    bağlantı verilen statik belge dosyaları (PDF/Word) okunur; başka sayfaya gidilmez, form gönderilmez.
  · Parola alanı içeren sayfanın metni saklanmaz.
Kendi kendine öğrenme: tohum sayfalarından başlayıp aynı sitede kılavuz/yardım bağlantılarını izler (sınırlı derinlik
ve sayfa sayısı), yeni sürümleri koşullu istekle (ETag/Last-Modified) yakalar; değişen kılavuza dayanan kartlar
kütüphane tarafından incelemeye alınır.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import unquote, urldefrag, urljoin, urlparse

from ..core.turkce import bosluk_normalle, katla
from ..crawler import beyaz_liste
from .kilavuz import KilavuzBelgesi, ayristir
from .sistemler import KILAVUZ_SOZCUKLERI, SISTEMLER, Sistem, sistem, sistem_bul

log = logging.getLogger("akilhocasi")

BELGE_UZANTILARI = (".pdf", ".docx", ".doc")
_GIRIS_YOLU = re.compile(
    r"/(?:login|logon|giris|oturum|signin|sign-in|account|hesabim|auth|sso|cas|portal/?$|wps/myportal)"
    r"(?:[/.?#]|$)|login\.(?:htm|html|aspx|jsp|do)|loginldap|/gen/login", re.IGNORECASE)
_RISKLI = re.compile(
    r"(?:logout|signout|cikis|oturumu?-?kapat|delete|remove|kaldir|onayla|approve|submit|gonder|kaydet|save|"
    r"update|guncelle|odeme|payment|basvur|apply|sepet|cart|wp-admin|admin|panel|mailto:|tel:|javascript:)",
    re.IGNORECASE)
_PAROLA = re.compile(rb"<input[^>]+type\s*=\s*[\"']?password", re.IGNORECASE)
IlerlemeFn = Callable[[str], None]


def _kat(url: str) -> str:
    return katla(unquote(url))


def _uygulama_alanlari() -> set[str]:
    alanlar = set()
    for s in SISTEMLER:
        h = (urlparse(s.adres).hostname or "").lower()
        if h:
            alanlar.add(h[4:] if h.startswith("www.") else h)
    return alanlar


UYGULAMA_ALANLARI = _uygulama_alanlari()


def sistem_alani_mi(url: str) -> bool:
    """Sistem uygulamasının kendi alan adı mı (oturumlu uygulama: ebys, mysv2, kbs, hitap...)?"""
    from ..gozlem.degerlendirici import sistem_mi

    host = (urlparse(url).hostname or "").lower()
    if any(host == a or host.endswith("." + a) for a in UYGULAMA_ALANLARI):
        return True
    return sistem_mi(url)


def adres_izinli(url: str, s: Sistem | None = None, tohum: bool = False) -> bool:
    """Bu adres kılavuz toplayıcı tarafından istenebilir mi?"""
    u = urlparse(url)
    if u.scheme not in ("https", "http") or not beyaz_liste.kilavuz_izinli_mi(url):
        return False
    tam = url.lower()
    if tohum and s is not None and url in s.tohumlar:
        return True                                   # katalogdaki tohum (herkese açık giriş/duyuru sayfası)
    if _GIRIS_YOLU.search(tam) or _RISKLI.search(u.path + "?" + u.query):
        return False
    if sistem_alani_mi(url):
        # sistem alan adında yalnız statik belge dosyası (PDF/Word) okunur; sayfa, form, uygulama okunmaz
        return u.path.lower().endswith(BELGE_UZANTILARI)
    return True


@dataclass
class KilavuzAdayi:
    url: str
    baslik: str
    sistem: str
    sayfa_url: str
    puan: float
    belge: bool                    # dosya (PDF/Word) mi, yardım sayfası mı


@dataclass
class ToplamaRaporu:
    baslangic: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    bitis: str = ""
    sistemler: dict[str, dict] = field(default_factory=dict)
    belgeler: list[dict] = field(default_factory=list)
    hatalar: list[str] = field(default_factory=list)

    def say(self, sistem_kimlik: str, anahtar: str, n: int = 1) -> None:
        d = self.sistemler.setdefault(sistem_kimlik, {})
        d[anahtar] = d.get(anahtar, 0) + n

    @property
    def yeni(self) -> int:
        return sum(1 for b in self.belgeler if b.get("sonuc") == "yeni")

    @property
    def guncellenen(self) -> int:
        return sum(1 for b in self.belgeler if b.get("sonuc") == "guncellendi")

    def ozet(self) -> str:
        return (f"{len(self.belgeler)} kılavuz işlendi: {self.yeni} yeni, {self.guncellenen} güncellendi"
                + (f"; {len(self.hatalar)} hata" if self.hatalar else ""))


def _baglantilar(html: bytes, sayfa_url: str) -> list[tuple[str, str]]:
    from bs4 import BeautifulSoup

    corba = BeautifulSoup(html, "lxml")
    sonuc, goruldu = [], set()
    for a in corba.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urldefrag(urljoin(sayfa_url, href))[0]
        if url in goruldu:
            continue
        goruldu.add(url)
        metin = bosluk_normalle(a.get_text(" ")) or bosluk_normalle(a.get("title", ""))
        sonuc.append((url, metin))
    return sonuc


def _kilavuz_puani(metin: str, url: str, s: Sistem) -> tuple[float, bool]:
    """Bağlantının kılavuz olma puanı ve sisteme ait olup olmadığı."""
    k = " " + katla(metin) + " " + _kat(urlparse(url).path).replace("/", " ").replace("_", " ").replace("-", " ") + " "
    puan = 0.0
    kilavuz = any(w in k for w in KILAVUZ_SOZCUKLERI) or " sunu" in k
    if kilavuz:
        puan += 3.0
    eslesen = 0
    for a in s.anahtar_katli():
        if len(a) <= 5:
            if re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", k):
                eslesen += 1
        elif a in k:
            eslesen += 1
    puan += 2.0 * min(eslesen, 3)
    return puan, eslesen > 0


class KilavuzToplayici:
    def __init__(self, kutuphane=None, depo=None, indirici=None, sayfa_siniri: int = 40, belge_siniri: int = 25,
                 derinlik: int = 2):
        if indirici is None:
            from http.cookiejar import DefaultCookiePolicy

            from ..crawler.indirici import Indirici
            indirici = Indirici()
            try:
                indirici.oturum.cookies.set_policy(DefaultCookiePolicy(allowed_domains=[]))   # çerez tutulmaz
            except Exception:  # noqa: BLE001 - sahte oturumlarda
                pass
        self.kutuphane = kutuphane
        self.depo = depo
        self.indirici = indirici
        self.sayfa_siniri = sayfa_siniri
        self.belge_siniri = belge_siniri
        self.derinlik = derinlik
        self.durdur = threading.Event()

    # ------------------------------------------------------------------ istek
    def _getir(self, url: str, rapor: ToplamaRaporu, kosullu: bool = True):
        """kosullu=True: kılavuz belgesi (ETag/Last-Modified ile; durum kaydedilir). False: keşif sayfası."""
        onceki = self.kutuphane.kaynak_durumu(url) if (kosullu and self.kutuphane is not None) else None
        s = self.indirici.getir(url, etag=(onceki["etag"] if onceki else ""),
                                last_modified=(onceki["last_modified"] if onceki else ""),
                                ek_izin=beyaz_liste.kilavuz_izinli_mi)
        if kosullu and self.kutuphane is not None and (s.basarili or s.degismedi):
            self.kutuphane.kaynak_durumu_yaz(url, s.etag, s.last_modified, s.sha256 if s.basarili else
                                            (onceki["sha256"] if onceki else ""))
        if s.hata and not s.degismedi:
            rapor.hatalar.append(f"{url}: {s.hata}")
        if s.basarili and s.son_url and s.son_url != url and _GIRIS_YOLU.search(s.son_url.lower()):
            rapor.hatalar.append(f"{url}: giriş sayfasına yönlendirdi (okunmadı)")
            s.icerik = b""
            s.durum = 0
        return s

    # ------------------------------------------------------------------ keşif
    def kesfet(self, s: Sistem, rapor: ToplamaRaporu) -> list[KilavuzAdayi]:
        """Tohum sayfalarından başlayarak sistemin kılavuz bağlantılarını bulur."""
        adaylar: dict[str, KilavuzAdayi] = {}
        kuyruk = [(t, 0) for t in s.tohumlar]
        gorulen: set[str] = set()
        sayfa = 0
        while kuyruk and sayfa < self.sayfa_siniri and not self.durdur.is_set():
            url, derinlik = kuyruk.pop(0)
            if url in gorulen:
                continue
            gorulen.add(url)
            tohum = url in s.tohumlar
            if not adres_izinli(url, s, tohum=tohum):
                rapor.say(s.kimlik, "reddedilen_adres")
                continue
            yanit = self._getir(url, rapor, kosullu=False)
            if not yanit.basarili:
                continue
            sayfa += 1
            rapor.say(s.kimlik, "sayfa")
            if not (yanit.icerik_turu or "").lower().startswith(("text/html", "application/xhtml")) \
                    and b"<html" not in yanit.icerik[:2000].lower():
                continue
            giris_sayfasi = bool(_PAROLA.search(yanit.icerik))
            sistem_sayfasi = sistem_alani_mi(url)
            for hedef, metin in _baglantilar(yanit.icerik, yanit.son_url or url):
                if hedef in gorulen:
                    continue
                yol = urlparse(hedef).path.lower()
                belge = yol.endswith(BELGE_UZANTILARI)
                puan, ait = _kilavuz_puani(metin, hedef, s)
                if belge:
                    if puan >= 3 and (ait or tohum) and adres_izinli(hedef, s):
                        mevcut = adaylar.get(hedef)
                        if mevcut is None or mevcut.puan < puan:
                            adaylar[hedef] = KilavuzAdayi(hedef, metin, s.kimlik, url, puan + (1 if tohum else 0),
                                                          True)
                    continue
                if sistem_sayfasi or giris_sayfasi:
                    continue                               # sistem/giriş sayfasından başka sayfaya gidilmez
                ayni_site = urlparse(hedef).hostname == urlparse(url).hostname
                if not ayni_site or derinlik >= self.derinlik:
                    continue
                if puan >= 3 or (puan >= 2 and tohum):
                    kuyruk.append((hedef, derinlik + 1))
                    if puan >= 5 and adres_izinli(hedef, s):   # kılavuz/SSS başlıklı yardım sayfası
                        adaylar.setdefault(hedef, KilavuzAdayi(hedef, metin, s.kimlik, url, puan - 1, False))
        sirali = sorted(adaylar.values(), key=lambda a: (-a.puan, not a.belge))
        rapor.say(s.kimlik, "aday", len(sirali))
        return sirali

    # ------------------------------------------------------------------ işleme
    def _sistemi_belirle(self, belge: KilavuzBelgesi, onerilen: Sistem) -> Sistem | None:
        on = belge.baslik + "\n" + belge.metin[:6000]
        bulunan = sistem_bul(on, en_az_puan=2.5)
        if not bulunan:
            return onerilen if onerilen.kimlik != "TOGU" else None
        if any(x[0].kimlik == onerilen.kimlik for x in bulunan[:2]):
            return onerilen
        return bulunan[0][0]

    @staticmethod
    def _kilavuz_mu(belge: KilavuzBelgesi, baglanti_metni: str) -> bool:
        o = belge.ozet()
        k = katla(belge.baslik + " " + baglanti_metni)
        return o["adim"] >= 2 or o["etiket"] >= 2 or o["yol"] >= 1 or any(w in k for w in ("kilavuz", "klavuz",
                                                                                            "sss", "sikca"))

    def isle(self, aday: KilavuzAdayi, rapor: ToplamaRaporu) -> dict | None:
        s = sistem(aday.sistem)
        yanit = self._getir(aday.url, rapor)
        if yanit.degismedi:
            rapor.say(aday.sistem, "degismeyen")
            return None
        if not yanit.basarili:
            return None
        if _PAROLA.search(yanit.icerik[:200000]):
            rapor.say(aday.sistem, "giris_sayfasi_atlandi")
            return None
        ad = unquote(urlparse(aday.url).path.rsplit("/", 1)[-1])
        try:
            belge = ayristir(yanit.icerik, ad, baslik=aday.baslik if len(aday.baslik) >= 8 else "")
        except Exception as e:  # noqa: BLE001 - bozuk belge taramayı durdurmaz
            rapor.hatalar.append(f"{aday.url}: ayrıştırılamadı ({e})")
            return None
        if belge is None:
            return None
        kayit = {"url": aday.url, "sistem": aday.sistem, "baslik": belge.baslik, **belge.ozet()}
        if belge.taranmis:
            kayit["sonuc"] = "taranmis"
            self._depola(yanit, aday, belge, s)
            rapor.belgeler.append(kayit)
            return kayit
        if not self._kilavuz_mu(belge, aday.baslik):
            rapor.say(aday.sistem, "kilavuz_degil")
            return None
        hedef = self._sistemi_belirle(belge, s) if s else None
        if hedef is None:
            rapor.say(aday.sistem, "sistemle_ilgisiz")
            return None
        kayit["sistem"] = hedef.kimlik
        dosya_yolu = self._depola(yanit, aday, belge, hedef)
        if self.kutuphane is not None:
            kayit["sonuc"] = self.kutuphane.belge_kaydet(
                tur="kilavuz", kimlik=kilavuz_kimligi(hedef.kimlik, aday.url),
                baslik=f"{hedef.kisa} — {belge.baslik}"[:220], metin=belge.metin, sha256=yanit.sha256,
                kaynak_url=aday.url, kaynak_turu="Kullanım kılavuzu", birim=hedef.kimlik, rv=belge.surum,
                yayin_tarihi=belge.tarih, dosya_yolu=dosya_yolu, maddeler=belge.maddeler())
        else:
            kayit["sonuc"] = "yeni"
        rapor.say(hedef.kimlik, kayit["sonuc"])
        rapor.belgeler.append(kayit)
        return kayit

    def _depola(self, yanit, aday: KilavuzAdayi, belge: KilavuzBelgesi, s: Sistem | None) -> str:
        if self.depo is None or not aday.belge:
            return ""
        try:
            k = self.depo.kaydet(yanit.icerik, aday.url, kod=f"KLV.{(s.kimlik if s else aday.sistem)}",
                                 ad=belge.baslik[:120], sayfa_url=aday.sayfa_url, birim=s.kimlik if s else "",
                                 rv=belge.surum, yayin_tarihi=belge.tarih)
            return k["dosya_yolu"] if k else ""
        except Exception as e:  # noqa: BLE001
            log.info("Kılavuz depoya alınamadı: %s", e)
            return ""

    # ------------------------------------------------------------------ ana giriş
    def topla(self, sistemler: list[str] | None = None, ilerleme: IlerlemeFn | None = None) -> ToplamaRaporu:
        rapor = ToplamaRaporu()
        bildir = ilerleme or (lambda m: None)
        secili = [s for s in SISTEMLER if (not sistemler or s.kimlik in sistemler) and s.tohumlar]
        islenen: set[str] = set()
        for s in secili:
            if self.durdur.is_set():
                break
            bildir(f"{s.kisa}: kılavuzlar aranıyor")
            try:
                adaylar = self.kesfet(s, rapor)
            except Exception as e:  # noqa: BLE001 - bir sistem diğerlerini durdurmaz
                rapor.hatalar.append(f"{s.kimlik} keşif: {e}")
                continue
            for aday in adaylar[: self.belge_siniri]:
                if self.durdur.is_set() or aday.url in islenen:
                    continue
                islenen.add(aday.url)
                bildir(f"{s.kisa}: {aday.baslik[:60] or aday.url.rsplit('/', 1)[-1]}")
                try:
                    self.isle(aday, rapor)
                except Exception as e:  # noqa: BLE001
                    rapor.hatalar.append(f"{aday.url}: {e}")
        rapor.bitis = datetime.now().isoformat(timespec="seconds")
        if self.kutuphane is not None:
            self.kutuphane.zamanlayici_yaz("kilavuz", rapor.bitis)
        return rapor

    def dosya_ekle(self, veri: bytes, ad: str, sistem_kimlik: str = "") -> dict:
        """Kullanıcının elindeki kılavuzu (EBYS ile gelen, eğitimde dağıtılan...) kütüphaneye ekler."""
        belge = ayristir(veri, ad)
        if belge is None:
            return {"sonuc": "desteklenmiyor", "ad": ad}
        if belge.taranmis:
            return {"sonuc": "taranmis", "ad": ad, **belge.ozet()}
        s = sistem(sistem_kimlik)
        if s is None:
            bulunan = sistem_bul(belge.baslik + " " + ad + "\n" + belge.metin[:6000], en_az_puan=2.0)
            s = bulunan[0][0] if bulunan else None
        if s is None:
            return {"sonuc": "sistem_belirlenemedi", "ad": ad, **belge.ozet()}
        sha = hashlib.sha256(veri).hexdigest()
        dosya_yolu = ""
        if self.depo is not None:
            k = self.depo.kaydet(veri, f"yerel://{ad}", kod=f"KLV.{s.kimlik}", ad=belge.baslik[:120], birim=s.kimlik,
                                 rv=belge.surum, yayin_tarihi=belge.tarih)
            dosya_yolu = k["dosya_yolu"] if k else ""
        sonuc = "yeni"
        if self.kutuphane is not None:
            sonuc = self.kutuphane.belge_kaydet(
                tur="kilavuz_yerel", kimlik=f"KLV:{s.kimlik}:yerel-{sha[:12]}",
                baslik=f"{s.kisa} — {belge.baslik}"[:220], metin=belge.metin, sha256=sha, kaynak_url="",
                kaynak_turu="Kullanım kılavuzu (sizin eklediğiniz)", birim=s.kimlik, rv=belge.surum,
                yayin_tarihi=belge.tarih, dosya_yolu=dosya_yolu, maddeler=belge.maddeler())
        return {"sonuc": sonuc, "ad": ad, "sistem": s.kimlik, **belge.ozet()}


def kilavuz_kimligi(sistem_kimlik: str, url: str) -> str:
    return f"KLV:{sistem_kimlik}:{hashlib.sha1(url.encode()).hexdigest()[:12]}"
