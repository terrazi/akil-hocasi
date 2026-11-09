"""Strateji deposu: yordam ayarlarının güncel değerleri ve gelişim geçmişi.

Ayarlar yalnızca Yordam Kitabı'nda tanımlı izinli aralıkta değişebilir. Değişikliğin kaynağı kaydedilir
(varsayılan, öğrenme, kullanıcı); kullanıcının elle verdiği ayar öğrenmeyle değiştirilmez.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import datetime

from .yordamlar import YORDAMLAR, Ayar

SEMA = """
CREATE TABLE IF NOT EXISTS cek_strateji (
    yordam TEXT NOT NULL, ayar TEXT NOT NULL, deger TEXT NOT NULL, kaynak TEXT NOT NULL,
    guncelleme TEXT NOT NULL, PRIMARY KEY (yordam, ayar)
);
CREATE TABLE IF NOT EXISTS cek_gelisim (
    id INTEGER PRIMARY KEY, zaman TEXT NOT NULL, tur TEXT NOT NULL, konu TEXT NOT NULL,
    eski TEXT DEFAULT '', yeni TEXT DEFAULT '', karar TEXT NOT NULL, gerekce TEXT DEFAULT '',
    eski_karne TEXT DEFAULT '', yeni_karne TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cek_karne (
    id INTEGER PRIMARY KEY, zaman TEXT NOT NULL, kapsam TEXT NOT NULL, karne TEXT NOT NULL
);
"""


def _ayar_tanimi(yordam: str, ayar: str) -> Ayar:
    for y in YORDAMLAR:
        if y.kod == yordam:
            for a in y.ayarlar:
                if a.ad == ayar:
                    return a
    raise KeyError(f"{yordam}.{ayar} tanımlı bir ayar değil")


def _cevir(a: Ayar, deger):
    if isinstance(a.varsayilan, bool):
        if isinstance(deger, str):
            return deger.lower() in ("1", "true", "evet", "açık", "acik")
        return bool(deger)
    if isinstance(a.varsayilan, int):
        return int(round(float(deger)))
    if isinstance(a.varsayilan, float):
        return round(float(deger), 3)
    return str(deger)


def gecerli_mi(a: Ayar, deger) -> bool:
    try:
        v = _cevir(a, deger)
    except (TypeError, ValueError):
        return False
    if a.secenekler:
        return v in a.secenekler
    if a.alt is not None and v < a.alt:
        return False
    return not (a.ust is not None and v > a.ust)


class StratejiDeposu:
    def __init__(self, kutuphane):
        self.k = kutuphane
        self._yerel = threading.local()          # geçici (sınama) ayarları yalnız sınavı yürüten iş parçacığında
        self._kilit = threading.RLock()
        with self.k._kilit, self.k.db:
            self.k.db.executescript(SEMA)

    def deger(self, yordam: str, ayar: str):
        a = _ayar_tanimi(yordam, ayar)
        gecici = getattr(self._yerel, "gecici", None)
        if gecici and (yordam, ayar) in gecici:
            return gecici[(yordam, ayar)]
        r = self.k.db.execute("SELECT deger FROM cek_strateji WHERE yordam=? AND ayar=?", (yordam, ayar)).fetchone()
        if r is None:
            return a.varsayilan
        try:
            v = _cevir(a, json.loads(r[0]))
        except (ValueError, TypeError):
            return a.varsayilan
        return v if gecerli_mi(a, v) else a.varsayilan

    def kaynak(self, yordam: str, ayar: str) -> str:
        r = self.k.db.execute("SELECT kaynak FROM cek_strateji WHERE yordam=? AND ayar=?", (yordam, ayar)).fetchone()
        return r[0] if r else "varsayilan"

    def ayarla(self, yordam: str, ayar: str, deger, kaynak: str = "ogrenme") -> None:
        a = _ayar_tanimi(yordam, ayar)
        if not gecerli_mi(a, deger):
            raise ValueError(f"{yordam}.{ayar} için izinli olmayan değer: {deger!r}")
        if kaynak == "ogrenme" and self.kaynak(yordam, ayar) == "kullanici":
            raise PermissionError("Kullanıcının elle verdiği ayar öğrenmeyle değiştirilmez")
        with self.k._kilit, self.k.db:
            self.k.db.execute(
                "INSERT INTO cek_strateji(yordam, ayar, deger, kaynak, guncelleme) VALUES(?,?,?,?,?)"
                " ON CONFLICT(yordam, ayar) DO UPDATE SET deger=excluded.deger, kaynak=excluded.kaynak,"
                " guncelleme=excluded.guncelleme",
                (yordam, ayar, json.dumps(_cevir(a, deger)), kaynak, datetime.now().isoformat(timespec="seconds")))

    @contextmanager
    def gecici(self, degisiklikler: dict[tuple[str, str], object]):
        """Sınamada geçici ayar: kalıcı depoya yazmaz, yalnız bu iş parçacığındaki cevapları etkiler."""
        for (y, ay), v in degisiklikler.items():
            if not gecerli_mi(_ayar_tanimi(y, ay), v):
                raise ValueError(f"{y}.{ay}: izinli olmayan değer {v!r}")
        onceki = getattr(self._yerel, "gecici", None) or {}
        self._yerel.gecici = {**onceki, **{k: _cevir(_ayar_tanimi(*k), v) for k, v in degisiklikler.items()}}
        try:
            yield
        finally:
            self._yerel.gecici = onceki

    def komsular(self, yordam: str, ayar: str) -> list:
        """Mevcut değerin izinli aralıktaki bir adım komşuları (strateji ayarı yalnız bunları dener)."""
        a = _ayar_tanimi(yordam, ayar)
        v = self.deger(yordam, ayar)
        if isinstance(a.varsayilan, bool):
            return [not v]
        if a.secenekler:
            i = a.secenekler.index(v) if v in a.secenekler else 0
            return [a.secenekler[j] for j in (i - 1, i + 1) if 0 <= j < len(a.secenekler)]
        alt, ust = a.alt, a.ust
        if isinstance(a.varsayilan, int):
            adim = max(1, round((ust - alt) / 6))
            adaylar = [v - adim, v + adim]
        else:
            adim = (ust - alt) / 5
            adaylar = [round(v - adim, 3), round(v + adim, 3)]
        return [x for x in adaylar if alt <= x <= ust and x != v]

    def tumu(self) -> list[dict]:
        cikti = []
        for y in YORDAMLAR:
            for a in y.ayarlar:
                cikti.append({"yordam": y.kod, "yordam_adi": y.ad, "ayar": a.ad, "aciklama": a.aciklama,
                              "deger": self.deger(y.kod, a.ad), "varsayilan": a.varsayilan,
                              "kaynak": self.kaynak(y.kod, a.ad)})
        return cikti

    # ------------------------------------------------------------------ gelişim geçmişi ve karne
    def gelisim_yaz(self, tur: str, konu: str, karar: str, gerekce: str = "", eski="", yeni="",
                    eski_karne: dict | None = None, yeni_karne: dict | None = None) -> None:
        with self.k._kilit, self.k.db:
            self.k.db.execute(
                "INSERT INTO cek_gelisim(zaman, tur, konu, eski, yeni, karar, gerekce, eski_karne, yeni_karne)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), tur, konu, json.dumps(eski, ensure_ascii=False),
                 json.dumps(yeni, ensure_ascii=False), karar, gerekce,
                 json.dumps(eski_karne or {}, ensure_ascii=False), json.dumps(yeni_karne or {}, ensure_ascii=False)))

    def gelisim_gecmisi(self, sinir: int = 100) -> list[dict]:
        return [dict(r) for r in self.k.db.execute(
            "SELECT * FROM cek_gelisim ORDER BY id DESC LIMIT ?", (sinir,)).fetchall()]

    def karne_yaz(self, kapsam: str, karne: dict) -> None:
        with self.k._kilit, self.k.db:
            self.k.db.execute("INSERT INTO cek_karne(zaman, kapsam, karne) VALUES(?,?,?)",
                              (datetime.now().isoformat(timespec="seconds"), kapsam, json.dumps(karne, ensure_ascii=False)))

    def karne_gecmisi(self, sinir: int = 60) -> list[dict]:
        return [{"zaman": r["zaman"], "kapsam": r["kapsam"], **json.loads(r["karne"])} for r in self.k.db.execute(
            "SELECT * FROM cek_karne ORDER BY id DESC LIMIT ?", (sinir,)).fetchall()]
