"""Satır içi SVG ikonlar (harici dosya gerekmez). Çizgi tarzı, 24x24 ızgara."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_YOLLAR = {
    "danisma": '<path d="M4 5h16v10H9l-5 4z"/><path d="M8 9h8M8 12h5"/>',
    "yakala": '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/>'
              '<path d="M8 10h8M8 14h5"/>',
    "yazi": '<path d="M4 20h4l10-10-4-4L4 16z"/><path d="M13 7l4 4"/>',
    "hesap": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 11h2M12 11h2M16 11h0M8 15h2M12 15h2M8 18h2M12 18h4"/>',
    "kontrol": '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2"/>',
    "depo": '<path d="M3 7a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>',
    "degisti": '<path d="M3 12h4l2-5 4 10 2-5h6"/>',
    "ayarlar": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
    "gonder": '<path d="M5 12h13M13 6l6 6-6 6"/>',
    "ek": '<path d="M16 7l-7.5 7.5a2.1 2.1 0 0 0 3 3L19 10a4 4 0 0 0-5.7-5.7L6 11.6a6 6 0 0 0 8.5 8.5L20 14.5"/>',
    "kopyala": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
    "dis": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "dosya": '<path d="M6 3h8l5 5v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v5h5"/>',
    "bayrak": '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
    "onay": '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    "uyari": '<path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17v.5"/>',
    "bilgi": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.5"/>',
    "panel": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
    "yenile": '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
    "buyut": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5M11 8v6M8 11h6"/>',
    "kucult": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5M8 11h6"/>',
    "tablo": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M10 4v16"/>',
    "kalem": '<path d="M4 20h4l10-10-4-4L4 16z"/>',
    "isik": '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.8.8 1 1.5 1 2.5h6c0-1 .2-1.7 1-2.5A6 6 0 0 0 12 3z"/>',
    "kisi": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "para": '<rect x="3" y="6" width="18" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/><path d="M6 9v.5M18 14.5v.5"/>',
    "sepet": '<path d="M3 5h2l2 11h11l2-8H6"/><circle cx="9" cy="20" r="1"/><circle cx="17" cy="20" r="1"/>',
    "zarf": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
    "kutu": '<path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M3 7l9 4 9-4M12 11v10"/>',
    "yol": '<path d="M5 20l4-16M19 20l-4-16M12 6v2M12 11v2M12 16v2"/>',
    "carpi": '<path d="M6 6l12 12M18 6L6 18"/>',
    "canli": '<circle cx="12" cy="12" r="4"/>',
    "klasor": '<path d="M3 7a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>',
    "indir": '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
}


@lru_cache(maxsize=256)
def ikon(ad: str, renk: str = "#565B76", boyut: int = 20, kalinlik: float = 1.8) -> QIcon:
    yol = _YOLLAR.get(ad, _YOLLAR["bilgi"])
    dolgu = renk if ad == "canli" else "none"
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{dolgu}" stroke="{renk}" '
           f'stroke-width="{kalinlik}" stroke-linecap="round" stroke-linejoin="round">{yol}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    simge = QIcon()
    for olcek in (1, 2):
        pm = QPixmap(boyut * olcek, boyut * olcek)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        renderer.render(p, QRectF(0, 0, boyut * olcek, boyut * olcek))
        p.end()
        pm.setDevicePixelRatio(olcek)
        simge.addPixmap(pm)
    return simge


def logo_pixmap(boyut: int = 40) -> QPixmap:
    """Gradyan daire içinde ampul: Akıl Hocası logosu."""
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">
      <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#22D3EE"/><stop offset="0.5" stop-color="#6366F1"/><stop offset="1" stop-color="#A855F7"/>
      </linearGradient></defs>
      <rect width="40" height="40" rx="12" fill="url(#g)"/>
      <g fill="none" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M16.5 27h7M17.5 30.5h5M20 9a8 8 0 0 0-5.3 14c1 1 1.3 1.9 1.3 3h8c0-1.1.3-2 1.3-3A8 8 0 0 0 20 9z"/>
        <path d="M20 14v5l3 2"/>
      </g></svg>'''
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(boyut * 2, boyut * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, boyut * 2, boyut * 2))
    p.end()
    pm.setDevicePixelRatio(2)
    return pm
