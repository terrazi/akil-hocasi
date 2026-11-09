"""Görüntü iyileştirme (OpenCV): eğiklik, perspektif, gölge, kontrast, keskinlik, büyütme.

Her fonksiyon numpy dizisi alır ve döndürür. iyilestir() kutuların orijinal görüntüye geri
eşlenebilmesi için uygulanan ölçek katsayısını da döndürür.
"""

from __future__ import annotations

import cv2
import numpy as np

HEDEF_HARF_YUKSEKLIGI = 26    # piksel; OCR motorları 20-30 px harf yüksekliğinde en iyi okur


def gri(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def harf_yuksekligi(g: np.ndarray) -> float:
    """Bağlı bileşenlerin ortanca yüksekliğinden yaklaşık harf yüksekliği."""
    _, ikili = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, _, istat, _ = cv2.connectedComponentsWithStats(ikili, connectivity=8)
    if n <= 1:
        return 0.0
    yuks = istat[1:, cv2.CC_STAT_HEIGHT]
    gen = istat[1:, cv2.CC_STAT_WIDTH]
    alan = istat[1:, cv2.CC_STAT_AREA]
    secim = (yuks >= 4) & (yuks <= g.shape[0] * 0.5) & (gen <= g.shape[1] * 0.5) & (alan >= 8)
    if not secim.any():
        return 0.0
    return float(np.median(yuks[secim]))


def olcekle(g: np.ndarray, hedef: int = HEDEF_HARF_YUKSEKLIGI) -> tuple[np.ndarray, float]:
    h = harf_yuksekligi(g)
    if h <= 0:
        return g, 1.0
    kat = float(np.clip(hedef / h, 0.5, 4.0))
    if 0.85 <= kat <= 1.15:
        return g, 1.0
    yontem = cv2.INTER_CUBIC if kat > 1 else cv2.INTER_AREA
    return cv2.resize(g, None, fx=kat, fy=kat, interpolation=yontem), kat


def golge_gider(g: np.ndarray) -> np.ndarray:
    arka = cv2.medianBlur(cv2.dilate(g, np.ones((7, 7), np.uint8)), 21)
    fark = 255 - cv2.absdiff(g, arka)
    return cv2.normalize(fark, None, 0, 255, cv2.NORM_MINMAX)


def kontrast(g: np.ndarray) -> np.ndarray:
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)


def keskinlestir(g: np.ndarray, miktar: float = 1.0) -> np.ndarray:
    bulanik = cv2.GaussianBlur(g, (0, 0), 1.2)
    return cv2.addWeighted(g, 1 + miktar, bulanik, -miktar, 0)


def ikilestir(g: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)


def egiklik_aci(g: np.ndarray) -> float:
    _, ikili = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    noktalar = np.column_stack(np.where(ikili > 0))
    if len(noktalar) < 50:
        return 0.0
    aci = cv2.minAreaRect(noktalar[:, ::-1].astype(np.float32))[-1]
    if aci > 45:
        aci -= 90
    if aci < -45:
        aci += 90
    return float(aci) if abs(aci) <= 15 else 0.0


def egiklik_duzelt(g: np.ndarray) -> np.ndarray:
    aci = egiklik_aci(g)
    if abs(aci) < 0.3:
        return g
    h, w = g.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), aci, 1.0)
    return cv2.warpAffine(g, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def perspektif_duzelt(img: np.ndarray) -> np.ndarray:
    """Telefonla çekilmiş belgede kâğıdın dört köşesini bulup düzler; bulamazsa aynen döner."""
    g = gri(img)
    kenar = cv2.Canny(cv2.GaussianBlur(g, (5, 5), 0), 50, 150)
    konturlar, _ = cv2.findContours(kenar, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    alan_esik = g.shape[0] * g.shape[1] * 0.3
    for k in sorted(konturlar, key=cv2.contourArea, reverse=True)[:5]:
        yaklasik = cv2.approxPolyDP(k, 0.02 * cv2.arcLength(k, True), True)
        if len(yaklasik) == 4 and cv2.contourArea(yaklasik) > alan_esik:
            p = yaklasik.reshape(4, 2).astype(np.float32)
            t = p.sum(1)
            f = np.diff(p, axis=1).ravel()
            sirali = np.array([p[t.argmin()], p[f.argmin()], p[t.argmax()], p[f.argmax()]], np.float32)
            gen = int(max(np.linalg.norm(sirali[0] - sirali[1]), np.linalg.norm(sirali[3] - sirali[2])))
            yuk = int(max(np.linalg.norm(sirali[0] - sirali[3]), np.linalg.norm(sirali[1] - sirali[2])))
            hedef = np.array([[0, 0], [gen - 1, 0], [gen - 1, yuk - 1], [0, yuk - 1]], np.float32)
            return cv2.warpPerspective(img, cv2.getPerspectiveTransform(sirali, hedef), (gen, yuk))
    return img


def iyilestir(img: np.ndarray, seviye: int = 1) -> tuple[np.ndarray, float]:
    """seviye 0: yalnız gri + ölçek; 1: + kontrast, keskinlik (ekran görüntüsü);
    2: + gölge, eğiklik (taranmış/foto belge); 3: + ikili görüntü (çok kötü kalite).
    Dönüş: (işlenmiş gri görüntü, ölçek katsayısı)."""
    g = gri(img)
    if seviye >= 2:
        g = golge_gider(g)
        g = egiklik_duzelt(g)
    g, kat = olcekle(g)
    if seviye >= 1:
        g = kontrast(g)
        g = keskinlestir(g, 0.6 if seviye == 1 else 1.0)
    if seviye >= 3:
        g = ikilestir(g)
    # Motorların kenara yapışık metni kaçırmaması için beyaz çerçeve
    g = cv2.copyMakeBorder(g, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255 if np.mean(g) > 127 else 0)
    return g, kat
