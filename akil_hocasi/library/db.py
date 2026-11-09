"""Yerel kütüphane: belgeler, sürümler, madde madde metin, soru-cevap bankası, takip listesi.

SQLite + FTS5 kullanır; Türkçe katlanmış metin üzerinde tam metin arama yapar.
Her belge değişikliğinde eski sürüm geçerlilik tarihiyle saklanır.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from ..core.turkce import katla
from .ayristirici import MaddeParcasi, maddelere_bol

SEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS belgeler (
    id INTEGER PRIMARY KEY,
    tur TEXT NOT NULL,              -- kanun, yonetmelik, togu, gorus, sss, emsal, ipucu
    kimlik TEXT NOT NULL UNIQUE,    -- '657', 'TOGÜ.FRM.203', 'RG:2026-11-09:1'
    baslik TEXT NOT NULL,
    kaynak_url TEXT,
    kaynak_turu TEXT NOT NULL,      -- Mevzuat, Resmî görüş, TOGÜ belgesi, Emsal, Yönlendirme
    birim TEXT DEFAULT '',
    durum TEXT DEFAULT 'guncel',    -- guncel, eski, kaldirildi, inceleme
    eklenme TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS surumler (
    id INTEGER PRIMARY KEY,
    belge_id INTEGER NOT NULL REFERENCES belgeler(id),
    sha256 TEXT NOT NULL,
    rv TEXT DEFAULT '',
    yayin_tarihi TEXT DEFAULT '',
    indirme_tarihi TEXT NOT NULL,
    gecerlilik_baslangic TEXT NOT NULL,
    gecerlilik_bitis TEXT,          -- NULL = güncel sürüm
    dosya_yolu TEXT DEFAULT '',
    degistiren TEXT DEFAULT ''      -- ör. 'RG 09.11.2026 / 33000'
);
CREATE TABLE IF NOT EXISTS maddeler (
    id INTEGER PRIMARY KEY,
    belge_id INTEGER NOT NULL REFERENCES belgeler(id),
    surum_id INTEGER NOT NULL REFERENCES surumler(id),
    madde_no TEXT NOT NULL,
    baslik TEXT DEFAULT '',
    metin TEXT NOT NULL,
    mulga INTEGER DEFAULT 0,
    yururluk_baslangic TEXT NOT NULL,
    yururluk_bitis TEXT
);
CREATE INDEX IF NOT EXISTS ix_madde_belge ON maddeler(belge_id, madde_no);
CREATE VIRTUAL TABLE IF NOT EXISTS maddeler_fts USING fts5(
    metin, baslik, belge, tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS atiflar (
    madde_id INTEGER NOT NULL REFERENCES maddeler(id),
    hedef TEXT NOT NULL               -- '657/108'
);
CREATE INDEX IF NOT EXISTS ix_atif_hedef ON atiflar(hedef);
CREATE TABLE IF NOT EXISTS soru_cevap (
    id INTEGER PRIMARY KEY,
    soru TEXT NOT NULL,
    kisa_cevap TEXT NOT NULL,
    dayanak TEXT NOT NULL,            -- JSON: ['657/108', 'TOGÜ.USE.020/5']
    kaynaklar TEXT NOT NULL,          -- JSON: [{"baslik":..,"url":..}]
    orijinal_url TEXT DEFAULT '',
    yaygin_yanlis TEXT DEFAULT '',
    dogrulama_tarihi TEXT NOT NULL,
    durum TEXT DEFAULT 'dogrulandi'   -- dogrulandi, yeniden_dogrulanacak
);
CREATE VIRTUAL TABLE IF NOT EXISTS soru_cevap_fts USING fts5(
    soru, cevap, tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS islem_kartlari (
    id INTEGER PRIMARY KEY,
    kimlik TEXT UNIQUE NOT NULL,
    baslik TEXT NOT NULL,
    icerik TEXT NOT NULL,             -- JSON
    dayanak TEXT NOT NULL,            -- JSON listesi
    onaylayan TEXT DEFAULT '',
    onay_tarihi TEXT DEFAULT '',
    surum TEXT DEFAULT '1',
    durum TEXT DEFAULT 'onay_bekliyor'  -- onayli, onay_bekliyor, inceleme_bekliyor
);
CREATE TABLE IF NOT EXISTS takipteki_sorular (
    id INTEGER PRIMARY KEY,
    soru TEXT NOT NULL,
    eklenme TEXT NOT NULL,
    son_arama TEXT,
    durum TEXT DEFAULT 'takipte'       -- takipte, bulundu, kapatildi
);
CREATE TABLE IF NOT EXISTS degisiklikler (
    id INTEGER PRIMARY KEY,
    zaman TEXT NOT NULL,
    belge_kimlik TEXT NOT NULL,
    tur TEXT NOT NULL,                 -- yeni, guncellendi, kaldirildi, inceleme
    ozet TEXT NOT NULL,
    kaynak_url TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS kaynak_durumu (
    url TEXT PRIMARY KEY,
    etag TEXT DEFAULT '',
    last_modified TEXT DEFAULT '',
    sha256 TEXT DEFAULT '',
    son_kontrol TEXT
);
CREATE TABLE IF NOT EXISTS zamanlayici (
    gorev TEXT PRIMARY KEY,
    son_calisma TEXT
);
"""

_DURAK = {
    "ve", "veya", "ile", "bir", "bu", "şu", "da", "de", "mi", "mı", "mu", "mü", "ne", "nasıl",
    "için", "icin", "gibi", "olan", "olarak", "hangi", "kim", "kimin", "midir", "mıdır",
    "var", "yok", "ise", "ki", "çok", "daha", "en", "her", "ya", "o",
}


def simdi() -> str:
    # Mikrosaniye: aynı saniyede kaydedilen sürümler de doğru sıralanır
    return datetime.now().isoformat(timespec="microseconds")


@dataclass
class Pasaj:
    """Arama sonucunda dönen, kaynağı belli metin parçası."""
    madde_id: int
    belge_kimlik: str
    belge_baslik: str
    madde_no: str
    baslik: str
    metin: str
    kaynak_url: str
    kaynak_turu: str
    belge_turu: str
    skor: float = 0.0
    yururlukte: bool = True
    mulga: bool = False
    rv: str = ""
    yayin_tarihi: str = ""
    son_kontrol: str = ""
    atiflar: list[str] = field(default_factory=list)
    anlam: float = 0.0           # anlam aramasındaki benzerlik (0..1); kelime aramasından geldiyse 0

    @property
    def etiket(self) -> str:
        if self.madde_no and self.madde_no != "Giriş":
            return f"{self.belge_baslik}, md. {self.madde_no}"
        return self.belge_baslik


# Katlanmış (ASCII) biçimde yaygın Türkçe çekim ekleri; uzundan kısaya
_EKLER = sorted({
    "larindan", "lerinden", "larinda", "lerinde", "larina", "lerine", "larini", "lerini", "lari", "leri",
    "lar", "ler", "sinin", "sunun", "sindan", "sinden", "sundan", "sinde", "sunda", "sina", "sine", "suna",
    "sini", "sunu", "si", "su", "nin", "nun", "inin", "unun", "ndan", "nden", "inda", "inde", "unda",
    "dan", "den", "tan", "ten", "da", "de", "ta", "te", "ina", "ine", "una", "ya", "ye", "yi", "yu",
    "in", "un", "i", "u", "a", "e",
}, key=len, reverse=True)
_DURAK_KATLI = {katla(d) for d in _DURAK}


def _terim_kok(terim: str) -> str:
    """Eklemeli Türkçe için hafif ek ayıklayıcı (kök en az 4 harf kalır).

    'suresi' -> 'sure' ('sürenin', 'süre' ile eşleşir), 'gorevlendirmede' -> 'gorevlendirm'.
    """
    if terim.isdigit():
        return terim
    kok = terim
    for _ in range(2):
        for ek in _EKLER:
            if kok.endswith(ek) and len(kok) - len(ek) >= 4:
                kok = kok[: -len(ek)]
                break
        else:
            break
    return kok


def _temiz(ham: str) -> str:
    return "".join(ch for ch in ham if ch.isalnum())


def fts_sorgusu(metin: str, ek_terimler: Iterable[str] = ()) -> str:
    """Kullanıcı sorusunu FTS5 sorgusuna çevirir (katlanmış, kök önekli, OR bağlı).

    Çok kelimeli ek terimler (ör. eş anlamlı 'aylıksız izin') ayrıca öbek olarak aranır;
    öbeği birebir içeren madde üst sıraya çıkar.
    """
    parcalar: list[str] = []
    ek_liste = [katla(t) for t in ek_terimler]
    for ham in list(katla(metin).replace("/", " ").split()) + [k for e in ek_liste for k in e.split()]:
        t = _temiz(ham)
        if not t or t in _DURAK_KATLI or (len(t) < 3 and not t.isdigit()):
            continue
        parcalar.append(f'"{_terim_kok(t)}"*')
    for e in ek_liste:
        kelimeler = [_temiz(k) for k in e.split() if _temiz(k)]
        if len(kelimeler) > 1:
            parcalar.append('"' + " ".join(kelimeler) + '"')
    goruldu, sonuc = set(), []
    for p in parcalar:
        if p not in goruldu:
            goruldu.add(p)
            sonuc.append(p)
    return " OR ".join(sonuc)


class Kutuphane:
    def __init__(self, yol: Path | str):
        self.yol = str(yol)
        self._kilit = threading.RLock()
        self.db = sqlite3.connect(self.yol, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SEMA)

    # ------------------------------------------------------------------ belgeler
    def belge_kaydet(self, *, tur: str, kimlik: str, baslik: str, metin: str, sha256: str,
                     kaynak_url: str = "", kaynak_turu: str = "Mevzuat", birim: str = "",
                     rv: str = "", yayin_tarihi: str = "", dosya_yolu: str = "",
                     degistiren: str = "", maddeler: list[MaddeParcasi] | None = None) -> str:
        """Belgeyi kaydeder. Dönüş: 'yeni', 'guncellendi' veya 'ayni'.

        Değişiklikte eski sürüm ve maddeleri kapanış tarihiyle saklanır, bu belgeye
        dayanan işlem kartları ve soru-cevaplar yeniden incelemeye düşer.
        """
        with self._kilit, self.db:
            zaman = simdi()
            satir = self.db.execute("SELECT id FROM belgeler WHERE kimlik=?", (kimlik,)).fetchone()
            if satir:
                belge_id = satir["id"]
                guncel = self.db.execute(
                    "SELECT id, sha256 FROM surumler WHERE belge_id=? AND gecerlilik_bitis IS NULL",
                    (belge_id,)).fetchone()
                if guncel and guncel["sha256"] == sha256:
                    return "ayni"
                if guncel:
                    self.db.execute("UPDATE surumler SET gecerlilik_bitis=? WHERE id=?", (zaman, guncel["id"]))
                    eski = self.db.execute(
                        "SELECT id FROM maddeler WHERE surum_id=? AND yururluk_bitis IS NULL",
                        (guncel["id"],)).fetchall()
                    for m in eski:
                        self.db.execute("DELETE FROM maddeler_fts WHERE rowid=?", (m["id"],))
                    self.db.execute(
                        "UPDATE maddeler SET yururluk_bitis=? WHERE surum_id=? AND yururluk_bitis IS NULL",
                        (zaman, guncel["id"]))
                self.db.execute(
                    "UPDATE belgeler SET baslik=?, kaynak_url=?, kaynak_turu=?, birim=?, durum='guncel' WHERE id=?",
                    (baslik, kaynak_url, kaynak_turu, birim, belge_id))
                sonuc = "guncellendi"
            else:
                belge_id = self.db.execute(
                    "INSERT INTO belgeler(tur,kimlik,baslik,kaynak_url,kaynak_turu,birim,eklenme)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (tur, kimlik, baslik, kaynak_url, kaynak_turu, birim, zaman)).lastrowid
                sonuc = "yeni"

            surum_id = self.db.execute(
                "INSERT INTO surumler(belge_id,sha256,rv,yayin_tarihi,indirme_tarihi,gecerlilik_baslangic,"
                "dosya_yolu,degistiren) VALUES(?,?,?,?,?,?,?,?)",
                (belge_id, sha256, rv, yayin_tarihi, zaman, zaman, dosya_yolu, degistiren)).lastrowid

            for p in (maddeler if maddeler is not None else maddelere_bol(metin)):
                mid = self.db.execute(
                    "INSERT INTO maddeler(belge_id,surum_id,madde_no,baslik,metin,mulga,yururluk_baslangic)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (belge_id, surum_id, p.madde_no, p.baslik, p.metin, int(p.mulga), zaman)).lastrowid
                self.db.execute(
                    "INSERT INTO maddeler_fts(rowid, metin, baslik, belge) VALUES(?,?,?,?)",
                    (mid, katla(p.metin), katla(p.baslik), katla(baslik)))
                for hedef in p.atiflar:
                    if hedef.startswith("./"):
                        hedef = f"{kimlik}/{hedef[2:]}"
                    self.db.execute("INSERT INTO atiflar(madde_id, hedef) VALUES(?,?)", (mid, hedef))

            ozet = f"{baslik} {'eklendi' if sonuc == 'yeni' else 'güncellendi'}" + (f" (RV {rv})" if rv else "")
            self.db.execute(
                "INSERT INTO degisiklikler(zaman,belge_kimlik,tur,ozet,kaynak_url) VALUES(?,?,?,?,?)",
                (zaman, kimlik, sonuc, ozet, kaynak_url))
            if sonuc == "guncellendi":
                self._bagimlilari_isaretle(kimlik, zaman)
            return sonuc

    def _bagimlilari_isaretle(self, kimlik: str, zaman: str) -> None:
        """Değişen belgeye dayanan kartları ve soru-cevapları incelemeye alır."""
        desen = f'%"{kimlik}%'
        kartlar = self.db.execute(
            "SELECT kimlik FROM islem_kartlari WHERE dayanak LIKE ?", (desen,)).fetchall()
        self.db.execute(
            "UPDATE islem_kartlari SET durum='inceleme_bekliyor' WHERE dayanak LIKE ?", (desen,))
        self.db.execute(
            "UPDATE soru_cevap SET durum='yeniden_dogrulanacak' WHERE dayanak LIKE ?", (desen,))
        for k in kartlar:
            self.db.execute(
                "INSERT INTO degisiklikler(zaman,belge_kimlik,tur,ozet) VALUES(?,?,?,?)",
                (zaman, k["kimlik"], "inceleme", f"{kimlik} değişti; işlem kartı inceleme bekliyor"))

    # ------------------------------------------------------------------ arama
    def ara(self, sorgu: str, limit: int = 8, ek_terimler: Iterable[str] = (),
            tarih: str | None = None) -> list[Pasaj]:
        """Güncel (veya verilen tarihte yürürlükte olan) maddelerde arar."""
        fts = fts_sorgusu(sorgu, ek_terimler)
        if not fts:
            return []
        with self._kilit:
            try:
                satirlar = self.db.execute(
                    "SELECT rowid, bm25(maddeler_fts, 1.0, 3.0, 0.5) AS skor FROM maddeler_fts"
                    " WHERE maddeler_fts MATCH ? ORDER BY skor LIMIT ?",
                    (fts, limit * 3)).fetchall()
            except sqlite3.OperationalError:
                return []
            pasajlar = []
            for s in satirlar:
                p = self._pasaj(s["rowid"], -s["skor"])
                if p and (tarih is None or p.yururlukte):
                    pasajlar.append(p)
            return pasajlar[:limit]

    def _pasaj(self, madde_id: int, skor: float = 0.0) -> Pasaj | None:
        r = self.db.execute(
            "SELECT m.*, b.kimlik, b.baslik AS bbaslik, b.kaynak_url, b.kaynak_turu, b.tur AS btur,"
            " s.rv, s.yayin_tarihi, s.indirme_tarihi FROM maddeler m"
            " JOIN belgeler b ON b.id=m.belge_id JOIN surumler s ON s.id=m.surum_id WHERE m.id=?",
            (madde_id,)).fetchone()
        if not r:
            return None
        atif = [a["hedef"] for a in self.db.execute("SELECT hedef FROM atiflar WHERE madde_id=?", (madde_id,))]
        k = self.db.execute("SELECT son_kontrol FROM kaynak_durumu WHERE url=?", (r["kaynak_url"] or "",)).fetchone()
        return Pasaj(
            madde_id=r["id"], belge_kimlik=r["kimlik"], belge_baslik=r["bbaslik"], madde_no=r["madde_no"],
            baslik=r["baslik"] or "", metin=r["metin"], kaynak_url=r["kaynak_url"] or "",
            kaynak_turu=r["kaynak_turu"], belge_turu=r["btur"], skor=skor,
            yururlukte=r["yururluk_bitis"] is None, mulga=bool(r["mulga"]), rv=r["rv"] or "",
            yayin_tarihi=r["yayin_tarihi"] or "",
            son_kontrol=(k["son_kontrol"] if k and k["son_kontrol"] else r["indirme_tarihi"]),
            atiflar=atif)

    def pasaj_getir(self, madde_id: int, skor: float = 0.0) -> Pasaj | None:
        with self._kilit:
            return self._pasaj(madde_id, skor)

    def madde_getir(self, kimlik: str, madde_no: str, tarih: str | None = None) -> Pasaj | None:
        """Belgenin maddesini getirir; tarih verilirse o tarihte yürürlükte olan metni."""
        with self._kilit:
            if tarih:
                r = self.db.execute(
                    "SELECT m.id FROM maddeler m JOIN belgeler b ON b.id=m.belge_id"
                    " WHERE b.kimlik=? AND m.madde_no=? AND m.yururluk_baslangic<=?"
                    " AND (m.yururluk_bitis IS NULL OR m.yururluk_bitis>?) ORDER BY m.id DESC LIMIT 1",
                    (kimlik, madde_no, tarih, tarih)).fetchone()
            else:
                r = self.db.execute(
                    "SELECT m.id FROM maddeler m JOIN belgeler b ON b.id=m.belge_id"
                    " WHERE b.kimlik=? AND m.madde_no=? AND m.yururluk_bitis IS NULL ORDER BY m.id DESC LIMIT 1",
                    (kimlik, madde_no)).fetchone()
            return self._pasaj(r["id"]) if r else None

    def atif_zinciri(self, pasaj: Pasaj, derinlik: int = 1) -> list[Pasaj]:
        """Pasajın atıf yaptığı maddeleri ve ona atıf yapan maddeleri getirir."""
        bulunan: dict[int, Pasaj] = {}
        with self._kilit:
            for hedef in pasaj.atiflar:
                if "/" not in hedef:
                    continue
                kimlik, no = hedef.rsplit("/", 1)
                p = self.madde_getir(kimlik, no)
                if p and p.madde_id != pasaj.madde_id:
                    bulunan[p.madde_id] = p
            geri = self.db.execute(
                "SELECT a.madde_id FROM atiflar a JOIN maddeler m ON m.id=a.madde_id"
                " WHERE a.hedef=? AND m.yururluk_bitis IS NULL LIMIT 6",
                (f"{pasaj.belge_kimlik}/{pasaj.madde_no}",)).fetchall()
            for g in geri:
                p = self._pasaj(g["madde_id"])
                if p and p.madde_id != pasaj.madde_id:
                    bulunan[p.madde_id] = p
        sonuc = list(bulunan.values())
        if derinlik > 1:
            for p in list(sonuc):
                for q in self.atif_zinciri(p, derinlik - 1):
                    if q.madde_id not in bulunan and q.madde_id != pasaj.madde_id:
                        bulunan[q.madde_id] = q
            sonuc = list(bulunan.values())
        return sonuc

    def belge_bilgisi(self, kimlik: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT b.*, s.rv, s.yayin_tarihi, s.gecerlilik_baslangic FROM belgeler b"
            " LEFT JOIN surumler s ON s.belge_id=b.id AND s.gecerlilik_bitis IS NULL WHERE b.kimlik=?",
            (kimlik,)).fetchone()

    def madde_degisti_mi(self, kimlik: str, madde_no: str, sonra: str) -> bool:
        """Maddenin verilen tarihten sonra yeni sürümü var mı (dayanak kontrolü için)."""
        r = self.db.execute(
            "SELECT COUNT(*) AS n FROM maddeler m JOIN belgeler b ON b.id=m.belge_id"
            " WHERE b.kimlik=? AND m.madde_no=? AND m.yururluk_baslangic>?",
            (kimlik, madde_no, sonra)).fetchone()
        return bool(r and r["n"] > 0)

    # ------------------------------------------------------------------ soru-cevap
    def soru_cevap_kaydet(self, soru: str, kisa_cevap: str, dayanak: list[str],
                          kaynaklar: list[dict], orijinal_url: str = "", yaygin_yanlis: str = "") -> int:
        with self._kilit, self.db:
            sid = self.db.execute(
                "INSERT INTO soru_cevap(soru,kisa_cevap,dayanak,kaynaklar,orijinal_url,yaygin_yanlis,"
                "dogrulama_tarihi) VALUES(?,?,?,?,?,?,?)",
                (soru, kisa_cevap, json.dumps(dayanak, ensure_ascii=False),
                 json.dumps(kaynaklar, ensure_ascii=False), orijinal_url, yaygin_yanlis, simdi())).lastrowid
            self.db.execute("INSERT INTO soru_cevap_fts(rowid, soru, cevap) VALUES(?,?,?)",
                            (sid, katla(soru), katla(kisa_cevap)))
            return sid

    def soru_cevap_ara(self, soru: str, limit: int = 3) -> list[sqlite3.Row]:
        fts = fts_sorgusu(soru)
        if not fts:
            return []
        with self._kilit:
            try:
                ids = self.db.execute(
                    "SELECT rowid, bm25(soru_cevap_fts, 3.0, 1.0) AS skor FROM soru_cevap_fts"
                    " WHERE soru_cevap_fts MATCH ? ORDER BY skor LIMIT ?", (fts, limit)).fetchall()
            except sqlite3.OperationalError:
                return []
            return [self.db.execute("SELECT * FROM soru_cevap WHERE id=?", (i["rowid"],)).fetchone() for i in ids]

    # ------------------------------------------------------------------ işlem kartları
    def kart_kaydet(self, kimlik: str, baslik: str, icerik: dict, dayanak: list[str],
                    onaylayan: str = "", onay_tarihi: str = "", surum: str = "1") -> None:
        durum = "onayli" if onaylayan else "onay_bekliyor"
        with self._kilit, self.db:
            self.db.execute(
                "INSERT INTO islem_kartlari(kimlik,baslik,icerik,dayanak,onaylayan,onay_tarihi,surum,durum)"
                " VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(kimlik) DO UPDATE SET baslik=excluded.baslik,"
                " icerik=excluded.icerik, dayanak=excluded.dayanak, onaylayan=excluded.onaylayan,"
                " onay_tarihi=excluded.onay_tarihi, surum=excluded.surum, durum=excluded.durum",
                (kimlik, baslik, json.dumps(icerik, ensure_ascii=False),
                 json.dumps(dayanak, ensure_ascii=False), onaylayan, onay_tarihi, surum, durum))

    def kart_ara(self, soru: str, limit: int = 3) -> list[sqlite3.Row]:
        terimler = [t for t in katla(soru).split() if len(t) >= 4]
        if not terimler:
            return []
        with self._kilit:
            kartlar = self.db.execute("SELECT * FROM islem_kartlari").fetchall()
        puanli = []
        for k in kartlar:
            hedef = katla(k["baslik"] + " " + k["icerik"])
            puan = sum(1 for t in terimler if _terim_kok(t) in hedef)
            if puan:
                puanli.append((puan, k))
        puanli.sort(key=lambda x: -x[0])
        return [k for _, k in puanli[:limit]]

    # ------------------------------------------------------------------ takip
    def takibe_al(self, soru: str) -> int:
        with self._kilit, self.db:
            r = self.db.execute("SELECT id FROM takipteki_sorular WHERE soru=? AND durum='takipte'",
                                (soru,)).fetchone()
            if r:
                return r["id"]
            return self.db.execute("INSERT INTO takipteki_sorular(soru, eklenme) VALUES(?,?)",
                                   (soru, simdi())).lastrowid

    def takipteki_sorular(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM takipteki_sorular WHERE durum='takipte' ORDER BY id").fetchall()

    def takip_guncelle(self, sid: int, durum: str | None = None) -> None:
        with self._kilit, self.db:
            if durum:
                self.db.execute("UPDATE takipteki_sorular SET durum=?, son_arama=? WHERE id=?", (durum, simdi(), sid))
            else:
                self.db.execute("UPDATE takipteki_sorular SET son_arama=? WHERE id=?", (simdi(), sid))

    # ------------------------------------------------------------------ değişiklik / durum
    def son_degisiklikler(self, gun: int = 7, limit: int = 100) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM degisiklikler WHERE zaman >= datetime('now','localtime',?) ORDER BY zaman DESC LIMIT ?",
            (f"-{gun} days", limit)).fetchall()

    def kaynak_durumu(self, url: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM kaynak_durumu WHERE url=?", (url,)).fetchone()

    def kaynak_durumu_yaz(self, url: str, etag: str = "", last_modified: str = "", sha256: str = "") -> None:
        with self._kilit, self.db:
            self.db.execute(
                "INSERT INTO kaynak_durumu(url,etag,last_modified,sha256,son_kontrol) VALUES(?,?,?,?,?)"
                " ON CONFLICT(url) DO UPDATE SET etag=excluded.etag, last_modified=excluded.last_modified,"
                " sha256=CASE WHEN excluded.sha256!='' THEN excluded.sha256 ELSE kaynak_durumu.sha256 END,"
                " son_kontrol=excluded.son_kontrol",
                (url, etag, last_modified, sha256, simdi()))

    def zamanlayici_son(self, gorev: str) -> str | None:
        r = self.db.execute("SELECT son_calisma FROM zamanlayici WHERE gorev=?", (gorev,)).fetchone()
        return r["son_calisma"] if r else None

    def zamanlayici_yaz(self, gorev: str, zaman: str | None = None) -> None:
        with self._kilit, self.db:
            self.db.execute(
                "INSERT INTO zamanlayici(gorev, son_calisma) VALUES(?,?)"
                " ON CONFLICT(gorev) DO UPDATE SET son_calisma=excluded.son_calisma", (gorev, zaman or simdi()))

    def istatistik(self) -> dict:
        def say(sql: str) -> int:
            return self.db.execute(sql).fetchone()[0]
        return {
            "belge": say("SELECT COUNT(*) FROM belgeler WHERE durum!='kaldirildi'"),
            "madde": say("SELECT COUNT(*) FROM maddeler WHERE yururluk_bitis IS NULL"),
            "soru_cevap": say("SELECT COUNT(*) FROM soru_cevap"),
            "takip": say("SELECT COUNT(*) FROM takipteki_sorular WHERE durum='takipte'"),
            "bugun_degisiklik": say(
                "SELECT COUNT(*) FROM degisiklikler WHERE date(zaman)=date('now','localtime')"),
        }

    def kapat(self) -> None:
        self.db.close()
