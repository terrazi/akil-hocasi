"""Gömülü tarayıcı: bilgisayardaki Edge/Chrome'u görünmez (headless) ve yalıtılmış boş profille çalıştırır.

- Ek paket gerekmez: Chrome DevTools Protokolü (CDP) için en küçük WebSocket istemcisi standart kütüphaneyle yazıldı.
- Her tarama yeni, geçici bir profille başlar: çerez, oturum, kayıtlı parola yoktur; bu yüzden hiçbir kamu
  sistemine oturum açık hâlde girilemez. Profil tarama bitince silinir.
- Sayfa, eklentiyle ortak okuma kuralıyla (kurallar.js → AHKurallar.sayfaOku) sayfanın kendi betiklerinden
  ayrı bir "yalıtılmış dünyada" okunur; hiçbir öğeye tıklanmaz, form gönderilmez, indirme kapalıdır.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import queue
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("akilhocasi")
_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
ENGELLI_KAYNAKLAR = ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.svg", "*.ico", "*.bmp", "*.mp4", "*.webm",
                     "*.mp3", "*.woff", "*.woff2", "*.ttf", "*.otf", "*.eot", "*google-analytics*", "*googletagmanager*",
                     "*doubleclick*", "*facebook.net*", "*hotjar*", "*yandex.ru/metrika*"]


class TarayiciHatasi(RuntimeError):
    pass


# ============================================================================ tarayıcıyı bulma
def tarayici_bul(ozel_yol: str = "") -> str:
    """Kurulu Edge ya da Chrome'un yolu (Windows'ta önce Edge: her Windows 10/11'de vardır)."""
    if ozel_yol and Path(ozel_yol).is_file():
        return ozel_yol
    adaylar: list[str] = []
    if sys.platform == "win32":
        pf = [os.environ.get(k, "") for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        for kok in pf:
            if kok:
                adaylar += [rf"{kok}\Microsoft\Edge\Application\msedge.exe",
                            rf"{kok}\Google\Chrome\Application\chrome.exe"]
        try:
            import winreg
            for kovan in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for exe in ("msedge.exe", "chrome.exe"):
                    try:
                        with winreg.OpenKey(kovan, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as a:
                            adaylar.append(winreg.QueryValue(a, None))
                    except OSError:
                        pass
        except ImportError:
            pass
    else:
        for ad in ("microsoft-edge", "microsoft-edge-stable", "google-chrome", "google-chrome-stable",
                   "chromium", "chromium-browser"):
            yol = shutil.which(ad)
            if yol:
                adaylar.append(yol)
    for a in adaylar:
        if a and Path(a).is_file():
            return a
    return ""


# ============================================================================ WebSocket (RFC 6455, istemci)
class WebSoket:
    def __init__(self, url: str, zaman_asimi: float = 30):
        u = urlparse(url)
        self.soket = socket.create_connection((u.hostname, u.port), timeout=zaman_asimi)
        anahtar = base64.b64encode(os.urandom(16)).decode()
        istek = (f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                 f"Connection: Upgrade\r\nSec-WebSocket-Key: {anahtar}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.soket.sendall(istek.encode())
        self._tampon = b""
        while b"\r\n\r\n" not in self._tampon:
            parca = self.soket.recv(4096)
            if not parca:
                raise TarayiciHatasi("WebSocket el sıkışması kapandı")
            self._tampon += parca
        baslik, self._tampon = self._tampon.split(b"\r\n\r\n", 1)
        satirlar = baslik.decode("latin-1").split("\r\n")
        if " 101 " not in satirlar[0] + " ":
            raise TarayiciHatasi(f"WebSocket reddedildi: {satirlar[0]}")
        beklenen = base64.b64encode(hashlib.sha1((anahtar + _GUID).encode()).digest()).decode()
        alanlar = {s.split(":", 1)[0].strip().lower(): s.split(":", 1)[1].strip() for s in satirlar[1:] if ":" in s}
        if alanlar.get("sec-websocket-accept") != beklenen:
            raise TarayiciHatasi("WebSocket kabul anahtarı uyuşmuyor")
        self.soket.settimeout(None)
        self._yazma = threading.Lock()

    def _oku(self, n: int) -> bytes:
        while len(self._tampon) < n:
            parca = self.soket.recv(max(65536, n - len(self._tampon)))
            if not parca:
                raise ConnectionError("WebSocket kapandı")
            self._tampon += parca
        veri, self._tampon = self._tampon[:n], self._tampon[n:]
        return veri

    def _cerceve_gonder(self, islem: int, veri: bytes) -> None:
        bas = bytes([0x80 | islem])
        n = len(veri)
        if n < 126:
            bas += bytes([0x80 | n])
        elif n < 65536:
            bas += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            bas += bytes([0x80 | 127]) + struct.pack(">Q", n)
        maske = os.urandom(4)
        maskeli = bytes(b ^ maske[i % 4] for i, b in enumerate(veri)) if n < 4096 else _maskele_hizli(veri, maske)
        with self._yazma:
            self.soket.sendall(bas + maske + maskeli)

    def gonder(self, metin: str) -> None:
        self._cerceve_gonder(0x1, metin.encode("utf-8"))

    def al(self) -> str:
        parcalar: list[bytes] = []
        while True:
            b1, b2 = self._oku(2)
            islem, son = b1 & 0x0F, bool(b1 & 0x80)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._oku(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._oku(8))[0]
            maske = self._oku(4) if b2 & 0x80 else None
            veri = self._oku(n)
            if maske:
                veri = _maskele_hizli(veri, maske)
            if islem == 0x8:
                raise ConnectionError("WebSocket kapatıldı")
            if islem == 0x9:
                self._cerceve_gonder(0xA, veri)
                continue
            if islem == 0xA:
                continue
            parcalar.append(veri)
            if son:
                return b"".join(parcalar).decode("utf-8", errors="replace")

    def kapat(self) -> None:
        try:
            self._cerceve_gonder(0x8, b"")
        except OSError:
            pass
        try:
            self.soket.close()
        except OSError:
            pass


def _maskele_hizli(veri: bytes, maske: bytes) -> bytes:
    n = len(veri)
    tam = (maske * (n // 4 + 1))[:n]
    return (int.from_bytes(veri, "big") ^ int.from_bytes(tam, "big")).to_bytes(n, "big") if n else b""


# ============================================================================ CDP oturumu
class CDP:
    def __init__(self, ws: WebSoket):
        self.ws = ws
        self._sayac = 0
        self._kilit = threading.Lock()
        self._bekleyen: dict[int, tuple[threading.Event, list]] = {}
        self._olaylar: queue.Queue = queue.Queue()
        self.kapandi = False
        threading.Thread(target=self._okuyucu, name="cdp-okuyucu", daemon=True).start()

    def _okuyucu(self) -> None:
        try:
            while True:
                m = json.loads(self.ws.al())
                if "id" in m:
                    kayit = self._bekleyen.pop(m["id"], None)
                    if kayit:
                        kayit[1].append(m)
                        kayit[0].set()
                elif m.get("method") == "Page.javascriptDialogOpening":
                    # Uyarı/onay pencereleri asla kabul edilmez
                    self._gonder("Page.handleJavaScriptDialog", {"accept": False}, m.get("sessionId"))
                else:
                    self._olaylar.put(m)
        except (ConnectionError, OSError, ValueError):
            pass
        finally:
            self.kapandi = True
            for olay, kutu in list(self._bekleyen.values()):
                kutu.append({"error": {"message": "tarayıcı bağlantısı kapandı"}})
                olay.set()

    def _gonder(self, yontem: str, parametre: dict | None, oturum: str | None) -> tuple[int, threading.Event, list]:
        with self._kilit:
            self._sayac += 1
            no = self._sayac
        olay, kutu = threading.Event(), []
        self._bekleyen[no] = (olay, kutu)
        ileti = {"id": no, "method": yontem, "params": parametre or {}}
        if oturum:
            ileti["sessionId"] = oturum
        self.ws.gonder(json.dumps(ileti))
        return no, olay, kutu

    def komut(self, yontem: str, parametre: dict | None = None, oturum: str | None = None,
              zaman_asimi: float = 30) -> dict:
        if self.kapandi:
            raise TarayiciHatasi("tarayıcı bağlantısı kapalı")
        no, olay, kutu = self._gonder(yontem, parametre, oturum)
        if not olay.wait(zaman_asimi):
            self._bekleyen.pop(no, None)
            raise TarayiciHatasi(f"{yontem} zaman aşımı")
        m = kutu[0]
        if "error" in m:
            raise TarayiciHatasi(f"{yontem}: {m['error'].get('message', m['error'])}")
        return m.get("result", {})

    def olay_bekle(self, yontem: str, oturum: str | None, zaman_asimi: float) -> dict | None:
        bitis = time.monotonic() + zaman_asimi
        while (kalan := bitis - time.monotonic()) > 0:
            try:
                m = self._olaylar.get(timeout=min(kalan, 0.5))
            except queue.Empty:
                if self.kapandi:
                    return None
                continue
            if m.get("method") == yontem and (oturum is None or m.get("sessionId") == oturum):
                return m.get("params", {})
        return None

    def olay_al(self, oturum: str | None, zaman_asimi: float) -> dict | None:
        """Bu oturumun sıradaki olayı (zaman aşımında ya da bağlantı kapanınca None)."""
        bitis = time.monotonic() + zaman_asimi
        while (kalan := bitis - time.monotonic()) > 0:
            try:
                m = self._olaylar.get(timeout=min(kalan, 0.5))
            except queue.Empty:
                if self.kapandi:
                    return None
                continue
            if oturum is None or m.get("sessionId") == oturum:
                return m
        return None

    def olaylari_temizle(self) -> None:
        while not self._olaylar.empty():
            self._olaylar.get_nowait()


# ============================================================================ görünmez tarayıcı
def kurallar_kaynagi() -> str:
    from .kurulum import eklenti_kaynagi
    return (eklenti_kaynagi() / "kurallar.js").read_text(encoding="utf-8")


class BasliksizTarayici:
    """Görünmez Edge/Chrome. with bloğuyla kullanılır; çıkışta süreç kapanır ve geçici profil silinir."""

    def __init__(self, yol: str = "", ek_argumanlar: list[str] | None = None, baslatma_suresi: float = 30,
                 durulma: float = 1.2):
        self.yol = tarayici_bul(yol)
        if not self.yol:
            raise TarayiciHatasi("Bilgisayarda Edge ya da Chrome bulunamadı")
        self.ek = list(ek_argumanlar or [])
        self.baslatma_suresi = baslatma_suresi
        self.profil = ""
        self.surec: subprocess.Popen | None = None
        self.cdp: CDP | None = None
        self.oturum = ""
        self._kurallar = kurallar_kaynagi()
        self.surum = ""
        self.son_durum = 0
        self.durulma = durulma

    # ----------------------------------------------------------------- yaşam döngüsü
    def __enter__(self) -> BasliksizTarayici:
        self.baslat()
        return self

    def __exit__(self, *_) -> None:
        self.kapat()

    def baslat(self) -> None:
        self.profil = tempfile.mkdtemp(prefix="akilhocasi_tarayici_")
        argumanlar = [self.yol, "--headless=new", f"--user-data-dir={self.profil}", "--remote-debugging-port=0",
                      "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync",
                      "--disable-component-update", "--disable-default-apps", "--disable-background-networking",
                      "--disable-features=Translate,MediaRouter,OptimizationHints", "--mute-audio", "--disable-gpu",
                      "--no-pings", "--password-store=basic", "--window-size=1366,900", "--lang=tr-TR",
                      *self.ek, "about:blank"]
        bayrak = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.surec = subprocess.Popen(argumanlar, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      stdin=subprocess.DEVNULL, creationflags=bayrak)
        dosya = Path(self.profil) / "DevToolsActivePort"
        bitis = time.monotonic() + self.baslatma_suresi
        while time.monotonic() < bitis:
            if self.surec.poll() is not None:
                raise TarayiciHatasi(f"Tarayıcı başlatılamadı (çıkış kodu {self.surec.returncode})")
            if dosya.is_file():
                satirlar = dosya.read_text(encoding="utf-8").split()
                if len(satirlar) >= 2:
                    break
            time.sleep(0.1)
        else:
            self.kapat()
            raise TarayiciHatasi("Tarayıcı zamanında açılmadı")
        port, yol = satirlar[0], satirlar[1]
        self.cdp = CDP(WebSoket(f"ws://127.0.0.1:{port}{yol}"))
        self.surum = self.cdp.komut("Browser.getVersion").get("product", "")
        hedef = self.cdp.komut("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.oturum = self.cdp.komut("Target.attachToTarget", {"targetId": hedef, "flatten": True})["sessionId"]
        for yontem, parametre in (("Page.enable", None), ("Network.enable", None),
                                  ("Network.setBlockedURLs", {"urls": ENGELLI_KAYNAKLAR}),
                                  ("Page.setDownloadBehavior", {"behavior": "deny"})):
            try:
                self.cdp.komut(yontem, parametre, self.oturum)
            except TarayiciHatasi as e:            # eski sürümlerde bazıları yok: tarama yine güvenli
                log.info("CDP %s: %s", yontem, e)
        try:
            self.cdp.komut("Browser.setDownloadBehavior", {"behavior": "deny"})
        except TarayiciHatasi:
            pass

    def kapat(self) -> None:
        if self.cdp:
            try:
                self.cdp.komut("Browser.close", zaman_asimi=5)
            except TarayiciHatasi:
                pass
            self.cdp.ws.kapat()
            self.cdp = None
        if self.surec:
            try:
                self.surec.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.surec.kill()
                self.surec.wait(timeout=5)
            self.surec = None
        if self.profil:
            for _ in range(10):                         # Windows'ta dosyalar süreç kapanınca serbest kalır
                shutil.rmtree(self.profil, ignore_errors=True)
                if not Path(self.profil).exists():
                    break
                time.sleep(0.3)
            self.profil = ""

    # ----------------------------------------------------------------- okuma
    def _yalitilmis_dunya(self, cerceve: str) -> int:
        return self.cdp.komut("Page.createIsolatedWorld", {"frameId": cerceve, "worldName": "akilhocasi",
                                                           "grantUniveralAccess": False}, self.oturum)["executionContextId"]

    def _degerlendir(self, ifade: str, cerceve: str, bekle_promise: bool = False, zaman_asimi: float = 30):
        baglam = self._yalitilmis_dunya(cerceve)
        sonuc = self.cdp.komut("Runtime.evaluate", {"expression": ifade, "contextId": baglam, "returnByValue": True,
                                                    "awaitPromise": bekle_promise, "timeout": int(zaman_asimi * 1000)},
                               self.oturum, zaman_asimi=zaman_asimi + 5)
        if "exceptionDetails" in sonuc:
            ayrinti = sonuc["exceptionDetails"]
            raise TarayiciHatasi("Sayfa okunamadı: " + str(ayrinti.get("exception", {}).get("description", ayrinti.get("text")))[:300])
        return sonuc.get("result", {}).get("value")

    def git(self, url: str, zaman_asimi: float = 25, durulma: float | None = None) -> str:
        """Adrese gider, yüklenmeyi bekler, ana belgenin HTTP durumunu self.son_durum'a yazar. Çerçeve kimliği döner."""
        self.cdp.olaylari_temizle()
        self.son_durum = 0
        sonuc = self.cdp.komut("Page.navigate", {"url": url}, self.oturum, zaman_asimi=zaman_asimi)
        if sonuc.get("errorText"):
            raise TarayiciHatasi(f"Sayfa açılamadı: {sonuc['errorText']}")
        cerceve = sonuc.get("frameId") or self.cdp.komut("Page.getFrameTree", None, self.oturum)["frameTree"]["frame"]["id"]
        bitis = time.monotonic() + zaman_asimi
        while (kalan := bitis - time.monotonic()) > 0:
            m = self.cdp.olay_al(self.oturum, kalan)
            if m is None:
                log.info("Yükleme olayı gelmedi, var olan içerik okunacak: %s", url)
                break
            p = m.get("params", {})
            if m.get("method") == "Network.responseReceived" and p.get("type") == "Document" \
                    and p.get("frameId") == cerceve:
                self.son_durum = int(p.get("response", {}).get("status", 0))
            elif m.get("method") == "Page.loadEventFired":
                break
        time.sleep(self.durulma if durulma is None else durulma)   # tek sayfa uygulamalarının içeriği otursun
        return cerceve

    def sayfa_oku(self, url: str, zaman_asimi: float = 25, durulma: float | None = None) -> dict:
        cerceve = self.git(url, zaman_asimi, durulma)
        if self.son_durum >= 400:
            return {"tur": "engel", "url": url, "neden": f"HTTP {self.son_durum}"}
        ifade = self._kurallar + "\n;JSON.stringify(globalThis.AHKurallar.sayfaOku(document, location));"
        deger = self._degerlendir(ifade, cerceve)
        return json.loads(deger) if deger else {"tur": "engel", "url": url, "neden": "boş yanıt"}

    def robots_getir(self, koken: str) -> str | None:
        """robots.txt tarayıcının kendi ağ yığınıyla. Dönüş: metin; '' = yok (4xx); None = alınamadı (5xx, ağ hatası)."""
        try:
            cerceve = self.git(koken + "/robots.txt", zaman_asimi=20, durulma=0.2)
        except TarayiciHatasi:
            return None
        if 400 <= self.son_durum < 500:
            return ""
        if self.son_durum != 200:
            return None
        return self._degerlendir("document.body ? document.body.innerText : ''", cerceve) or ""
