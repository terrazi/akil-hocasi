"""Gelişim döngüsü: test etme → ders sınama → strateji ayarı → benimseme / geri alma.

Ağır bir iştir (her soru tam iş akışıyla cevaplanır); yalnızca bilgisayar boştayken ve süre bütçesiyle çalışır.
Her karar gerekçesiyle cek_gelisim tablosuna yazılır.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from ..core.turkce import katla
from .dersler import DersHafizasi
from .karne import Karne, karne_hesapla, kapi
from .strateji import StratejiDeposu
from .yordamlar import YORDAMLAR

# Karnede zayıf olan ilkeye göre denenecek yordam ayarları (strateji ayarı yalnızca bunları dener)
ILKE_AYARLARI: dict[str, list[tuple[str, str]]] = {
    "dogruluk": [("sentez", "sicaklik"), ("secme", "sunulacak_kaynak"), ("duzeltme", "tur_siniri")],
    "muhakeme": [("tarama", "aday_sayisi"), ("yordama", "dusunme_kipi"), ("planlama", "derin_okuma")],
    "durum": [("netlestirme", "soru_siniri"), ("anlama", "alt_soru_siniri")],
    "cozum": [("tarama", "atif_derinligi"), ("bulma", "canli_arama"), ("yeniden_isleme", "acik")],
    "somutluk": [("sentez", "ornek_sayisi"), ("elestirme", "elestiri_esigi")],
    "guven": [("elestirme", "elestiri_esigi")],
}
GENEL_AYARLAR = [("tarama", "aday_sayisi"), ("tarama", "anlam_agirligi"), ("secme", "sunulacak_kaynak"),
                 ("sentez", "ornek_sayisi"), ("ders", "ders_siniri")]


class GelisimDongusu:
    def __init__(self, hat, kutuphane, strateji: StratejiDeposu, dersler: DersHafizasi,
                 bildir: Callable[[str], None] | None = None):
        self.hat, self.k, self.st, self.dersler = hat, kutuphane, strateji, dersler
        self.bildir = bildir or (lambda m: None)

    # ------------------------------------------------------------------ sınav
    def sinav_seti(self, sinir: int = 60) -> list[dict]:
        sorular = []
        for r in self.k.db.execute("SELECT * FROM ogr_altin").fetchall():
            sorular.append({"soru": r["soru"], "beklenen_dayanak": json.loads(r["beklenen_dayanak"] or "[]"),
                            "beklenen_ifade": r["beklenen_ifade"] or "", "kaynak": "altin"})
        try:
            for r in self.k.db.execute(
                    "SELECT * FROM yz_sentetik WHERE kullanim='sinav' AND durum='dogrulandi' ORDER BY id DESC LIMIT ?",
                    (max(0, sinir - len(sorular)),)).fetchall():
                sorular.append({"soru": r["soru"], "beklenen_dayanak": json.loads(r["dayanak"] or "[]"),
                                "beklenen_ifade": "", "kaynak": "sentetik"})
        except Exception:  # noqa: BLE001 - sentetik tablo henüz yoksa
            pass
        return sorular[:sinir]

    def sinav(self, sorular: list[dict], bitis: float | None = None, ders_kimligi: int | None = None) -> Karne:
        from ..ogrenme.degerlendirme import altin_sonucu
        sonuclar = []
        eski_ek = getattr(self.hat, "sinanan_ders", None)
        self.hat.sinanan_ders = ders_kimligi
        try:
            for s in sorular:
                if bitis and time.monotonic() > bitis:
                    break
                c = self.hat.cevapla(s["soru"], "derin", kayit=False)
                gecti, kritik = altin_sonucu(c, s.get("beklenen_dayanak", []), s.get("beklenen_ifade", ""))
                sonuclar.append((c, {"netlestirme": s.get("netlestirme", False)}, gecti, kritik))
        finally:
            self.hat.sinanan_ders = eski_ek
        return karne_hesapla(sonuclar)

    # ------------------------------------------------------------------ dersler
    def dersleri_sina(self, sorular: list[dict], bitis: float) -> list[str]:
        rapor = []
        for d in self.dersler.adaylar(5):
            if time.monotonic() > bitis:
                break
            kosul = json.loads(d["kosul"] or "[]")
            ilgili = [s for s in sorular if not kosul or any(t in katla(s["soru"]) for t in kosul)] or sorular
            ilgili = ilgili[:20]
            if len(ilgili) < 3:
                continue
            eski = self.sinav(ilgili, bitis)
            yeni = self.sinav(ilgili, bitis, ders_kimligi=d["id"])
            ok, gerekce = kapi(eski, yeni)
            self.dersler.karar(d["id"], "etkin" if ok else "reddedildi", gerekce)
            self.st.gelisim_yaz("ders", d["metin"], "benimsendi" if ok else "reddedildi", gerekce,
                                eski_karne=eski.sozluk(), yeni_karne=yeni.sozluk())
            rapor.append(f"Ders {'benimsendi' if ok else 'reddedildi'}: {d['metin'][:70]} ({gerekce})")
        return rapor

    # ------------------------------------------------------------------ strateji
    def strateji_dene(self, sorular: list[dict], karne: Karne, bitis: float, butce: int = 2) -> list[str]:
        if len(sorular) < 10:
            return ["Strateji ayarı için en az 10 sınav sorusu gerekir; atlandı"]
        zayif = sorted((k for k, n in karne.ornek.items() if n), key=lambda k: karne.notlar[k])
        denenecek: list[tuple[str, str]] = []
        for ilke in zayif:
            denenecek += [x for x in ILKE_AYARLARI.get(ilke, []) if x not in denenecek]
        denenecek += [x for x in GENEL_AYARLAR if x not in denenecek]
        rapor = []
        for yordam, ayar in denenecek:
            if butce <= 0 or time.monotonic() > bitis:
                break
            if self.st.kaynak(yordam, ayar) == "kullanici":
                continue
            eski_deger = self.st.deger(yordam, ayar)
            for aday in self.st.komsular(yordam, ayar):
                if butce <= 0 or time.monotonic() > bitis:
                    break
                butce -= 1
                with self.st.gecici({(yordam, ayar): aday}):
                    yeni = self.sinav(sorular, bitis)
                ok, gerekce = kapi(karne, yeni)
                konu = f"{yordam}.{ayar}"
                if ok:
                    self.st.ayarla(yordam, ayar, aday, "ogrenme")
                    self.st.gelisim_yaz("strateji", konu, "benimsendi", gerekce, eski_deger, aday,
                                        karne.sozluk(), yeni.sozluk())
                    rapor.append(f"Ayar benimsendi: {konu} {eski_deger} → {aday} ({gerekce})")
                    karne = yeni
                    break
                self.st.gelisim_yaz("strateji", konu, "reddedildi", gerekce, eski_deger, aday,
                                    karne.sozluk(), yeni.sozluk())
        return rapor or ["Denenen ayarların hiçbiri kapıdan geçmedi; mevcut ayarlar korunuyor"]

    # ------------------------------------------------------------------ geri alma
    def geri_alma_denetimi(self, guncel: Karne) -> list[str]:
        """Son benimsenen ayar değişikliği sonrası karne belirgin düştüyse o değişikliği geri al."""
        r = self.k.db.execute("SELECT * FROM cek_gelisim WHERE tur='strateji' AND karar='benimsendi'"
                              " ORDER BY id DESC LIMIT 1").fetchone()
        if not r:
            return []
        try:
            o_karne = json.loads(r["yeni_karne"] or "{}")
        except ValueError:
            return []
        if not o_karne or guncel.toplam < 10:
            return []
        if guncel.basari + 0.05 < o_karne.get("basari", 0) or guncel.kritik > o_karne.get("kritik", 0) + 1:
            yordam, ayar = r["konu"].split(".", 1)
            try:
                eski = json.loads(r["eski"])
                self.st.ayarla(yordam, ayar, eski, "ogrenme")
            except (ValueError, PermissionError):
                return []
            self.st.gelisim_yaz("geri_alma", r["konu"], "geri_alindi",
                                "Benimsendikten sonra başarı belirgin düştü", json.loads(r["yeni"]), eski,
                                o_karne, guncel.sozluk())
            return [f"Geri alındı: {r['konu']} (sonraki ölçümlerde başarı düştü)"]
        return []

    # ------------------------------------------------------------------ tam döngü
    def calistir(self, sure_dk: float = 45, durdur=None) -> list[str]:
        bitis = time.monotonic() + sure_dk * 60
        rapor: list[str] = []
        sorular = self.sinav_seti()
        if not sorular:
            return ["Sınav sorusu yok (altın set ya da doğrulanmış sentetik soru gerekli)"]
        self.bildir(f"Sınav: {len(sorular)} soru")
        karne = self.sinav(sorular, bitis)
        self.st.karne_yaz("genel", karne.sozluk())
        rapor.append(f"Karne: başarı {karne.basari:.0%}, ilke ortalaması {karne.ortalama():.2f}, kritik {karne.kritik}")
        rapor += self.geri_alma_denetimi(karne)
        if durdur is not None and durdur.is_set():
            return rapor
        self.bildir("Ders adayları sınanıyor")
        rapor += self.dersleri_sina(sorular, bitis)
        if durdur is not None and durdur.is_set():
            return rapor
        self.bildir("Yordam ayarları deneniyor")
        rapor += self.strateji_dene(sorular, karne, bitis)
        return rapor


def yordam_adlari() -> dict[str, str]:
    return {y.kod: y.ad for y in YORDAMLAR}
