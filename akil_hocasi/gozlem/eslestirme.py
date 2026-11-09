"""Eklenti ile programın kendiliğinden eşleşmesi (Chrome/Edge yerel mesajlaşma, "native messaging").

Kurulum, tarayıcıya "com.akilhocasi.gozlemci" adlı yerel köprüyü kaydeder (yalnız bu kullanıcı, yönetici
yetkisi gerekmez). Tarayıcı bu köprüyü yalnızca kimliği allowed_origins'te yazan Akıl Hocası Gözlemci eklentisi
için çalıştırır. Eklenti köprüye "eşleştir" der; köprü bu bilgisayardaki ayarlardan bağlantı noktasını ve
eşleştirme anahtarını okuyup döndürür, program kapalıysa tepside başlatır. Kullanıcı anahtar kopyalamaz.

Bu modül yalnız standart kütüphaneyi ve config'i kullanır: köprü exe'si küçük ve hızlı kalır.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import struct
import subprocess
import sys
from pathlib import Path

ANA_BILGISAYAR_ADI = "com.akilhocasi.gozlemci"
EKLENTI_KIMLIGI = "bomcdbbmmjdekjbldmgmoekhcagaidea"      # manifest.json "key" alanından türetilir (testle denetlenir)
VARSAYILAN_PORT = 47231
KOPRU_EXE = "AkilHocasiKopru.exe"
UYGULAMA_EXE = "AkilHocasi.exe"
KAYIT_YOLLARI = {
    "Chrome": r"Software\Google\Chrome\NativeMessagingHosts",
    "Edge": r"Software\Microsoft\Edge\NativeMessagingHosts",
    "Chromium": r"Software\Chromium\NativeMessagingHosts",
}
EN_BUYUK_ILETI = 1024 * 1024


def yeni_anahtar() -> str:
    return secrets.token_urlsafe(24)


def anahtari_hazirla(ayarlar) -> str:
    """Eşleştirme anahtarı yoksa üretir ve kaydeder."""
    anahtar = ayarlar.al("gozlem.anahtar", "")
    if not anahtar:
        anahtar = yeni_anahtar()
        ayarlar.ayarla("gozlem.anahtar", anahtar)
        if not ayarlar.al("gozlem.port"):
            ayarlar.ayarla("gozlem.port", VARSAYILAN_PORT)
        ayarlar.kaydet()
    return anahtar


# ----------------------------------------------------------------- ileti çerçevesi (4 bayt uzunluk + JSON)
def ileti_oku(akis) -> dict | None:
    bas = akis.read(4)
    if len(bas) < 4:
        return None
    n = struct.unpack("<I", bas)[0]
    if n > EN_BUYUK_ILETI:
        raise ValueError("ileti çok büyük")
    veri = akis.read(n)
    return json.loads(veri.decode("utf-8"))


def ileti_yaz(akis, ileti: dict) -> None:
    veri = json.dumps(ileti, ensure_ascii=False).encode("utf-8")
    akis.write(struct.pack("<I", len(veri)) + veri)
    akis.flush()


# ----------------------------------------------------------------- köprü
def uygulama_acik_mi(port: int, zaman_asimi: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=zaman_asimi):
            return True
    except OSError:
        return False


def _uygulamayi_baslat() -> bool:
    exe = Path(sys.executable).with_name(UYGULAMA_EXE) if getattr(sys, "frozen", False) else None
    if not exe or not exe.is_file():
        return False
    bayrak = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(exe), "--tepside"], close_fds=True, creationflags=bayrak,  # noqa: S603 - kendi programımız
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def yanit_hazirla(ileti: dict, kaynak: str, ayarlar) -> dict:
    """Köprünün bir iletiye cevabı (saf işlev: testler doğrudan çağırır)."""
    from .. import __version__
    beklenen = f"chrome-extension://{EKLENTI_KIMLIGI}/"
    if kaynak and kaynak != beklenen:
        return {"ok": False, "hata": "tanınmayan eklenti"}
    if not isinstance(ileti, dict) or ileti.get("tur") != "eslestir":
        return {"ok": False, "hata": "bilinmeyen istek"}
    if not ayarlar.al("gozlem.acik", True):
        return {"ok": False, "hata": "Akıl Hocası'nda tarayıcı gözlemcisi kapalı"}
    anahtar = anahtari_hazirla(ayarlar)
    port = int(ayarlar.al("gozlem.port", VARSAYILAN_PORT))
    acik = uygulama_acik_mi(port)
    baslatildi = False
    if not acik and ileti.get("baslat"):
        baslatildi = _uygulamayi_baslat()
    return {"ok": True, "port": port, "anahtar": anahtar, "surum": __version__,
            "uygulama_acik": acik, "baslatildi": baslatildi}


def kopru_main(argv: list[str] | None = None) -> int:
    """Tarayıcının çalıştırdığı köprü: stdin'den ileti okur, stdout'a cevap yazar."""
    from ..config import Ayarlar, Yollar, veri_klasoru
    argv = sys.argv if argv is None else argv
    kaynak = next((a for a in argv[1:] if a.startswith("chrome-extension://")), "")
    giris, cikis = sys.stdin.buffer, sys.stdout.buffer
    yollar = Yollar(veri_klasoru()).olustur()
    while True:
        try:
            ileti = ileti_oku(giris)
        except (ValueError, OSError):
            return 1
        if ileti is None:
            return 0
        ileti_yaz(cikis, yanit_hazirla(ileti, kaynak, Ayarlar(yollar.ayarlar)))


# ----------------------------------------------------------------- tarayıcıya kayıt
def ana_bilgisayar_bildirimi(kopru_yolu: str) -> dict:
    return {"name": ANA_BILGISAYAR_ADI, "description": "Akıl Hocası Gözlemci köprüsü (yerel eşleşme)",
            "path": kopru_yolu, "type": "stdio", "allowed_origins": [f"chrome-extension://{EKLENTI_KIMLIGI}/"]}


def yerel_mesajlasma_kaydet(veri_koku: Path, kopru_yolu: str | None = None) -> list[str]:
    """Köprüyü Chrome, Edge ve Chromium'a bu kullanıcı için kaydeder (HKCU). Kaydedilen tarayıcıları döndürür."""
    if sys.platform != "win32":
        return []
    kopru = kopru_yolu or str(Path(sys.executable).with_name(KOPRU_EXE))
    if not Path(kopru).is_file():
        return []
    klasor = veri_koku / "kopru"
    klasor.mkdir(parents=True, exist_ok=True)
    bildirim = klasor / f"{ANA_BILGISAYAR_ADI}.json"
    yeni = json.dumps(ana_bilgisayar_bildirimi(kopru), ensure_ascii=False, indent=2)
    if not bildirim.is_file() or bildirim.read_text(encoding="utf-8") != yeni:
        bildirim.write_text(yeni, encoding="utf-8")
    import winreg
    kaydedilen = []
    for tarayici, yol in KAYIT_YOLLARI.items():
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{yol}\{ANA_BILGISAYAR_ADI}") as a:
                winreg.SetValueEx(a, "", 0, winreg.REG_SZ, str(bildirim))
            kaydedilen.append(tarayici)
        except OSError:
            continue
    return kaydedilen


def yerel_mesajlasma_durumu() -> dict[str, bool]:
    if sys.platform != "win32":
        return {}
    import winreg
    durum = {}
    for tarayici, yol in KAYIT_YOLLARI.items():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{yol}\{ANA_BILGISAYAR_ADI}") as a:
                durum[tarayici] = Path(winreg.QueryValue(a, None)).is_file()
        except OSError:
            durum[tarayici] = False
    return durum


if __name__ == "__main__":  # pragma: no cover
    os._exit(kopru_main())
