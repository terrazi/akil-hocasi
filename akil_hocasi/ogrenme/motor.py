"""Öğrenme motoru: kullanım olaylarından terim, kaynak, OCR ve örnek öğrenir.

Kural: öğrenilen hiçbir şey cevabın içeriğini belirlemez. Terimler aramayı genişletir,
kaynak puanları sıralamayı değiştirir, örnekler modele biçim gösterir; her cümle yine
madde metnine bağlıdır ve doğrulama motorundan geçer.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from datetime import datetime, timedelta

from ..core.maskeleme import metni_maskele
from ..core.turkce import katla
from ..library.db import _DURAK_KATLI, Kutuphane, _terim_kok

ES_ANLAM_ESIGI = 2          # bir terim karşılığı en az iki kez gözlenince kullanılır
OTURUM_PENCERESI = 600      # sn: başarısız soru ile başarılı yeniden sorma arası

SEMA = """
CREATE TABLE IF NOT EXISTS ogr_olaylar (
    id INTEGER PRIMARY KEY, zaman TEXT NOT NULL, soru TEXT NOT NULL, durum TEXT NOT NULL,
    kaynaklar TEXT NOT NULL DEFAULT '[]', girdi TEXT DEFAULT '', cikti TEXT DEFAULT '',
    geri_bildirim INTEGER DEFAULT 0, tiklama INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ogr_es_anlam (a TEXT, b TEXT, sayi INTEGER DEFAULT 0, PRIMARY KEY (a, b));
CREATE TABLE IF NOT EXISTS ogr_ocr (yanlis TEXT, dogru TEXT, sayi INTEGER DEFAULT 0, PRIMARY KEY (yanlis, dogru));
CREATE TABLE IF NOT EXISTS ogr_kaynak (anahtar TEXT PRIMARY KEY, puan REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS ogr_ornek (
    id INTEGER PRIMARY KEY, soru TEXT UNIQUE NOT NULL, cikti TEXT NOT NULL, etiketler TEXT NOT NULL,
    zaman TEXT NOT NULL, kaynak TEXT DEFAULT 'yerel'
);
CREATE TABLE IF NOT EXISTS ogr_paylasilan (
    makine TEXT, tur TEXT, anahtar TEXT, deger REAL, PRIMARY KEY (makine, tur, anahtar)
);
CREATE TABLE IF NOT EXISTS ogr_paket_alim (makine TEXT PRIMARY KEY, sha TEXT, zaman TEXT);
CREATE TABLE IF NOT EXISTS ogr_altin (
    id INTEGER PRIMARY KEY, soru TEXT UNIQUE NOT NULL, beklenen_dayanak TEXT DEFAULT '[]',
    beklenen_ifade TEXT DEFAULT '', birim TEXT DEFAULT '', onaylayan TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ogr_degerlendirme (
    id INTEGER PRIMARY KEY, zaman TEXT NOT NULL, toplam INTEGER, gecen INTEGER, kritik INTEGER,
    model TEXT DEFAULT '', ayrinti TEXT DEFAULT '{}'
);
"""


def _simdi() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ayirt_edici_terimler(soru: str) -> set[str]:
    """Sorunun durak kelimesi olmayan, kökü alınmış terimleri."""
    return {_terim_kok(t) for t in re.findall(r"[a-z0-9]+", katla(soru))
            if len(t) >= 4 and t not in _DURAK_KATLI}


def kaynak_anahtari(belge_kimlik: str, madde_no: str) -> str:
    return f"{belge_kimlik}/{madde_no}"


class OgrenmeMotoru:
    def __init__(self, kutuphane: Kutuphane, makine: str = "yerel"):
        self.k = kutuphane
        self.db = kutuphane.db
        self.makine = makine
        self.duzeltici = None            # TurkceDuzeltici; uygulama bağlar
        self._kilit = threading.RLock()
        self._son_olay: tuple[float, str, str, set[str]] | None = None   # (zaman, soru, durum, terimler)
        with self._kilit, self.db:
            self.db.executescript(SEMA)

    # ================================================================== olaylar
    def olay_kaydet(self, cevap, girdi: str = "", cikti: str = "") -> int:
        """Her cevaptan sonra çağrılır; terim karşılığı öğrenmeyi de tetikler."""
        anahtarlar = [kaynak_anahtari(k.pasaj.belge_kimlik, k.pasaj.madde_no) for k in cevap.kaynaklar]
        durum = cevap.durum.value
        with self._kilit, self.db:
            oid = self.db.execute(
                "INSERT INTO ogr_olaylar(zaman, soru, durum, kaynaklar, girdi, cikti) VALUES(?,?,?,?,?,?)",
                (_simdi(), cevap.soru, durum, json.dumps(anahtarlar, ensure_ascii=False), girdi, cikti)).lastrowid
        self._terim_karsiligi_ogren(cevap.soru, durum)
        return oid

    def _terim_karsiligi_ogren(self, soru: str, durum: str) -> None:
        """Başarısız sorudan kısa süre sonra başarılı yeniden sorma: farklı terimler karşılık adayıdır."""
        simdi = time.time()
        terimler = ayirt_edici_terimler(soru)
        onceki = self._son_olay
        self._son_olay = (simdi, soru, durum, terimler)
        if not onceki or simdi - onceki[0] > OTURUM_PENCERESI:
            return
        if onceki[2] != "Doğrudan hüküm yok" or durum == "Doğrudan hüküm yok":
            return
        yalniz_onceki = onceki[3] - terimler
        yalniz_simdiki = terimler - onceki[3]
        if not (1 <= len(yalniz_onceki) <= 2 and 1 <= len(yalniz_simdiki) <= 2):
            return
        with self._kilit, self.db:
            for a in yalniz_onceki:
                for b in yalniz_simdiki:
                    self.db.execute(
                        "INSERT INTO ogr_es_anlam(a, b, sayi) VALUES(?,?,1)"
                        " ON CONFLICT(a, b) DO UPDATE SET sayi = sayi + 1", (a, b))

    def geri_bildirim(self, olay_id: int, deger: int, cevap=None) -> None:
        """+1 faydalı, -1 yanlış/eksik. Faydalı ve doğrulanmış cevap bankaya ve örnek hafızaya girer."""
        deger = 1 if deger > 0 else -1
        with self._kilit, self.db:
            r = self.db.execute("SELECT * FROM ogr_olaylar WHERE id=?", (olay_id,)).fetchone()
            if not r:
                return
            self.db.execute("UPDATE ogr_olaylar SET geri_bildirim=? WHERE id=?", (deger, olay_id))
            for anahtar in json.loads(r["kaynaklar"]):
                self.db.execute(
                    "INSERT INTO ogr_kaynak(anahtar, puan) VALUES(?,?)"
                    " ON CONFLICT(anahtar) DO UPDATE SET puan = puan + excluded.puan", (anahtar, float(deger)))
        if deger > 0 and r["durum"] == "Doğrulandı" and cevap is not None:
            self._bankaya_ve_hafizaya_al(cevap, r["cikti"])

    def tiklama(self, olay_id: int, belge_kimlik: str, madde_no: str) -> None:
        with self._kilit, self.db:
            self.db.execute("UPDATE ogr_olaylar SET tiklama = tiklama + 1 WHERE id=?", (olay_id,))
            self.db.execute(
                "INSERT INTO ogr_kaynak(anahtar, puan) VALUES(?, 0.3)"
                " ON CONFLICT(anahtar) DO UPDATE SET puan = puan + 0.3", (kaynak_anahtari(belge_kimlik, madde_no),))

    def _bankaya_ve_hafizaya_al(self, cevap, cikti: str) -> None:
        soru = metni_maskele(cevap.soru)
        kisa = " ".join(c.metin for c in cevap.kisa_cevap)
        dayanak = [kaynak_anahtari(k.pasaj.belge_kimlik, k.pasaj.madde_no) for k in cevap.kaynaklar]
        kaynaklar = [{"baslik": k.etiket, "url": k.pasaj.kaynak_url} for k in cevap.kaynaklar]
        var = self.db.execute("SELECT id FROM soru_cevap WHERE soru=?", (soru,)).fetchone()
        if not var:
            self.k.soru_cevap_kaydet(soru, metni_maskele(kisa), dayanak, kaynaklar)
        if cikti:
            with self._kilit, self.db:
                self.db.execute(
                    "INSERT OR IGNORE INTO ogr_ornek(soru, cikti, etiketler, zaman) VALUES(?,?,?,?)",
                    (soru, metni_maskele(cikti), json.dumps([k.etiket for k in cevap.kaynaklar], ensure_ascii=False),
                     _simdi()))

    # ================================================================== öğrenilenlerin kullanımı
    def _es_anlam_sayilari(self) -> dict[tuple[str, str], float]:
        sayilar: dict[tuple[str, str], float] = {}
        for r in self.db.execute("SELECT a, b, sayi FROM ogr_es_anlam"):
            sayilar[(r["a"], r["b"])] = float(r["sayi"])
        for r in self.db.execute("SELECT anahtar, SUM(deger) AS d FROM ogr_paylasilan WHERE tur='es_anlam' GROUP BY anahtar"):
            a, _, b = r["anahtar"].partition("→")
            sayilar[(a, b)] = sayilar.get((a, b), 0.0) + float(r["d"])
        return sayilar

    def ogrenilmis_terimler(self, soru: str) -> list[str]:
        """Soruda geçen terimler için öğrenilmiş (eşiği aşmış) karşılıklar."""
        terimler = ayirt_edici_terimler(soru)
        return sorted({b for (a, b), n in self._es_anlam_sayilari().items() if n >= ES_ANLAM_ESIGI and a in terimler})

    def kaynak_puani(self, belge_kimlik: str, madde_no: str) -> float:
        anahtar = kaynak_anahtari(belge_kimlik, madde_no)
        r = self.db.execute("SELECT puan FROM ogr_kaynak WHERE anahtar=?", (anahtar,)).fetchone()
        p = float(r["puan"]) if r else 0.0
        r2 = self.db.execute("SELECT SUM(deger) FROM ogr_paylasilan WHERE tur='kaynak' AND anahtar=?", (anahtar,)).fetchone()
        return p + 0.5 * float(r2[0] or 0.0)

    def siralamayi_ayarla(self, pasajlar) -> None:
        """İşe yaradığı görülen maddeleri öne, yanlış bildirilenleri geriye alır (yalnızca sıra)."""
        for p in pasajlar:
            puan = self.kaynak_puani(p.belge_kimlik, p.madde_no)
            p.skor += math.log1p(max(puan, 0.0)) - 1.5 * math.log1p(max(-puan, 0.0))

    def benzer_ornekler(self, soru: str, adet: int = 2) -> list[dict]:
        hedef = ayirt_edici_terimler(soru)
        if not hedef:
            return []
        puanli = []
        for r in self.db.execute("SELECT soru, cikti, etiketler FROM ogr_ornek ORDER BY id DESC LIMIT 500"):
            t = ayirt_edici_terimler(r["soru"])
            if not t:
                continue
            benzerlik = len(hedef & t) / len(hedef | t)
            if benzerlik >= 0.3:
                puanli.append((benzerlik, {"soru": r["soru"], "cikti": r["cikti"]}))
        puanli.sort(key=lambda x: -x[0])
        return [o for _, o in puanli[:adet]]

    # ================================================================== OCR düzeltmeleri
    def ocr_duzeltme_kaydet(self, yanlis: str, dogru: str) -> None:
        if not yanlis or not dogru or yanlis == dogru:
            return
        with self._kilit, self.db:
            self.db.execute("INSERT INTO ogr_ocr(yanlis, dogru, sayi) VALUES(?,?,1)"
                            " ON CONFLICT(yanlis, dogru) DO UPDATE SET sayi = sayi + 1", (yanlis, dogru))
        if self.duzeltici is not None:
            self.duzeltici.ogrenilmis[yanlis] = dogru

    def ocr_duzeltmeleri(self) -> dict[str, str]:
        sayilar: dict[tuple[str, str], float] = {}
        for r in self.db.execute("SELECT yanlis, dogru, sayi FROM ogr_ocr"):
            sayilar[(r["yanlis"], r["dogru"])] = float(r["sayi"])
        for r in self.db.execute("SELECT anahtar, SUM(deger) AS d FROM ogr_paylasilan WHERE tur='ocr' GROUP BY anahtar"):
            y, _, d = r["anahtar"].partition("→")
            sayilar[(y, d)] = sayilar.get((y, d), 0.0) + float(r["d"])
        en_iyi: dict[str, tuple[float, str]] = {}
        for (y, d), n in sayilar.items():
            if n > en_iyi.get(y, (0.0, ""))[0]:
                en_iyi[y] = (n, d)
        return {y: d for y, (_, d) in en_iyi.items()}

    # ================================================================== altın soru seti
    def altin_set_yukle(self, kayitlar: list[dict]) -> int:
        """Birim uzmanlarının onayladığı sorular: [{soru, beklenen_dayanak, beklenen_ifade, birim, onaylayan}]"""
        n = 0
        with self._kilit, self.db:
            for k in kayitlar:
                if not k.get("soru"):
                    continue
                self.db.execute(
                    "INSERT INTO ogr_altin(soru, beklenen_dayanak, beklenen_ifade, birim, onaylayan) VALUES(?,?,?,?,?)"
                    " ON CONFLICT(soru) DO UPDATE SET beklenen_dayanak=excluded.beklenen_dayanak,"
                    " beklenen_ifade=excluded.beklenen_ifade, birim=excluded.birim, onaylayan=excluded.onaylayan",
                    (k["soru"], json.dumps(k.get("beklenen_dayanak", []), ensure_ascii=False),
                     k.get("beklenen_ifade", ""), k.get("birim", ""), k.get("onaylayan", "")))
                n += 1
        return n

    # ================================================================== durum ve boşluklar
    def bilgi_bosluklari(self, gun: int = 30, adet: int = 8) -> list[dict]:
        """Son günlerde cevap bulunamayan soruların en sık terimleri ve örnek soruları."""
        sinir = (datetime.now() - timedelta(days=gun)).isoformat(timespec="seconds")
        sayac: dict[str, list[str]] = {}
        for r in self.db.execute("SELECT soru FROM ogr_olaylar WHERE durum='Doğrudan hüküm yok' AND zaman>=?", (sinir,)):
            for t in ayirt_edici_terimler(r["soru"]):
                sayac.setdefault(t, []).append(r["soru"])
        sirali = sorted(sayac.items(), key=lambda x: -len(x[1]))[:adet]
        return [{"terim": t, "sayi": len(s), "ornek": s[-1]} for t, s in sirali]

    def durum(self) -> dict:
        def say(sql: str, *p) -> int:
            return self.db.execute(sql, p).fetchone()[0] or 0
        son = self.db.execute("SELECT * FROM ogr_degerlendirme ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "olay": say("SELECT COUNT(*) FROM ogr_olaylar"),
            "faydali": say("SELECT COUNT(*) FROM ogr_olaylar WHERE geri_bildirim>0"),
            "es_anlam": len([1 for n in self._es_anlam_sayilari().values() if n >= ES_ANLAM_ESIGI]),
            "ocr": len(self.ocr_duzeltmeleri()),
            "ornek": say("SELECT COUNT(*) FROM ogr_ornek"),
            "altin": say("SELECT COUNT(*) FROM ogr_altin"),
            "son_degerlendirme": dict(son) if son else None,
            "paylasan_makine": say("SELECT COUNT(DISTINCT makine) FROM ogr_paylasilan"),
        }

    def gecmisi_temizle(self, gun: int) -> int:
        """Gizlilik: eski olayları siler; faydalı işaretlenenler (eğitim verisi) maskeli olarak kalır."""
        if gun <= 0:
            return 0
        sinir = (datetime.now() - timedelta(days=gun)).isoformat(timespec="seconds")
        with self._kilit, self.db:
            return self.db.execute("DELETE FROM ogr_olaylar WHERE zaman<? AND geri_bildirim<=0", (sinir,)).rowcount
