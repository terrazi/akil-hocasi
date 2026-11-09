"""Donanım bilgisi: bellek, işlemci çekirdekleri, güç durumu (model seçimi ve kibar arka plan çalışması için)."""

from __future__ import annotations

import os
import sys


def bellek_gb() -> tuple[float, float]:
    """(toplam, boş) fiziksel bellek, GB."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MEMORYSTATUSEX()
            m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 1024 ** 3, m.ullAvailPhys / 1024 ** 3
        toplam = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
        bos = toplam
        try:
            with open("/proc/meminfo", encoding="ascii") as f:
                for satir in f:
                    if satir.startswith("MemAvailable:"):
                        bos = int(satir.split()[1]) / 1024 ** 2
                        break
        except OSError:
            pass
        return toplam, bos
    except (OSError, ValueError, AttributeError):
        return 0.0, 0.0


def is_parcacigi_sayisi() -> int:
    """Model için iş parçacığı: fiziksel çekirdek sayısına yakın, arayüze bir çekirdek bırakır."""
    mantiksal = os.cpu_count() or 4
    fiziksel = max(1, mantiksal // 2) if mantiksal >= 4 else mantiksal
    return max(1, min(fiziksel, mantiksal - 1, 16))


def prizde_mi() -> bool | None:
    """Dizüstü bilgisayar pilde mi? (None: bilinmiyor / masaüstü)"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                        ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                        ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
        d = SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(d)):
            return None
        return {0: False, 1: True}.get(d.ACLineStatus)
    except (OSError, AttributeError):
        return None


def ozet() -> dict:
    toplam, bos = bellek_gb()
    return {"bellek_gb": round(toplam, 1), "bos_bellek_gb": round(bos, 1), "cekirdek": os.cpu_count() or 0,
            "is_parcacigi": is_parcacigi_sayisi(), "prizde": prizde_mi()}
