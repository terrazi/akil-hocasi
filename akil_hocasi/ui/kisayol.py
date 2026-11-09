"""Genel kısayol (Windows RegisterHotKey). Varsayılan Win+Shift+Y; Win+Shift+S ve Win+Shift+T ile çakışmaz.

Kısayol alınamazsa (başka program kullanıyorsa) yedek kısayol denenir; o da olmazsa
Hızlı Yakala menüden ve sistem tepsisinden kullanılabilir.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY = 0x0312
_OZEL_TUSLAR = {"PRINTSCREEN": 0x2C, "PRTSC": 0x2C, "SPACE": 0x20, "INSERT": 0x2D}


def cozumle(metin: str) -> tuple[int, int] | None:
    """'Win+Shift+Y' -> (değiştiriciler, sanal tuş kodu)."""
    mod, vk = 0, None
    for parca in [p.strip().upper() for p in metin.split("+") if p.strip()]:
        if parca in ("WIN", "WINDOWS"):
            mod |= MOD_WIN
        elif parca in ("CTRL", "CONTROL"):
            mod |= MOD_CONTROL
        elif parca == "ALT":
            mod |= MOD_ALT
        elif parca == "SHIFT":
            mod |= MOD_SHIFT
        elif len(parca) == 1 and parca.isalnum():
            vk = ord(parca)
        elif parca.startswith("F") and parca[1:].isdigit() and 1 <= int(parca[1:]) <= 24:
            vk = 0x6F + int(parca[1:])
        elif parca in _OZEL_TUSLAR:
            vk = _OZEL_TUSLAR[parca]
        else:
            return None
    return (mod, vk) if vk is not None else None


class GenelKisayol(QWidget):
    tetiklendi = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(0, 0)
        self._kayitli: list[int] = []
        self.etkin_kisayol = ""

    def kaydet(self, *adaylar: str) -> str:
        """Sırayla dener; başarılı olan kısayolu döndürür (olmazsa boş)."""
        if sys.platform != "win32":
            return ""
        import ctypes
        self.kaldir()
        hwnd = int(self.winId())
        for i, aday in enumerate(adaylar, start=1):
            c = cozumle(aday)
            if not c:
                continue
            if ctypes.windll.user32.RegisterHotKey(hwnd, i, c[0] | MOD_NOREPEAT, c[1]):
                self._kayitli.append(i)
                self.etkin_kisayol = aday
                return aday
        return ""

    def kaldir(self) -> None:
        if sys.platform != "win32":
            return
        import ctypes
        hwnd = int(self.winId())
        for i in self._kayitli:
            ctypes.windll.user32.UnregisterHotKey(hwnd, i)
        self._kayitli.clear()

    def nativeEvent(self, olay_turu, mesaj):
        if sys.platform == "win32":
            import ctypes.wintypes
            msg = ctypes.wintypes.MSG.from_address(int(mesaj))
            if msg.message == WM_HOTKEY and msg.wParam in self._kayitli:
                self.tetiklendi.emit()
                return True, 0
        return super().nativeEvent(olay_turu, mesaj)


def bosta_kalma_sn() -> float:
    """Kullanıcının klavye/fare kullanmadığı süre (Windows). Diğer sistemlerde 0."""
    if sys.platform != "win32":
        return 0.0
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0
