"""Gömülü tarama motoru: resmî siteleri programın kendi görünmez tarayıcısıyla arka planda tarar.

Eklenti gerekmez. İş kuyruğu: Kaynak Havuzu ekranındaki "Şimdi tara", eklentideki "Bu siteyi tara" ve
zamanlayıcının boştayken başlattığı site taramaları buraya düşer. Her site için:
  robots.txt → sayfa oku (ortak kural) → son adresi yeniden denetle → değerlendirici (kabul/ipucu/ret)
  → dosya bağlantıları resmî siteden indirilmek üzere kuyruğa → aynı alandaki güvenli bağlantılar sıraya
  → benzer şablon süzgeci, derinlik ve sayfa sınırı, hız profili. Durdurulan tarama kaldığı yerden sürer.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from urllib.parse import urlparse

from ..crawler import beyaz_liste
from .cdp import BasliksizTarayici, TarayiciHatasi, tarayici_bul
from .degerlendirici import GozlemDegerlendirici, sistem_mi
from .kurallar import bekleme, genisletilsin_mi, robots_ayristir, robots_izinli, yol_kalibi

log = logging.getLogger("akilhocasi")

SEMA = """
CREATE TABLE IF NOT EXISTS gozlem_tarama (
    kok TEXT PRIMARY KEY, durum TEXT NOT NULL, veri TEXT NOT NULL, guncelleme TEXT NOT NULL
);
"""
VARSAYILAN_AYAR = {"hiz": "normal", "en_cok_sayfa": 200, "derinlik": 4, "tarayici_yolu": ""}


@dataclass
class SiteTaramasi:
    kok: str
    host: str
    en_cok: int = 200
    derinlik: int = 4
    durum: str = "bekliyor"          # bekliyor | calisiyor | duraklatildi | bitti
    neden: str = ""
    sayfa: int = 0
    kuyruk: list = field(default_factory=list)      # [[url, derinlik], ...]
    gorulen: list = field(default_factory=list)
    gecmis: list = field(default_factory=list)      # [{"kalip", "imza"}] son 300 sayfa
    sayac: dict = field(default_factory=dict)
    robots: list | None = None
    baslangic: str = ""
    bitis: str = ""
    son_sayfa: str = ""

    def say(self, anahtar: str) -> None:
        self.sayac[anahtar] = self.sayac.get(anahtar, 0) + 1

    def ozet(self) -> dict:
        return {"kok": self.kok, "durum": self.durum, "neden": self.neden, "sayfa": self.sayfa, "en_cok": self.en_cok,
                "kuyruk": len(self.kuyruk), "sayac": dict(self.sayac), "son_sayfa": self.son_sayfa,
                "baslangic": self.baslangic, "bitis": self.bitis}


def kok_adres(url: str) -> str | None:
    u = urlparse((url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    return f"{u.scheme}://{u.hostname.lower()}{(':' + str(u.port)) if u.port else ''}{u.path or '/'}" + \
        (f"?{u.query}" if u.query else "")


class GozlemMotoru:
    def __init__(self, degerlendirici: GozlemDegerlendirici, dosyalar=None,
                 ayar: Callable[[], dict] | None = None, bildir: Callable[[dict], None] | None = None,
                 tarayici_fabrikasi: Callable[[], BasliksizTarayici] | None = None):
        self.d = degerlendirici
        self.k = degerlendirici.k
        self.dosyalar = dosyalar
        self._ayar = ayar or (lambda: {})
        self.bildir = bildir or (lambda durum: None)
        self._fabrika = tarayici_fabrikasi or (lambda: BasliksizTarayici(self.ayar()["tarayici_yolu"]))
        self._isler: queue.Queue[str] = queue.Queue()
        self._sirada: list[str] = []
        self._durdur = threading.Event()
        self._kapat = threading.Event()
        self.etkin: SiteTaramasi | None = None
        self.son_hata = ""
        self.tarayici_surumu = ""
        with self.k._kilit, self.k.db:
            self.k.db.executescript(SEMA)
        self._is = threading.Thread(target=self._calis, name="gozlem-motoru", daemon=True)
        self._is.start()

    # ------------------------------------------------------------------ dış arayüz
    def ayar(self) -> dict:
        return {**VARSAYILAN_AYAR, **{k: v for k, v in (self._ayar() or {}).items() if v not in (None, "")}}

    def tarayici_yolu(self) -> str:
        return tarayici_bul(self.ayar()["tarayici_yolu"])

    def ekle(self, url: str) -> tuple[bool, str]:
        """Bir siteyi tarama kuyruğuna ekler. (kabul, açıklama)"""
        kok = kok_adres(url)
        if not kok or not beyaz_liste.birincil_mi(kok) or sistem_mi(kok):
            return False, "Yalnız beyaz listedeki herkese açık resmî siteler taranır; kamu sistemleri ve giriş sayfaları taranmaz."
        if (self.etkin and self.etkin.kok == kok and self.etkin.durum == "calisiyor") or kok in self._sirada:
            return True, "Bu site zaten taranıyor ya da sırada."
        self._sirada.append(kok)
        self._isler.put(kok)
        self._bildir()
        return True, "Tarama sıraya alındı."

    def durdur(self) -> None:
        """Etkin taramayı duraklatır (kaldığı yer saklanır) ve sıradakileri boşaltır."""
        self._sirada.clear()
        while not self._isler.empty():
            try:
                self._isler.get_nowait()
            except queue.Empty:
                break
        self._durdur.set()
        self._bildir()

    def kapat(self) -> None:
        self._kapat.set()
        self.durdur()

    def durum(self) -> dict:
        return {"etkin": self.etkin.ozet() if self.etkin else None, "sirada": list(self._sirada),
                "son_hata": self.son_hata, "tarayici": self.tarayici_surumu,
                "dosya_kuyrugu": self.dosyalar.bekleyen() if self.dosyalar else 0}

    def gecmis(self, sinir: int = 50) -> list[dict]:
        satirlar = self.k.db.execute("SELECT veri FROM gozlem_tarama ORDER BY guncelleme DESC LIMIT ?", (sinir,))
        cikti = []
        for r in satirlar:
            try:
                t = SiteTaramasi(**json.loads(r[0]))
                cikti.append(t.ozet())
            except (TypeError, ValueError):
                continue
        return cikti

    # ------------------------------------------------------------------ kalıcılık
    def _kaydet(self, t: SiteTaramasi) -> None:
        with self.k._kilit, self.k.db:
            self.k.db.execute(
                "INSERT INTO gozlem_tarama(kok, durum, veri, guncelleme) VALUES(?,?,?,?)"
                " ON CONFLICT(kok) DO UPDATE SET durum=excluded.durum, veri=excluded.veri, guncelleme=excluded.guncelleme",
                (t.kok, t.durum, json.dumps(asdict(t), ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))

    def _yukle_ya_da_yeni(self, kok: str) -> SiteTaramasi:
        a = self.ayar()
        r = self.k.db.execute("SELECT durum, veri FROM gozlem_tarama WHERE kok=?", (kok,)).fetchone()
        if r and r["durum"] in ("duraklatildi", "calisiyor"):
            try:
                t = SiteTaramasi(**json.loads(r["veri"]))
                if t.kuyruk:
                    t.neden = "Kaldığı yerden sürüyor"
                    return t
            except (TypeError, ValueError):
                pass
        return SiteTaramasi(kok=kok, host=(urlparse(kok).hostname or "").lower(),
                            en_cok=max(1, min(5000, int(a["en_cok_sayfa"]))),
                            derinlik=max(0, min(10, int(a["derinlik"]))),
                            kuyruk=[[kok, 0]], gorulen=[kok])

    def _bildir(self) -> None:
        try:
            self.bildir(self.durum())
        except Exception as e:  # noqa: BLE001 - arayüz bildirimi taramayı durdurmaz
            log.debug("Gözlem bildirimi: %s", e)

    # ------------------------------------------------------------------ çalışma döngüsü
    def _calis(self) -> None:
        while not self._kapat.is_set():
            try:
                kok = self._isler.get(timeout=1)
            except queue.Empty:
                continue
            try:
                with self._fabrika() as tarayici:
                    self.tarayici_surumu = tarayici.surum
                    self.son_hata = ""
                    while kok:
                        if kok in self._sirada:
                            self._sirada.remove(kok)
                        self._durdur.clear()
                        self._site_tara(tarayici, kok)
                        try:
                            kok = self._isler.get_nowait()
                        except queue.Empty:
                            kok = None
            except TarayiciHatasi as e:
                self.son_hata = str(e)
                log.warning("Gömülü tarayıcı: %s", e)
                if self.etkin and self.etkin.durum == "calisiyor":
                    self.etkin.durum, self.etkin.neden = "duraklatildi", f"Tarayıcı hatası: {e}"
                    self._kaydet(self.etkin)
            except Exception as e:  # noqa: BLE001 - motor iş parçacığı çökmez
                self.son_hata = f"Beklenmeyen hata: {e}"
                log.exception("Gözlem motoru")
            self._bildir()

    def _site_tara(self, tarayici: BasliksizTarayici, kok: str) -> None:
        t = self._yukle_ya_da_yeni(kok)
        self.etkin = t
        t.durum, t.bitis = "calisiyor", ""
        t.baslangic = t.baslangic or datetime.now().isoformat(timespec="seconds")
        a = self.ayar()
        self._bildir()

        if t.robots is None:
            u = urlparse(kok)
            metin = tarayici.robots_getir(f"{u.scheme}://{u.netloc}")
            if metin is None:
                self._bitir(t, "robots.txt alınamadı; site bu kez taranmadı")
                return
            t.robots = robots_ayristir(metin)

        gorulen = set(t.gorulen)
        while t.kuyruk and t.sayfa < t.en_cok:
            if self._durdur.is_set() or self._kapat.is_set():
                t.durum, t.neden = "duraklatildi", "Durduruldu; yeniden başlatınca kaldığı yerden sürer"
                self._kaydet(t)
                self._bildir()
                return
            url, derinlik = t.kuyruk.pop(0)
            u = urlparse(url)
            if not robots_izinli(t.robots, u.path + (f"?{u.query}" if u.query else "")):
                t.say("robots")
                continue
            try:
                sonuc = tarayici.sayfa_oku(url)
            except TarayiciHatasi as e:
                t.say("hata")
                t.sayfa += 1
                log.info("Sayfa okunamadı %s: %s", url, e)
                if tarayici.cdp is None or tarayici.cdp.kapandi:
                    t.kuyruk.insert(0, [url, derinlik])
                    t.sayfa -= 1
                    raise
                continue
            t.sayfa += 1
            t.son_sayfa = url
            if sonuc.get("tur") != "sayfa":
                t.say("engel" if sonuc.get("tur") == "engel" else "kapsam_disi")
            else:
                kayit = sonuc["kayit"]
                son = kayit.get("url", url)
                # Yönlendirme sonrası adres yeniden denetlenir (giriş sayfasına ya da başka alana gidildiyse okunmaz)
                if sistem_mi(son) or not beyaz_liste.birincil_mi(son) or (urlparse(son).hostname or "").lower() != t.host:
                    t.say("yonlendirme")
                else:
                    karar = self.d.degerlendir({"url": son, "baslik": kayit.get("baslik", ""), "metin": kayit.get("metin", ""),
                                                "dosyalar": kayit.get("dosyalar", []), "dil": kayit.get("dil", ""),
                                                "mod": "motor"})
                    t.say(karar["karar"])
                    if self.dosyalar and karar.get("indirilecek"):
                        t.sayac["dosya"] = t.sayac.get("dosya", 0) + self.dosyalar.ekle(karar["indirilecek"])
                    kalip = yol_kalibi(son)
                    if derinlik < t.derinlik:
                        if genisletilsin_mi(kayit.get("imza", []), kalip, t.gecmis):
                            for yeni in kayit.get("taranacak", []):
                                if yeni in gorulen or len(t.kuyruk) >= 3000:
                                    continue
                                if (urlparse(yeni).hostname or "").lower() != t.host or sistem_mi(yeni):
                                    continue
                                gorulen.add(yeni)
                                t.kuyruk.append([yeni, derinlik + 1])
                        else:
                            t.say("benzer")
                    t.gecmis.append({"kalip": kalip, "imza": kayit.get("imza", [])[:150]})
                    t.gecmis = t.gecmis[-300:]
            t.gorulen = list(gorulen)[-8000:]
            if t.sayfa % 10 == 0:
                self._kaydet(t)
            self._bildir()
            if t.kuyruk and t.sayfa < t.en_cok:
                self._durdur.wait(bekleme(a["hiz"]))
        self._bitir(t, "Sayfa sınırına ulaşıldı" if t.sayfa >= t.en_cok else "Sitedeki erişilebilir sayfalar tamamlandı")

    def _bitir(self, t: SiteTaramasi, neden: str) -> None:
        t.durum, t.neden, t.bitis = "bitti", neden, datetime.now().isoformat(timespec="seconds")
        t.kuyruk = []
        self._kaydet(t)
        self._bildir()
