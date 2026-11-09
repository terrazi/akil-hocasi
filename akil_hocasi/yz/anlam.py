"""Anlam dizini: kütüphanedeki maddelerin anlam vektörleri ve anlamsal arama.

Kelime araması "ücretsiz izin" ile "aylıksız izin"i ancak eş anlamlı sözlüğüyle eşleştirebilir; anlam araması
ise soru farklı kelimelerle sorulsa da ilgili maddeyi bulur. Vektörler yerel anlam modeliyle (Qwen3 Embedding)
üretilir ve SQLite'ta float16 olarak saklanır; değişen maddeler (sha) yeniden vektörlenir.
"""

from __future__ import annotations

import hashlib
import threading

import numpy as np

SEMA = """
CREATE TABLE IF NOT EXISTS yz_anlam (
    madde_id INTEGER PRIMARY KEY, model TEXT NOT NULL, sha TEXT NOT NULL, vektor BLOB NOT NULL
);
"""
VARSAYILAN_TALIMAT = ("Given a question from a Turkish public university administrative employee, retrieve the "
                      "legislation articles that answer it")


def madde_metni(baslik: str, belge: str, madde_no: str, metin: str) -> str:
    return f"{belge} — madde {madde_no}" + (f" ({baslik})" if baslik else "") + f"\n{metin[:2400]}"


class AnlamDizini:
    def __init__(self, kutuphane, sunucu=None, model_kimlik: str = "", talimat: str = VARSAYILAN_TALIMAT):
        self.k = kutuphane
        self.sunucu = sunucu
        self.model_kimlik = model_kimlik
        self.talimat = talimat
        self._kilit = threading.RLock()
        self._matris: np.ndarray | None = None
        self._kimlikler: np.ndarray | None = None
        self._surum = -1
        with self.k._kilit, self.k.db:
            self.k.db.executescript(SEMA)

    @property
    def hazir(self) -> bool:
        return self.sunucu is not None and self.sunucu.calisiyor()

    def baglan(self, sunucu, model_kimlik: str, talimat: str = "") -> None:
        with self._kilit:
            self.sunucu, self.model_kimlik = sunucu, model_kimlik
            if talimat:
                self.talimat = talimat
            self._matris = None

    def ilerleme(self) -> tuple[int, int]:
        toplam = self.k.db.execute(
            "SELECT COUNT(*) FROM maddeler WHERE yururluk_bitis IS NULL AND mulga=0").fetchone()[0]
        hazir = self.k.db.execute(
            "SELECT COUNT(*) FROM yz_anlam a JOIN maddeler m ON m.id=a.madde_id"
            " WHERE m.yururluk_bitis IS NULL AND m.mulga=0 AND a.model=?", (self.model_kimlik,)).fetchone()[0]
        return hazir, toplam

    def eksikleri_isle(self, sinir: int = 512, durdur: threading.Event | None = None, ilerleme=None) -> int:
        """Vektörü olmayan ya da metni değişen güncel maddeleri vektörler. İşlenen madde sayısını döndürür."""
        if not self.hazir:
            return 0
        satirlar = self.k.db.execute(
            "SELECT m.id, m.madde_no, m.baslik, m.metin, b.baslik AS belge, a.sha AS eski_sha, a.model AS eski_model"
            " FROM maddeler m JOIN belgeler b ON b.id=m.belge_id LEFT JOIN yz_anlam a ON a.madde_id=m.id"
            " WHERE m.yururluk_bitis IS NULL AND m.mulga=0 AND (a.madde_id IS NULL OR a.model!=?)"
            " ORDER BY m.id LIMIT ?", (self.model_kimlik, sinir)).fetchall()
        islenen = 0
        for i in range(0, len(satirlar), 16):
            if durdur is not None and durdur.is_set():
                break
            parti = satirlar[i:i + 16]
            metinler = [madde_metni(r["baslik"] or "", r["belge"], r["madde_no"], r["metin"]) for r in parti]
            vektorler = self.sunucu.vektor(metinler)
            with self.k._kilit, self.k.db:
                for r, metin, v in zip(parti, metinler, vektorler, strict=True):
                    self.k.db.execute(
                        "INSERT INTO yz_anlam(madde_id, model, sha, vektor) VALUES(?,?,?,?)"
                        " ON CONFLICT(madde_id) DO UPDATE SET model=excluded.model, sha=excluded.sha,"
                        " vektor=excluded.vektor",
                        (r["id"], self.model_kimlik, hashlib.sha1(metin.encode("utf-8")).hexdigest(),
                         v.astype(np.float16).tobytes()))
            islenen += len(parti)
            if ilerleme:
                ilerleme(islenen, len(satirlar))
        if islenen:
            with self._kilit:
                self._matris = None
        return islenen

    def _yukle(self) -> None:
        sayi = self.k.db.execute("SELECT COUNT(*) FROM yz_anlam WHERE model=?", (self.model_kimlik,)).fetchone()[0]
        if self._matris is not None and sayi == self._surum:
            return
        satirlar = self.k.db.execute(
            "SELECT a.madde_id, a.vektor FROM yz_anlam a JOIN maddeler m ON m.id=a.madde_id"
            " WHERE a.model=? AND m.yururluk_bitis IS NULL", (self.model_kimlik,)).fetchall()
        if not satirlar:
            self._matris = np.zeros((0, 1), dtype=np.float32)
            self._kimlikler = np.zeros(0, dtype=np.int64)
        else:
            self._kimlikler = np.array([r[0] for r in satirlar], dtype=np.int64)
            self._matris = np.vstack([np.frombuffer(r[1], dtype=np.float16) for r in satirlar]).astype(np.float32)
        self._surum = sayi

    def sorgu_vektoru(self, sorgu: str) -> np.ndarray:
        return self.sunucu.vektor([f"Instruct: {self.talimat}\nQuery: {sorgu}"])[0]

    def ara(self, sorgu: str, k: int = 10) -> list[tuple[int, float]]:
        if not self.hazir:
            return []
        with self._kilit:
            self._yukle()
            if self._matris is None or not len(self._kimlikler):
                return []
            q = self.sorgu_vektoru(sorgu)
            if q.shape[0] != self._matris.shape[1]:
                return []
            skor = self._matris @ q
            en_iyi = np.argsort(-skor)[:k]
            return [(int(self._kimlikler[i]), float(skor[i])) for i in en_iyi]
