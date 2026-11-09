"""Yerel gözlem sunucusu: yalnızca 127.0.0.1 üzerinde, eşleştirme anahtarıyla eklentiden veri alır.

Uç noktalar:
  GET  /v1/durum   → bağlantı testi + beyaz liste ve sistem engel listesi (eklenti kuralları uygulamadan alır)
  POST /v1/gozlem  → bir sayfa gözlemi; cevap: değerlendirme kararı
  POST /v1/tara    → bir siteyi programın gömülü tarama motoruna devreder ({"url": ...})
  GET  /v1/tara    → motorun durumu (etkin tarama, sıra)
Güvenlik: yalnız geri döngü adresi; Host başlığı denetimi (DNS yeniden bağlama); Origin yalnız eklenti;
sabit zamanlı anahtar karşılaştırma; 3 MB istek sınırı.
"""

from __future__ import annotations

import hmac
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import __version__
from ..crawler import beyaz_liste
from .degerlendirici import (
    ISTISNALAR,
    SISTEM_ALANLARI,
    SISTEM_ANAHTARLARI,
    GozlemDegerlendirici,
)

from .eslestirme import VARSAYILAN_PORT, yeni_anahtar  # noqa: F401 - dışarıya da buradan sunulur

log = logging.getLogger("akilhocasi")
EN_BUYUK_ISTEK = 3 * 1024 * 1024


class GozlemSunucusu:
    def __init__(self, degerlendirici: GozlemDegerlendirici, anahtar: str, port: int = VARSAYILAN_PORT,
                 dosyalar=None, motor=None, bildir=None):
        self.d = degerlendirici
        self.anahtar = anahtar
        self.port = port
        self.dosyalar = dosyalar          # DosyaKuyrugu: resmî dosyalar resmî siteden indirilir
        self.motor = motor                # GozlemMotoru: "Bu siteyi tara" programın motoruna devredilir
        self.bildir = bildir or (lambda sonuc: None)
        self.httpd: ThreadingHTTPServer | None = None
        self.son_temas = 0.0

    # ---------------------------------------------------------------- yaşam döngüsü
    def baslat(self) -> bool:
        sunucu = self

        class Isleyici(BaseHTTPRequestHandler):
            server_version = "AkilHocasi"

            def log_message(self, *a):  # konsola yazma
                return

            def _origin_izinli(self) -> bool:
                origin = self.headers.get("Origin", "")
                return not origin or origin.startswith(("chrome-extension://", "moz-extension://"))

            def _host_izinli(self) -> bool:
                return self.headers.get("Host", "") in (f"127.0.0.1:{sunucu.port}", f"localhost:{sunucu.port}")

            def _cors(self) -> None:
                origin = self.headers.get("Origin", "")
                if origin.startswith(("chrome-extension://", "moz-extension://")):
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-AkilHocasi-Anahtar")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                if self.headers.get("Access-Control-Request-Private-Network", "").lower() == "true":
                    self.send_header("Access-Control-Allow-Private-Network", "true")   # Chrome yerel ağ erişimi

            def _yanit(self, kod: int, veri: dict) -> None:
                govde = json.dumps(veri, ensure_ascii=False).encode("utf-8")
                self.send_response(kod)
                self._cors()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(govde)))
                self.end_headers()
                self.wfile.write(govde)

            def _yetkili(self) -> bool:
                gelen = self.headers.get("X-AkilHocasi-Anahtar", "")
                return bool(sunucu.anahtar) and hmac.compare_digest(gelen.encode(), sunucu.anahtar.encode())

            def do_OPTIONS(self):
                if not (self._host_izinli() and self._origin_izinli()):
                    self.send_response(403)
                    self.end_headers()
                    return
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_GET(self):
                if not (self._host_izinli() and self._origin_izinli()):
                    return self._yanit(403, {"hata": "izin yok"})
                if self.path not in ("/v1/durum", "/v1/tara"):
                    return self._yanit(404, {"hata": "yok"})
                if not self._yetkili():
                    return self._yanit(401, {"hata": "eşleştirme anahtarı geçersiz"})
                sunucu.son_temas = time.time()
                if self.path == "/v1/tara":
                    return self._yanit(200, sunucu.motor.durum() if sunucu.motor else {"etkin": None, "motor": False})
                return self._yanit(200, {
                    "ok": True, "uygulama": "Akıl Hocası", "surum": __version__,
                    "birincil": beyaz_liste.BIRINCIL, "ikincil": beyaz_liste.IKINCIL,
                    "sistem_alanlari": SISTEM_ALANLARI, "sistem_anahtarlari": SISTEM_ANAHTARLARI,
                    "istisnalar": ISTISNALAR, "istatistik": sunucu.d.istatistik(),
                    "motor": bool(sunucu.motor and sunucu.motor.tarayici_yolu())})

            def do_POST(self):
                if not (self._host_izinli() and self._origin_izinli()):
                    return self._yanit(403, {"hata": "izin yok"})
                if self.path not in ("/v1/gozlem", "/v1/tara"):
                    return self._yanit(404, {"hata": "yok"})
                if not self._yetkili():
                    return self._yanit(401, {"hata": "eşleştirme anahtarı geçersiz"})
                try:
                    uzunluk = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    uzunluk = 0
                if uzunluk <= 0 or uzunluk > EN_BUYUK_ISTEK:
                    return self._yanit(413, {"hata": "istek boyutu geçersiz"})
                try:
                    kayit = json.loads(self.rfile.read(uzunluk).decode("utf-8"))
                    if not isinstance(kayit, dict):
                        raise ValueError
                except (ValueError, UnicodeDecodeError):
                    return self._yanit(400, {"hata": "geçersiz JSON"})
                sunucu.son_temas = time.time()
                if self.path == "/v1/tara":
                    if not sunucu.motor or not sunucu.motor.tarayici_yolu():
                        return self._yanit(200, {"ok": False, "motor": False,
                                                 "mesaj": "Programın tarama motoru kullanılamıyor"})
                    if kayit.get("komut") == "durdur":
                        sunucu.motor.durdur()
                        return self._yanit(200, {"ok": True, "motor": True, "mesaj": "Tarama durduruldu"})
                    ok, mesaj = sunucu.motor.ekle(str(kayit.get("url", "")))
                    return self._yanit(200, {"ok": ok, "motor": True, "mesaj": mesaj})
                try:
                    sonuc = sunucu.d.degerlendir(kayit)
                except Exception as e:  # değerlendirme hatası sunucuyu düşürmez
                    log.warning("Gözlem değerlendirme hatası: %s", e)
                    return self._yanit(500, {"hata": "değerlendirme hatası"})
                alinan = sunucu.dosyalar.ekle(sonuc.get("indirilecek", [])) if sunucu.dosyalar else 0
                sunucu.bildir(sonuc)
                return self._yanit(200, {k: v for k, v in sonuc.items() if k != "indirilecek"} |
                                   {"kuyruga_alinan": alinan})

        try:
            self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Isleyici)
        except OSError as e:
            log.warning("Gözlem sunucusu başlatılamadı (port %s): %s", self.port, e)
            return False
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, name="gozlem-sunucu", daemon=True).start()
        log.info("Gözlem sunucusu 127.0.0.1:%s üzerinde", self.port)
        return True

    def durdur(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
