"""Görsel tema: renk paleti, yazı tipi ve Qt stil sayfası (QSS).

Modern, renkli ve sade: koyu indigo menü şeridi, açık zemin, beyaz kartlar,
kategori başına canlı vurgu renkleri, yumuşak köşeler.
"""

from __future__ import annotations

R = {
    # zemin ve yüzeyler
    "zemin": "#F4F5FB",
    "yuzey": "#FFFFFF",
    "yuzey2": "#F8F9FD",
    "cizgi": "#E5E7F0",
    "cizgi2": "#D6D9E6",
    # metin
    "metin": "#1E2140",
    "metin2": "#565B76",
    "soluk": "#6B7088",
    # ana renk ve geçişler
    "ana": "#4F46E5",
    "ana_koyu": "#4338CA",
    "ana_acik": "#EEF0FF",
    "mor": "#8B5CF6",
    "camgobegi": "#22D3EE",
    "serit_ust": "#2E2A78",
    "serit_alt": "#4338CA",
    # kategori vurguları
    "personel": "#4338CA",
    "maas": "#0369A1",
    "satinalma": "#C2410C",
    "yazisma": "#BE185D",
    "tasinir": "#047857",
    "harcirah": "#6D28D9",
    # durumlar
    "yesil": "#15803D", "yesil_zemin": "#DCFCE7",
    "sari": "#B45309", "sari_zemin": "#FEF3C7",
    "gri": "#475569", "gri_zemin": "#E2E8F0",
    "kirmizi": "#B91C1C", "kirmizi_zemin": "#FEE2E2",
}

DURUM_RENK = {
    "Doğrulandı": (R["yesil"], R["yesil_zemin"]),
    "Çelişkili": (R["sari"], R["sari_zemin"]),
    "Doğrudan hüküm yok": (R["gri"], R["gri_zemin"]),
}

KAYNAK_TURU_RENK = {
    "Mevzuat": R["ana"],
    "Resmî görüş": R["maas"],
    "TOGÜ belgesi": R["tasinir"],
    "Emsal": R["harcirah"],
    "Yönlendirme": R["soluk"],
}

YAZI_TIPI = '"Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", sans-serif'


def stil_sayfasi() -> str:
    return f"""
* {{ font-family: {YAZI_TIPI}; color: {R['metin']}; }}
QMainWindow, #Icerik {{ background: {R['zemin']}; }}
QToolTip {{ background: {R['metin']}; color: white; border: none; padding: 6px 8px; border-radius: 6px; }}

/* ---------- sol menü şeridi ---------- */
#Serit {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {R['serit_ust']}, stop:1 {R['serit_alt']});
}}
#Serit QLabel#Logo {{ color: white; font-size: 11px; font-weight: 600; }}
#SeritDugme {{
    background: transparent; border: none; border-radius: 12px; color: rgba(255,255,255,0.78);
    font-size: 10.5px; padding: 8px 2px 6px 2px; text-align: center;
}}
#SeritDugme:hover {{ background: rgba(255,255,255,0.10); color: white; }}
#SeritDugme:checked {{ background: rgba(255,255,255,0.18); color: white; font-weight: 600; }}

/* ---------- kartlar ---------- */
#Kart, #CevapKarti, #Besteci, #KaynakKarti, #AyarKart {{
    background: {R['yuzey']}; border: 1px solid {R['cizgi']}; border-radius: 16px;
}}
#KaynakKarti[vurgulu="true"] {{ border: 2px solid {R['ana']}; background: {R['ana_acik']}; }}
#OneriKarti {{
    background: {R['yuzey']}; border: 1px solid {R['cizgi']}; border-radius: 16px; text-align: left;
}}
#OneriKarti:hover {{ border: 1px solid {R['ana']}; background: {R['ana_acik']}; }}

/* ---------- başlıklar ---------- */
#Selam {{ font-size: 30px; font-weight: 700; }}
#AltSelam {{ font-size: 14.5px; color: {R['metin2']}; }}
#SayfaBaslik {{ font-size: 22px; font-weight: 700; }}
#BolumBaslik {{ font-size: 12px; font-weight: 700; color: {R['soluk']}; letter-spacing: 0.6px; }}
#Ikincil {{ color: {R['metin2']}; }}
#Soluk {{ color: {R['soluk']}; font-size: 12px; }}

/* ---------- kullanıcı balonu ---------- */
#KullaniciBalonu {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {R['ana']}, stop:1 {R['mor']});
    border-radius: 18px; border-bottom-right-radius: 6px;
}}
#KullaniciBalonu QLabel {{ color: white; font-size: 14px; }}

/* ---------- metin girişi ---------- */
#Besteci QPlainTextEdit {{ border: none; background: transparent; font-size: 14.5px; padding: 4px; }}
QLineEdit, QPlainTextEdit#Duz, QComboBox, QSpinBox, QTimeEdit {{
    background: {R['yuzey']}; border: 1px solid {R['cizgi2']}; border-radius: 10px; padding: 7px 10px;
    selection-background-color: {R['ana']};
}}
QLineEdit:focus, QPlainTextEdit#Duz:focus, QComboBox:focus, QTimeEdit:focus {{ border: 1px solid {R['ana']}; }}

/* ---------- düğmeler ---------- */
QPushButton {{
    background: {R['yuzey']}; border: 1px solid {R['cizgi2']}; border-radius: 10px;
    padding: 7px 14px; font-weight: 600; color: {R['metin']};
}}
QPushButton:hover {{ border-color: {R['ana']}; color: {R['ana']}; }}
QPushButton:disabled {{ color: {R['soluk']}; border-color: {R['cizgi']}; }}
QPushButton#Birincil {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {R['ana']}, stop:1 {R['mor']});
    color: white; border: none;
}}
QPushButton#Birincil:hover {{ background: {R['ana_koyu']}; color: white; }}
QPushButton#Gonder {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {R['ana']}, stop:1 {R['mor']});
    border: none; border-radius: 20px; min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px;
}}
QPushButton#Gonder:disabled {{ background: {R['cizgi2']}; }}
QPushButton#Hayalet, QToolButton#Hayalet {{
    background: transparent; border: none; color: {R['metin2']}; padding: 6px 10px; border-radius: 10px;
}}
QPushButton#Hayalet:hover, QToolButton#Hayalet:hover {{ background: {R['ana_acik']}; color: {R['ana']}; }}
QPushButton#Segment {{
    background: transparent; border: none; border-radius: 8px; padding: 5px 12px; color: {R['metin2']};
    font-weight: 600; font-size: 12.5px;
}}
QPushButton#Segment:checked {{ background: {R['yuzey']}; color: {R['ana']}; }}
#SegmentKap {{ background: {R['zemin']}; border-radius: 10px; }}
QPushButton#BelgeCipi {{
    background: {R['yuzey2']}; border: 1px solid {R['cizgi']}; border-radius: 10px; padding: 6px 12px;
    font-weight: 600; font-size: 12.5px; text-align: left;
}}
QPushButton#BelgeCipi:hover {{ border-color: {R['tasinir']}; color: {R['tasinir']}; }}

/* ---------- ilerleme ---------- */
QProgressBar {{ background: {R['ana_acik']}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{
    border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {R['ana']}, stop:1 {R['camgobegi']});
}}

/* ---------- kaydırma çubukları ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {R['cizgi2']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {R['soluk']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {R['cizgi2']}; border-radius: 4px; min-width: 30px; }}

/* ---------- tablo ---------- */
QTableWidget {{
    background: {R['yuzey']}; border: 1px solid {R['cizgi']}; border-radius: 14px; gridline-color: transparent;
    alternate-background-color: {R['yuzey2']}; selection-background-color: {R['ana_acik']}; selection-color: {R['metin']};
}}
QHeaderView::section {{
    background: {R['yuzey']}; border: none; border-bottom: 1px solid {R['cizgi']}; padding: 8px;
    font-weight: 700; color: {R['metin2']};
}}

/* ---------- durum çubuğu ---------- */
#DurumCubugu {{ background: {R['yuzey']}; border-top: 1px solid {R['cizgi']}; }}
#DurumCubugu QLabel {{ color: {R['metin2']}; font-size: 12px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {R['cizgi2']}; background: white; }}
QCheckBox::indicator:checked {{ background: {R['ana']}; border-color: {R['ana']}; }}
QMenu {{ background: white; border: 1px solid {R['cizgi']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {R['ana_acik']}; color: {R['ana']}; }}
"""


def cip_html(metin: str, renk: str, zemin: str | None = None) -> str:
    if zemin is None:
        r, g, b = int(renk[1:3], 16), int(renk[3:5], 16), int(renk[5:7], 16)
        zemin = f"rgba({r},{g},{b},0.12)"
    return (f"<span style='background:{zemin}; color:{renk}; font-weight:600; "
            f"border-radius:8px; padding:2px 8px;'>&nbsp;{metin}&nbsp;</span>")
