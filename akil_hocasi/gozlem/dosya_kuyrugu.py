"""Gözlemde ve taramada görülen resmî dosyaları (PDF, Word, Excel) doğrudan resmî siteden indirir.

Eklentiden ya da gömülü tarayıcıdan gelen dosya bağlantısı yalnızca adres olarak kullanılır; içerik her zaman
programın kendi indiricisiyle (beyaz liste, robots.txt, hız sınırı) resmî sunucudan alınır.
"""

from __future__ import annotations

import logging
import queue
import threading

from ..crawler import beyaz_liste
from ..crawler.kaynaklar import kod_bul

log = logging.getLogger("akilhocasi")


class DosyaKuyrugu:
    def __init__(self, tarayici, kutuphane):
        self.tarayici = tarayici
        self.k = kutuphane
        self.kuyruk: queue.Queue = queue.Queue(maxsize=5000)
        self._gorulen: set[str] = set()
        self._durdur = threading.Event()
        self.islenen = 0
        self._is = threading.Thread(target=self._calis, name="gozlem-dosya", daemon=True)
        self._is.start()

    def ekle(self, ogeler: list[dict]) -> int:
        n = 0
        for oge in ogeler or []:
            url = oge.get("url", "")
            if url in self._gorulen or not beyaz_liste.birincil_mi(url):
                continue
            self._gorulen.add(url)
            try:
                self.kuyruk.put_nowait(oge)
                n += 1
            except queue.Full:
                break
        return n

    def bekleyen(self) -> int:
        return self.kuyruk.qsize()

    def durdur(self) -> None:
        self._durdur.set()

    def _calis(self) -> None:
        from ..crawler.tarayici import TaramaRaporu
        while not self._durdur.is_set():
            try:
                oge = self.kuyruk.get(timeout=1)
            except queue.Empty:
                continue
            if self.tarayici is None:
                continue
            url = oge["url"]
            if self.k.kaynak_durumu(url):          # zaten biliniyor; güncellemeyi takvimli tarayıcı yapar
                continue
            rapor = TaramaRaporu("gozlem")
            try:
                s = self.tarayici._getir(url, rapor)
                if s.basarili:
                    kod = oge.get("kod") or kod_bul(oge.get("metin", ""))
                    togu = "gop.edu.tr" in url
                    self.tarayici.belge_isle(
                        s, rapor, tur="togu" if togu else "web", kimlik=kod or url,
                        baslik=oge.get("metin") or kod or url.rsplit("/", 1)[-1],
                        kaynak_turu="TOGÜ belgesi" if togu else "Resmî görüş", kod=kod,
                        sayfa_url=oge.get("sayfa_url", ""))
                    self.islenen += 1
            except Exception as e:  # noqa: BLE001 - tek dosyanın hatası kuyruğu durdurmaz
                log.warning("Gözlem dosyası indirilemedi %s: %s", url, e)
