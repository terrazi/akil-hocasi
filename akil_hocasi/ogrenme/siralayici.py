"""Öğrenen sıralayıcı: program her gece kendi verisiyle kendini eğitir (işlemci, dakikalar).

Eğitim verisini kendisi toplar — hiçbiri uydurma değildir:
  1. Kütüphaneden kendi kendine üretilen çiftler: madde kenar başlığı (sorgu) → o maddenin metni (doğru cevap)
  2. Personelin "faydalı" işaretlediği cevapların kaynakları (olumlu), "yanlış" bildirilenler (olumsuz)
  3. Altın soru setindeki beklenen dayanaklar

Model: lojistik regresyon (numpy). Yeni sürüm, ayrılmış test sorularında (MRR@10) yürürlükteki
sürümden daha iyiyse devreye girer; değilse eski sürüm kalır. Böylece öğrenme hiçbir zaman geriye gitmez.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from ..core.turkce import katla
from ..library.db import _DURAK_KATLI, Kutuphane, Pasaj, _terim_kok

OZELLIKLER = ["bm25", "kapsama", "baslik_kapsama", "belge_kapsama", "sayi_eslesme", "uzunluk",
              "mevzuat", "resmi_gorus", "togu", "emsal", "yururlukte", "kaynak_puani", "sabit"]
_TURLER = {"Mevzuat": "mevzuat", "Resmî görüş": "resmi_gorus", "TOGÜ belgesi": "togu", "Emsal": "emsal"}
SEMA = """
CREATE TABLE IF NOT EXISTS ogr_model (
    id INTEGER PRIMARY KEY, ad TEXT NOT NULL, surum INTEGER NOT NULL, agirliklar TEXT NOT NULL,
    mrr REAL NOT NULL, taban_mrr REAL NOT NULL, ornek_sayisi INTEGER NOT NULL, zaman TEXT NOT NULL,
    aktif INTEGER DEFAULT 0, not_ TEXT DEFAULT ''
);
"""


def _terimler(metin: str) -> list[str]:
    return [_terim_kok(t) for t in re.findall(r"[a-z0-9]+", katla(metin)) if len(t) >= 3 and t not in _DURAK_KATLI]


def _kapsama(terimler: list[str], hedef: str) -> float:
    if not terimler:
        return 0.0
    h = katla(hedef)
    return sum(1 for t in terimler if t in h) / len(terimler)


@dataclass
class EgitimRaporu:
    ornek: int
    sorgu: int
    yeni_mrr: float
    eski_mrr: float
    taban_mrr: float
    devreye_girdi: bool
    surum: int

    @property
    def ozet(self) -> str:
        karar = "devreye girdi" if self.devreye_girdi else "eski sürüm korundu"
        return (f"Sıralayıcı v{self.surum}: {self.sorgu} sorgu, {self.ornek} örnek; MRR yeni {self.yeni_mrr:.3f}, "
                f"yürürlükteki {self.eski_mrr:.3f}, taban {self.taban_mrr:.3f} → {karar}")


class OgrenenSiralayici:
    def __init__(self, kutuphane: Kutuphane, ogrenme=None):
        self.k = kutuphane
        self.ogrenme = ogrenme
        self._kilit = threading.RLock()
        with self._kilit, self.k.db:
            self.k.db.executescript(SEMA)
        self.agirlik: np.ndarray | None = None
        self.surum = 0
        self._yukle()

    # ---------------------------------------------------------------- model kaydı
    def _yukle(self) -> None:
        r = self.k.db.execute("SELECT * FROM ogr_model WHERE ad='siralayici' AND aktif=1 ORDER BY id DESC LIMIT 1").fetchone()
        if r:
            self.agirlik = np.array(json.loads(r["agirliklar"]), dtype=float)
            self.surum = r["surum"]

    @property
    def aktif(self) -> bool:
        return self.agirlik is not None

    # ---------------------------------------------------------------- özellikler
    def ozellikler(self, soru: str, p: Pasaj, terimler: list[str] | None = None) -> np.ndarray:
        terimler = terimler if terimler is not None else _terimler(soru)
        sayilar = set(re.findall(r"\d+", soru))
        v = dict.fromkeys(OZELLIKLER, 0.0)
        v["bm25"] = math.log1p(max(p.skor, 0.0)) if p.skor < 50 else math.log1p(10.0)
        v["kapsama"] = _kapsama(terimler, p.baslik + " " + p.metin)
        v["baslik_kapsama"] = _kapsama(terimler, p.baslik)
        v["belge_kapsama"] = _kapsama(terimler, p.belge_baslik)
        v["sayi_eslesme"] = (sum(1 for s in sayilar if s in p.metin or s == p.belge_kimlik or s == p.madde_no)
                             / len(sayilar)) if sayilar else 0.0
        v["uzunluk"] = math.log1p(len(p.metin)) / 8.0
        tur = _TURLER.get(p.kaynak_turu)
        if tur:
            v[tur] = 1.0
        v["yururlukte"] = 1.0 if p.yururlukte and not p.mulga else 0.0
        if self.ogrenme is not None:
            puan = self.ogrenme.kaynak_puani(p.belge_kimlik, p.madde_no)
            v["kaynak_puani"] = math.copysign(math.log1p(abs(puan)), puan)
        v["sabit"] = 1.0
        return np.array([v[o] for o in OZELLIKLER], dtype=float)

    def olasilik(self, soru: str, p: Pasaj, agirlik: np.ndarray | None = None) -> float:
        w = self.agirlik if agirlik is None else agirlik
        z = float(self.ozellikler(soru, p) @ w)
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))

    def uygula(self, soru: str, pasajlar: list[Pasaj]) -> None:
        """Aday maddeleri öğrenilmiş modele göre yeniden puanlar (onaylı kart dayanakları dokunulmaz)."""
        if not self.aktif:
            return
        terimler = _terimler(soru)
        for p in pasajlar:
            if p.skor >= 50:
                continue
            z = float(self.ozellikler(soru, p, terimler) @ self.agirlik)
            p.skor = 10.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z)))) + 0.05 * p.skor

    # ---------------------------------------------------------------- veri toplama
    def _sorgu_gruplari(self, en_fazla_madde: int = 600) -> list[tuple[str, set[str], str]]:
        """(sorgu, doğru madde anahtarları, bölüm) — bölüm: 'egitim' veya 'test'."""
        gruplar: list[tuple[str, set[str], str]] = []

        def bolum(anahtar: str) -> str:
            return "test" if int(hashlib.md5(anahtar.encode()).hexdigest(), 16) % 5 == 0 else "egitim"

        # 1) Kütüphaneden kendi kendine: kenar başlığı → madde
        for r in self.k.db.execute(
                "SELECT m.id, m.baslik, m.madde_no, b.kimlik FROM maddeler m JOIN belgeler b ON b.id=m.belge_id"
                " WHERE m.yururluk_bitis IS NULL AND length(m.baslik) >= 4 ORDER BY m.id LIMIT ?", (en_fazla_madde,)):
            anahtar = f"{r['kimlik']}/{r['madde_no']}"
            gruplar.append((r["baslik"], {anahtar}, bolum(anahtar)))
        # 2) Geri bildirimler
        if self.ogrenme is not None:
            for r in self.k.db.execute("SELECT soru, kaynaklar, geri_bildirim FROM ogr_olaylar WHERE geri_bildirim>0"):
                dogru = set(json.loads(r["kaynaklar"])[:2])
                if dogru:
                    gruplar.append((r["soru"], dogru, bolum(r["soru"])))
            # 3) Altın set: her zaman test bölümünde (ölçüt)
            for r in self.k.db.execute("SELECT soru, beklenen_dayanak FROM ogr_altin"):
                dogru = set(json.loads(r["beklenen_dayanak"] or "[]"))
                if dogru:
                    gruplar.append((r["soru"], dogru, "test"))
        # 4) Programın kendi ürettiği ve doğruladığı sorular (yalnız eğitim payı; sınav payı ayrı kalır)
        try:
            for r in self.k.db.execute("SELECT soru, dayanak FROM yz_sentetik WHERE durum='dogrulandi'"
                                       " AND kullanim='egitim' ORDER BY id DESC LIMIT 800"):
                dogru = set(json.loads(r["dayanak"] or "[]"))
                if dogru:
                    gruplar.append((r["soru"], dogru, bolum(r["soru"])))
        except Exception:  # noqa: BLE001 - sentetik tablo henüz yoksa
            pass
        return gruplar

    def _adaylar(self, sorgu: str, dogru: set[str]) -> list[tuple[Pasaj, int]]:
        adaylar = self.k.ara(sorgu, limit=10)
        anahtarlar = {f"{p.belge_kimlik}/{p.madde_no}" for p in adaylar}
        for d in dogru - anahtarlar:      # doğru madde aramada çıkmadıysa da öğrenmeye katılır
            kimlik, _, no = d.rpartition("/")
            p = self.k.madde_getir(kimlik, no)
            if p:
                adaylar.append(p)
                anahtarlar.add(d)
        # Aday az ise aynı belgenin başka maddeleri gerçek olumsuz örnek olarak eklenir
        if len(adaylar) < 5 and dogru:
            kimlik = next(iter(dogru)).rpartition("/")[0]
            for r in self.k.db.execute(
                    "SELECT m.id FROM maddeler m JOIN belgeler b ON b.id=m.belge_id WHERE b.kimlik=?"
                    " AND m.yururluk_bitis IS NULL ORDER BY (m.id * 7919) % 101 LIMIT 12", (kimlik,)):
                if len(adaylar) >= 5:
                    break
                p = self.k._pasaj(r["id"])
                if p and f"{p.belge_kimlik}/{p.madde_no}" not in anahtarlar:
                    adaylar.append(p)
                    anahtarlar.add(f"{p.belge_kimlik}/{p.madde_no}")
        return [(p, 1 if f"{p.belge_kimlik}/{p.madde_no}" in dogru else 0) for p in adaylar]

    # ---------------------------------------------------------------- değerlendirme
    @staticmethod
    def _mrr(gruplar_adaylar, puanla) -> float:
        toplam, n = 0.0, 0
        for sorgu, adaylar in gruplar_adaylar:
            if not any(y for _, y in adaylar):
                continue
            sirali = sorted(adaylar, key=lambda a: -puanla(sorgu, a[0]))
            for i, (_, y) in enumerate(sirali[:10], 1):
                if y:
                    toplam += 1.0 / i
                    break
            n += 1
        return toplam / n if n else 0.0

    # ---------------------------------------------------------------- eğitim
    def egit(self, adim: int = 400, ogrenme_hizi: float = 0.3, l2: float = 0.01) -> EgitimRaporu | None:
        """Gece görevi: veriyi toplar, modeli eğitir, testte daha iyiyse devreye alır."""
        gruplar = self._sorgu_gruplari()
        if len(gruplar) < 10:
            return None
        egitim, test = [], []
        for sorgu, dogru, b in gruplar:
            adaylar = self._adaylar(sorgu, dogru)
            if len(adaylar) < 2 or not any(y for _, y in adaylar):
                continue
            (test if b == "test" else egitim).append((sorgu, adaylar))
        if not egitim or not test:
            return None

        X, y, agirlik = [], [], []
        for sorgu, adaylar in egitim:
            terimler = _terimler(sorgu)
            pozitif = sum(yy for _, yy in adaylar)
            for p, yy in adaylar:
                X.append(self.ozellikler(sorgu, p, terimler))
                y.append(yy)
                agirlik.append(1.0 if yy else pozitif / max(1, len(adaylar) - pozitif))  # sınıf dengesi
        X, y, s = np.array(X), np.array(y, dtype=float), np.array(agirlik)
        w = np.zeros(X.shape[1])
        for _ in range(adim):
            tahmin = 1.0 / (1.0 + np.exp(-np.clip(X @ w, -30, 30)))
            egim = X.T @ ((tahmin - y) * s) / s.sum() + l2 * w
            w -= ogrenme_hizi * egim

        yeni = self._mrr(test, lambda q, p: self.olasilik(q, p, w))
        taban = self._mrr(test, lambda q, p: p.skor)
        eski = self._mrr(test, lambda q, p: self.olasilik(q, p)) if self.aktif else taban
        devreye = yeni >= max(eski, taban) + 0.005 or (not self.aktif and yeni > taban)
        surum = (self.k.db.execute("SELECT MAX(surum) FROM ogr_model WHERE ad='siralayici'").fetchone()[0] or 0) + 1
        with self._kilit, self.k.db:
            if devreye:
                self.k.db.execute("UPDATE ogr_model SET aktif=0 WHERE ad='siralayici'")
            self.k.db.execute(
                "INSERT INTO ogr_model(ad, surum, agirliklar, mrr, taban_mrr, ornek_sayisi, zaman, aktif)"
                " VALUES('siralayici',?,?,?,?,?,?,?)",
                (surum, json.dumps(w.round(5).tolist()), yeni, taban, len(y),
                 datetime.now().isoformat(timespec="seconds"), int(devreye)))
        if devreye:
            self.agirlik, self.surum = w, surum
        return EgitimRaporu(len(y), len(egitim) + len(test), yeni, eski, taban, devreye, surum)

    def gecmis(self, adet: int = 10) -> list[dict]:
        return [dict(r) for r in self.k.db.execute(
            "SELECT surum, mrr, taban_mrr, ornek_sayisi, zaman, aktif FROM ogr_model WHERE ad='siralayici'"
            " ORDER BY id DESC LIMIT ?", (adet,))]
