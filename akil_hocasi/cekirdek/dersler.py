"""Ders hafızası: hatalardan çıkarılan yöntem dersleri.

Ders bir YÖNTEMDİR, bilgi değildir ("Yıllık izin sorularında önce statüyü belirle" geçerli; "yıllık izin 20 gündür"
geçersiz). Dersler aday olarak kaydedilir; gelişim kapısında sınanıp benimsenmeden kullanılmaz. Hiçbir ders bir
ilkeyi gevşetemez ya da bir testi atlatamaz.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from ..core.turkce import katla
from .ilkeler import ILKE_KODLARI, sistem_cekirdegi
from .yordamlar import YORDAMLAR

SEMA = """
CREATE TABLE IF NOT EXISTS cek_ders (
    id INTEGER PRIMARY KEY, yordam TEXT NOT NULL, metin TEXT NOT NULL, anahtar TEXT NOT NULL UNIQUE,
    kosul TEXT DEFAULT '[]', ilke TEXT DEFAULT '', kaynak TEXT DEFAULT '', durum TEXT NOT NULL DEFAULT 'aday',
    kanit TEXT DEFAULT '{}', olusturma TEXT NOT NULL, karar_zamani TEXT DEFAULT '', gerekce TEXT DEFAULT '',
    kullanim INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cek_hata (
    id INTEGER PRIMARY KEY, zaman TEXT NOT NULL, soru TEXT NOT NULL, hatalar TEXT NOT NULL, islendi INTEGER DEFAULT 0
);
"""
_YORDAM_KODLARI = {y.kod for y in YORDAMLAR}
# İlkeyi gevşeten ya da testi atlatan ifadeler: böyle ders kabul edilmez
_YASAK = re.compile(r"kaynak (gösterme|gerekmez|gereksiz)|doğrulama(yı)? (atla|yapma|gerekmez)|test(i|leri)? atla|"
                    r"uydur|tahmin(en)? (yaz|söyle)|kesin (söyle|yaz) .*kaynaksız|alıntıyı değiştir|"
                    r"maskeleme(yi)? (yapma|kaldır)|sayı(yı)? üret|tarih(i)? üret|imza(yı)? üret|kurala uyma", re.I)
_SAYI_MADDE = re.compile(r"\d|madde\s+\w+\s*\d|md\.\s*\d", re.I)


def ders_gecerli_mi(metin: str) -> tuple[bool, str]:
    m = (metin or "").strip()
    if not 20 <= len(m) <= 300:
        return False, "Ders 20–300 karakter olmalı"
    if _SAYI_MADDE.search(m):
        return False, "Ders kesin bilgi (sayı, süre, madde) içeremez; bilgi kütüphaneden gelir"
    if _YASAK.search(m):
        return False, "Ders bir ilkeyi gevşetemez ya da bir testi atlatamaz"
    return True, ""


def _anahtar(metin: str) -> str:
    return " ".join(sorted(set(re.findall(r"[a-z0-9]{3,}", katla(metin)))))[:400]


class DersHafizasi:
    def __init__(self, kutuphane):
        self.k = kutuphane
        with self.k._kilit, self.k.db:
            self.k.db.executescript(SEMA)

    def aday_ekle(self, yordam: str, metin: str, kosul: list[str] | None = None, ilke: str = "",
                  kaynak: str = "", kanit: dict | None = None) -> int | None:
        ok, _ = ders_gecerli_mi(metin)
        if not ok or yordam not in _YORDAM_KODLARI or (ilke and ilke not in ILKE_KODLARI):
            return None
        anahtar = _anahtar(metin)
        with self.k._kilit, self.k.db:
            if self.k.db.execute("SELECT 1 FROM cek_ders WHERE anahtar=?", (anahtar,)).fetchone():
                return None
            return self.k.db.execute(
                "INSERT INTO cek_ders(yordam, metin, anahtar, kosul, ilke, kaynak, durum, kanit, olusturma)"
                " VALUES(?,?,?,?,?,?, 'aday', ?, ?)",
                (yordam, metin.strip(), anahtar, json.dumps([katla(t) for t in (kosul or []) if t][:12]), ilke, kaynak,
                 json.dumps(kanit or {}, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"))).lastrowid

    def karar(self, ders_id: int, durum: str, gerekce: str = "") -> None:
        assert durum in ("etkin", "reddedildi", "geri_alindi", "aday")
        with self.k._kilit, self.k.db:
            self.k.db.execute("UPDATE cek_ders SET durum=?, gerekce=?, karar_zamani=? WHERE id=?",
                              (durum, gerekce, datetime.now().isoformat(timespec="seconds"), ders_id))

    def adaylar(self, sinir: int = 20) -> list[dict]:
        return [dict(r) for r in self.k.db.execute(
            "SELECT * FROM cek_ders WHERE durum='aday' ORDER BY id LIMIT ?", (sinir,)).fetchall()]

    def tumu(self) -> list[dict]:
        return [dict(r) for r in self.k.db.execute("SELECT * FROM cek_ders ORDER BY id DESC").fetchall()]

    def ilgili(self, istek: str, yordamlar: tuple[str, ...] = (), n: int = 3, ek_kimlik: int | None = None) -> list[str]:
        """Bu işe uyan etkin dersler (ek_kimlik: sınamada geçici olarak etkin sayılan aday)."""
        k = katla(istek)
        satirlar = self.k.db.execute(
            "SELECT * FROM cek_ders WHERE durum='etkin' OR id=?", (ek_kimlik or -1,)).fetchall()
        puanli = []
        for r in satirlar:
            if yordamlar and r["yordam"] not in yordamlar:
                continue
            kosul = json.loads(r["kosul"] or "[]")
            puan = sum(1 for t in kosul if t and t in k) if kosul else 0.5
            if kosul and puan == 0:
                continue
            puanli.append((puan, r["kullanim"], r["id"], r["metin"]))
        secilen = sorted(puanli, key=lambda x: (-x[0], -x[1]))[:n]
        if secilen:
            with self.k._kilit, self.k.db:
                self.k.db.executemany("UPDATE cek_ders SET kullanim=kullanim+1 WHERE id=?", [(s[2],) for s in secilen])
        return [s[3] for s in secilen]

    # ------------------------------------------------------------------ hata kayıtları
    def hata_kaydet(self, soru: str, hatalar: list[str]) -> None:
        with self.k._kilit, self.k.db:
            self.k.db.execute("INSERT INTO cek_hata(zaman, soru, hatalar) VALUES(?,?,?)",
                              (datetime.now().isoformat(timespec="seconds"), soru[:500],
                               json.dumps(hatalar[:10], ensure_ascii=False)))
            self.k.db.execute("DELETE FROM cek_hata WHERE id NOT IN (SELECT id FROM cek_hata ORDER BY id DESC LIMIT 500)")

    def islenmemis_hatalar(self, sinir: int = 10) -> list[dict]:
        return [dict(r) for r in self.k.db.execute(
            "SELECT * FROM cek_hata WHERE islendi=0 ORDER BY id DESC LIMIT ?", (sinir,)).fetchall()]

    def hata_islendi(self, kimlik: int) -> None:
        with self.k._kilit, self.k.db:
            self.k.db.execute("UPDATE cek_hata SET islendi=1 WHERE id=?", (kimlik,))

    # ------------------------------------------------------------------ ders çıkarma
    DERS_SEMASI = {
        "type": "object",
        "properties": {
            "dersler": {"type": "array", "maxItems": 2, "items": {"type": "object", "properties": {
                "yordam": {"type": "string", "enum": sorted(_YORDAM_KODLARI)},
                "ders": {"type": "string"},
                "kosul_terimleri": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                "ilke": {"type": "string", "enum": list(ILKE_KODLARI)}},
                "required": ["yordam", "ders", "kosul_terimleri", "ilke"]}}},
        "required": ["dersler"],
    }
    DERS_GOREVI = (
        "Aşağıda bir işte yapılan hatalar ve nedenleri var. Bunlardan, benzer işlerde tekrarlanmaması için en fazla iki "
        "YÖNTEM dersi çıkar. Ders bir talimattır ('… sorularında önce … denetle'); kesin bilgi, sayı, süre, madde "
        "numarası içeremez; hiçbir ilkeyi gevşetemez. Dersin hangi yordama ait olduğunu ve hangi tür sorularda "
        "geçerli olduğunu belirten anahtar terimleri yaz. Genellenemeyen hatadan ders çıkarma; boş liste döndür.")

    def hatadan_cikar(self, model, soru: str, hatalar: list[str], kaynak: str = "sinama") -> list[int]:
        """Hata özetinden ders adayları (model yoksa kural tabanlı şablonlar)."""
        eklenen: list[int] = []
        if model is not None and getattr(model, "hazir", False) and hatalar:
            from ..answer.llm import json_cikar
            try:
                cikti = model.sohbet(
                    [{"role": "system", "content": sistem_cekirdegi(self.DERS_GOREVI)},
                     {"role": "user", "content": f"SORU: {soru}\nHATALAR:\n" + "\n".join(f"- {h}" for h in hatalar[:8])}],
                    max_tokens=400, sicaklik=0.2, json_mod=True, json_sema=self.DERS_SEMASI)
                for d in (json_cikar(cikti) or {}).get("dersler", [])[:2]:
                    i = self.aday_ekle(d.get("yordam", ""), d.get("ders", ""), d.get("kosul_terimleri"),
                                       d.get("ilke", ""), kaynak, {"soru": soru, "hatalar": hatalar[:8]})
                    if i:
                        eklenen.append(i)
            except Exception:  # noqa: BLE001 - ders çıkarılamazsa kayıtta kalır
                pass
        return eklenen
