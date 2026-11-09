"""Nazik indirici: beyaz liste, robots.txt, hız sınırı, koşullu istek (ETag / Last-Modified).

Değişmeyen belge yeniden indirilmez. Oturum gerektiren hiçbir sayfaya girilmez.
"""

from __future__ import annotations

import hashlib
import threading
import time
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from .. import __version__
from . import beyaz_liste

KULLANICI_AJANI = f"AkilHocasi/{__version__} (yerel mevzuat asistani; saygili tarayici)"
ZAMAN_ASIMI = 30
EN_BUYUK_BOYUT = 60 * 1024 * 1024   # 60 MB


@dataclass
class IndirmeSonucu:
    url: str
    durum: int                 # HTTP durum kodu; 304 = değişmedi; 0 = ağ hatası
    icerik: bytes = b""
    icerik_turu: str = ""
    etag: str = ""
    last_modified: str = ""
    sha256: str = ""
    hata: str = ""
    son_url: str = ""

    @property
    def degismedi(self) -> bool:
        return self.durum == 304

    @property
    def basarili(self) -> bool:
        return self.durum == 200 and bool(self.icerik)


class Indirici:
    def __init__(self, istek_arasi_sn: float = 1.5, oturum=None):
        import requests  # isteğe bağlı bağımlılık; testlerde sahte oturum verilebilir

        self.oturum = oturum or requests.Session()
        self.oturum.headers.update({"User-Agent": KULLANICI_AJANI, "Accept-Language": "tr-TR,tr;q=0.9"})
        self.istek_arasi = istek_arasi_sn
        self._son_istek: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._kilit = threading.Lock()

    def _bekle(self, host: str) -> None:
        with self._kilit:
            gecen = time.time() - self._son_istek.get(host, 0)
            if gecen < self.istek_arasi:
                time.sleep(self.istek_arasi - gecen)
            self._son_istek[host] = time.time()

    def _robots_izin(self, url: str) -> bool:
        u = urlparse(url)
        kok = f"{u.scheme}://{u.netloc}"
        if kok not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.oturum.get(urljoin(kok, "/robots.txt"), timeout=10)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                    self._robots[kok] = rp
                else:
                    self._robots[kok] = None   # robots.txt yok: izinli
            except Exception:
                self._robots[kok] = None
        rp = self._robots[kok]
        return True if rp is None else rp.can_fetch(KULLANICI_AJANI, url)

    def getir(self, url: str, etag: str = "", last_modified: str = "") -> IndirmeSonucu:
        if not beyaz_liste.izinli_mi(url):
            beyaz_liste.oneri_ekle(url)
            return IndirmeSonucu(url, 0, hata="Beyaz liste dışı alan")
        if not self._robots_izin(url):
            return IndirmeSonucu(url, 0, hata="robots.txt izin vermiyor")
        basliklar = {}
        if etag:
            basliklar["If-None-Match"] = etag
        if last_modified:
            basliklar["If-Modified-Since"] = last_modified
        self._bekle(urlparse(url).netloc)
        try:
            r = self.oturum.get(url, headers=basliklar, timeout=ZAMAN_ASIMI, stream=True)
        except Exception as e:  # ağ yok, zaman aşımı
            return IndirmeSonucu(url, 0, hata=str(e))
        son_url = getattr(r, "url", url) or url
        if son_url != url and not beyaz_liste.izinli_mi(son_url):
            return IndirmeSonucu(url, 0, hata="Yönlendirme beyaz liste dışına çıktı")
        if r.status_code == 304:
            return IndirmeSonucu(url, 304, etag=etag, last_modified=last_modified, son_url=son_url)
        if r.status_code != 200:
            return IndirmeSonucu(url, r.status_code, hata=f"HTTP {r.status_code}", son_url=son_url)
        parcalar, boyut = [], 0
        for p in r.iter_content(64 * 1024):
            boyut += len(p)
            if boyut > EN_BUYUK_BOYUT:
                return IndirmeSonucu(url, 0, hata="Dosya boyut sınırını aşıyor", son_url=son_url)
            parcalar.append(p)
        icerik = b"".join(parcalar)
        return IndirmeSonucu(
            url=url, durum=200, icerik=icerik,
            icerik_turu=r.headers.get("Content-Type", ""),
            etag=r.headers.get("ETag", ""), last_modified=r.headers.get("Last-Modified", ""),
            sha256=hashlib.sha256(icerik).hexdigest(), son_url=son_url)
