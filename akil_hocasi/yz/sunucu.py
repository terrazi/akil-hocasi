"""llama.cpp sunucusu (llama-server) yönetimi ve istemcisi.

Model ayrı bir süreçte çalışır: çökerse programı düşürmez, kapatılınca belleği tamamen bırakır. Yalnız
127.0.0.1 üzerinde rastgele bir bağlantı noktası dinlenir. OpenAI uyumlu uç noktalar kullanılır:
  /v1/chat/completions (JSON şemasıyla yapılandırılmış çıktı, düşünme kipi denetimi, akış)
  /v1/embeddings (anlam vektörleri; Qwen3 Embedding için son belirteç havuzlama)
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .donanim import is_parcacigi_sayisi

log = logging.getLogger("akilhocasi")
_DUSUNCE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class ModelHatasi(RuntimeError):
    pass


def sunucu_exe(ozel: str = "") -> str:
    """llama-server yolu: ayardaki, programla gelen ya da PATH'teki."""
    if ozel and Path(ozel).is_file():
        return ozel
    ad = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    adaylar = []
    if getattr(sys, "frozen", False):
        adaylar.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "llama" / ad)
        adaylar.append(Path(sys.executable).parent / "llama" / ad)
    adaylar.append(Path(__file__).resolve().parents[2] / "derleme" / "llama" / ad)
    for a in adaylar:
        if a.is_file():
            return str(a)
    return shutil.which(ad) or ""


_IS_NESNESI = None


def _ebeveynle_kapansin(surec: subprocess.Popen) -> None:
    """Windows: model sunucusunu "iş nesnesine" bağlar; program nasıl kapanırsa kapansın (görev yöneticisi, kaldırma,
    çökme) sunucu da kapanır, bellekte sahipsiz llama-server kalmaz ve dosyalar kilitli kalmaz."""
    global _IS_NESNESI
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class _Temel(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _Gc(ctypes.Structure):
            _fields_ = [(ad, ctypes.c_uint64) for ad in ("ReadOperationCount", "WriteOperationCount",
                                                          "OtherOperationCount", "ReadTransferCount",
                                                          "WriteTransferCount", "OtherTransferCount")]

        class _Genis(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _Temel), ("IoInfo", _Gc), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if _IS_NESNESI is None:
            h = k32.CreateJobObjectW(None, None)
            bilgi = _Genis()
            bilgi.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not h or not k32.SetInformationJobObject(h, 9, ctypes.byref(bilgi), ctypes.sizeof(bilgi)):
                raise OSError(ctypes.get_last_error())
            _IS_NESNESI = h
        if not k32.AssignProcessToJobObject(_IS_NESNESI, wintypes.HANDLE(int(surec._handle))):
            raise OSError(ctypes.get_last_error())
    except Exception as e:  # noqa: BLE001 - bağlanamazsa program kapanırken durdur() yine çalışır
        log.debug("İş nesnesine bağlanamadı: %s", e)


def _bos_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LlamaSunucusu:
    def __init__(self, model_yolu: str, tur: str = "sohbet", baglam: int = 8192, is_parcacigi: int = 0,
                 exe: str = "", gunluk_klasoru: Path | None = None, ek_argumanlar: list[str] | None = None,
                 havuzlama: str = "last"):
        self.model_yolu = model_yolu
        self.tur = tur
        self.baglam = baglam
        self.is_parcacigi = is_parcacigi or is_parcacigi_sayisi()
        self.exe = sunucu_exe(exe)
        self.gunluk = (gunluk_klasoru / f"llama_{tur}.log") if gunluk_klasoru else None
        self.ek = list(ek_argumanlar or [])
        self.havuzlama = havuzlama
        self.port = 0
        self.surec: subprocess.Popen | None = None
        self._kilit = threading.Lock()

    @property
    def adres(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def calisiyor(self) -> bool:
        return self.surec is not None and self.surec.poll() is None

    def baslat(self, zaman_asimi: float = 300, ilerleme: Callable[[str], None] | None = None) -> None:
        if not self.exe:
            raise ModelHatasi("llama-server bulunamadı (programla gelmesi gerekir)")
        if not Path(self.model_yolu).is_file():
            raise ModelHatasi(f"Model dosyası yok: {self.model_yolu}")
        self.port = _bos_port()
        argumanlar = [self.exe, "-m", self.model_yolu, "--host", "127.0.0.1", "--port", str(self.port),
                      "-c", str(self.baglam), "-t", str(self.is_parcacigi), "-np", "1"]
        if self.tur == "anlam":
            argumanlar += ["--embeddings", "--pooling", self.havuzlama, "-b", "4096", "-ub", "4096"]
        else:
            argumanlar += ["--jinja"]
        argumanlar += self.ek
        cikis = open(self.gunluk, "ab") if self.gunluk else subprocess.DEVNULL  # noqa: SIM115
        self.surec = subprocess.Popen(argumanlar, stdout=cikis, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        _ebeveynle_kapansin(self.surec)
        bitis = time.monotonic() + zaman_asimi
        while time.monotonic() < bitis:
            if self.surec.poll() is not None:
                raise ModelHatasi(f"Model sunucusu kapandı (kod {self.surec.returncode}). {self._gunluk_sonu()}")
            try:
                with urllib.request.urlopen(f"{self.adres}/health", timeout=2) as y:  # noqa: S310 - yerel
                    if y.status == 200:
                        log.info("Model sunucusu hazır: %s (%s)", Path(self.model_yolu).name, self.tur)
                        return
            except urllib.error.HTTPError as e:
                if e.code != 503:                    # 503 = model yükleniyor
                    raise ModelHatasi(f"Model sunucusu yanıtı: {e.code}") from e
                if ilerleme:
                    ilerleme("Model belleğe yükleniyor")
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.4)
        self.durdur()
        raise ModelHatasi("Model zamanında yüklenemedi")

    def _gunluk_sonu(self) -> str:
        if not self.gunluk or not self.gunluk.is_file():
            return ""
        try:
            return self.gunluk.read_bytes()[-600:].decode("utf-8", "replace").strip().splitlines()[-1]
        except (OSError, IndexError):
            return ""

    def durdur(self) -> None:
        if self.surec and self.surec.poll() is None:
            self.surec.terminate()
            try:
                self.surec.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.surec.kill()
        self.surec = None

    # ------------------------------------------------------------------ istekler
    def _post(self, yol: str, govde: dict, zaman_asimi: float):
        if not self.calisiyor():
            raise ModelHatasi("Model sunucusu çalışmıyor")
        r = urllib.request.Request(f"{self.adres}{yol}", data=json.dumps(govde).encode("utf-8"),
                                   headers={"Content-Type": "application/json"}, method="POST")
        try:
            return urllib.request.urlopen(r, timeout=zaman_asimi)  # noqa: S310 - yerel sunucu
        except urllib.error.HTTPError as e:
            ayrinti = e.read()[:300].decode("utf-8", "replace")
            raise ModelHatasi(f"Model isteği reddedildi ({e.code}): {ayrinti}") from e
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise ModelHatasi(f"Model isteği başarısız: {e}") from e

    def sohbet(self, mesajlar: list[dict], max_tokens: int = 900, sicaklik: float = 0.2,
               json_sema: dict | None = None, json_mod: bool = False, dusunme: bool = False,
               akis: Callable[[str], None] | None = None, zaman_asimi: float = 600) -> str:
        govde: dict = {"messages": mesajlar, "max_tokens": max_tokens, "temperature": sicaklik,
                       "top_p": 0.9, "cache_prompt": True, "chat_template_kwargs": {"enable_thinking": dusunme}}
        if json_sema:
            govde["response_format"] = {"type": "json_schema", "json_schema": {"name": "cikti", "schema": json_sema}}
        elif json_mod:
            govde["response_format"] = {"type": "json_object"}
        with self._kilit:                              # tek yuva: istekler sırayla
            if akis is None:
                with self._post("/v1/chat/completions", govde, zaman_asimi) as y:
                    veri = json.loads(y.read().decode("utf-8"))
                metin = veri["choices"][0]["message"].get("content") or ""
            else:
                govde["stream"] = True
                parcalar: list[str] = []
                with self._post("/v1/chat/completions", govde, zaman_asimi) as y:
                    for satir in y:
                        satir = satir.decode("utf-8", "replace").strip()
                        if not satir.startswith("data:"):
                            continue
                        icerik = satir[5:].strip()
                        if icerik == "[DONE]":
                            break
                        try:
                            delta = json.loads(icerik)["choices"][0].get("delta", {})
                        except (ValueError, KeyError, IndexError):
                            continue
                        p = delta.get("content") or ""
                        if p:
                            parcalar.append(p)
                            akis(p)
                metin = "".join(parcalar)
        return _DUSUNCE.sub("", metin).strip()

    def vektor(self, metinler: list[str], parti: int = 16) -> np.ndarray:
        """Normalleştirilmiş anlam vektörleri (satır başına bir metin)."""
        cikti = []
        for i in range(0, len(metinler), parti):
            with self._kilit, self._post("/v1/embeddings", {"input": metinler[i:i + parti], "model": "anlam"}, 300) as y:
                veri = json.loads(y.read().decode("utf-8"))
            for d in sorted(veri["data"], key=lambda x: x["index"]):
                v = np.asarray(d["embedding"], dtype=np.float32)
                if v.ndim > 1:                          # bazı sürümler belirteç başına döndürür: son belirteç
                    v = v[-1]
                n = float(np.linalg.norm(v)) or 1.0
                cikti.append(v / n)
        return np.vstack(cikti) if cikti else np.zeros((0, 0), dtype=np.float32)


class SunucuModeli:
    """Cevap hattının kullandığı dil modeli arayüzü (DilModeli) — llama-server üzerinden."""

    def __init__(self, sunucu: LlamaSunucusu, ad: str, dusunme_destegi: bool = False):
        self.sunucu = sunucu
        self.ad = ad
        self.dusunme_destegi = dusunme_destegi
        self.hazir = True
        self.olcum: dict = {}

    def sohbet(self, mesajlar, max_tokens=900, sicaklik=0.2, json_mod=False, json_sema=None, dusunme=False,
               akis=None) -> str:
        return self.sunucu.sohbet(mesajlar, max_tokens=max_tokens, sicaklik=sicaklik, json_sema=json_sema,
                                  json_mod=json_mod, dusunme=dusunme and self.dusunme_destegi, akis=akis)

    def hiz_olc(self) -> dict:
        """Kısa bir üretimle saniyedeki belirteç sayısını ölçer (arayüzde ve model seçiminde kullanılır)."""
        bas = time.monotonic()
        metin = self.sohbet([{"role": "user", "content": "Türkiye'nin başkenti neresidir? Tek kelimeyle yaz."}],
                            max_tokens=16, sicaklik=0)
        sure = max(0.01, time.monotonic() - bas)
        self.olcum = {"sure_sn": round(sure, 2), "cikti": metin[:40]}
        return self.olcum


def env_model_klasoru() -> str:
    return os.environ.get("AKILHOCASI_MODELLER", "")
