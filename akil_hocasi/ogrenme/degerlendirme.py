"""Gece öz değerlendirmesi: program kendini sınar, öğrendiklerini doğrular ve kendini eğitir.

Adımlar:
 1 Soru-cevap bankasını güncel kütüphaneyle yeniden doğrula (tutmayanı askıya al)
 2 Altın soru setinde başarıyı ölç; düşüş varsa uyar
 3 Öğrenen sıralayıcıyı yeniden eğit (yalnızca iyileşirse devreye girer)
 4 Bilgi boşluklarını çıkar (tarayıcıya ve birim uzmanlarına yön verir)
 5 Gizlilik: süresi dolan olayları sil
 6 Paylaşım klasörü varsa öğrenme paketlerini eşitle
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from ..core.turkce import katla
from .motor import kaynak_anahtari


def altin_sonucu(cevap, beklenen_dayanak: list[str], beklenen_ifade: str) -> tuple[bool, bool]:
    """(geçti_mi, kritik_mi). Kritik: program 'Doğrulandı' dediği halde beklenen cevabı vermedi."""
    anahtarlar = {kaynak_anahtari(k.pasaj.belge_kimlik, k.pasaj.madde_no) for k in cevap.kaynaklar}
    belgeler = {k.pasaj.belge_kimlik for k in cevap.kaynaklar}
    dayanak_ok = not beklenen_dayanak or any(d in anahtarlar or d in belgeler for d in beklenen_dayanak)
    metin = katla(" ".join(c.metin for c in cevap.tum_cumleler()))
    ifade_ok = not beklenen_ifade or katla(beklenen_ifade) in metin
    gecti = cevap.durum.value != "Doğrudan hüküm yok" and dayanak_ok and ifade_ok
    kritik = cevap.durum.value == "Doğrulandı" and not gecti
    return gecti, kritik


def altin_seti_olc(hat, kutuphane, model_adi: str = "") -> dict:
    sonuc = {"toplam": 0, "gecen": 0, "kritik": 0, "kalanlar": []}
    for r in kutuphane.db.execute("SELECT * FROM ogr_altin").fetchall():
        c = hat.cevapla(r["soru"], "derin", kayit=False)
        gecti, kritik = altin_sonucu(c, json.loads(r["beklenen_dayanak"] or "[]"), r["beklenen_ifade"] or "")
        sonuc["toplam"] += 1
        sonuc["gecen"] += int(gecti)
        sonuc["kritik"] += int(kritik)
        if not gecti:
            sonuc["kalanlar"].append(r["soru"])
    sonuc["model"] = model_adi
    return sonuc


class GeceDegerlendirmesi:
    def __init__(self, hat, kutuphane, ogrenme, siralayici=None, paylasim_klasoru: str = "", gecmis_gun: int = 30):
        self.hat, self.k, self.ogr, self.sir = hat, kutuphane, ogrenme, siralayici
        self.paylasim_klasoru = paylasim_klasoru
        self.gecmis_gun = gecmis_gun

    def _kaydet(self, tur: str, ozet: str) -> None:
        with self.k.db:
            self.k.db.execute("INSERT INTO degisiklikler(zaman, belge_kimlik, tur, ozet) VALUES(?,?,?,?)",
                              (datetime.now().isoformat(timespec="microseconds"), "Öğrenme", tur, ozet))

    def calistir(self, en_fazla_soru_cevap: int = 50) -> list[str]:
        rapor: list[str] = []

        def adim(ad: str, fn) -> None:
            try:
                sonuc = fn()
                if sonuc:
                    rapor.append(f"{ad}: {sonuc}")
            except Exception as e:  # bir adımın hatası diğerlerini durdurmaz
                rapor.append(f"{ad}: HATA {e}")

        adim("Soru-cevap bankası", lambda: self._bankayi_dogrula(en_fazla_soru_cevap))
        adim("Altın set", self._altin_set)
        if self.sir is not None:
            adim("Öğrenen sıralayıcı", self._siralayici)
        adim("Bilgi boşlukları", self._bosluklar)
        adim("Gizlilik", lambda: f"{self.ogr.gecmisi_temizle(self.gecmis_gun)} eski olay silindi")
        if self.paylasim_klasoru:
            from .paket import esitle
            adim("Paylaşım", lambda: esitle(self.ogr, self.paylasim_klasoru))
        return rapor

    def _bankayi_dogrula(self, sinir: int) -> str:
        eski = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
        satirlar = self.k.db.execute(
            "SELECT * FROM soru_cevap WHERE durum='yeniden_dogrulanacak' OR dogrulama_tarihi < ? LIMIT ?",
            (eski, sinir)).fetchall()
        tutan = askiya = 0
        for r in satirlar:
            c = self.hat.cevapla(r["soru"], "hizli", kayit=False)
            dayanak = set(json.loads(r["dayanak"]))
            anahtarlar = {kaynak_anahtari(k.pasaj.belge_kimlik, k.pasaj.madde_no) for k in c.kaynaklar}
            with self.k.db:
                if c.durum.value == "Doğrulandı" and dayanak & anahtarlar:
                    self.k.db.execute("UPDATE soru_cevap SET durum='dogrulandi', dogrulama_tarihi=? WHERE id=?",
                                      (datetime.now().isoformat(timespec="seconds"), r["id"]))
                    tutan += 1
                else:
                    self.k.db.execute("UPDATE soru_cevap SET durum='askida' WHERE id=?", (r["id"],))
                    askiya += 1
        if askiya:
            self._kaydet("inceleme", f"{askiya} soru-cevap güncel mevzuatla doğrulanamadı ve askıya alındı")
        return f"{tutan} yeniden doğrulandı, {askiya} askıya alındı" if satirlar else ""

    def _altin_set(self) -> str:
        sonuc = altin_seti_olc(self.hat, self.k, getattr(self.hat.model, "ad", ""))
        if not sonuc["toplam"]:
            return "altın soru seti henüz yok"
        onceki = self.k.db.execute("SELECT * FROM ogr_degerlendirme ORDER BY id DESC LIMIT 1").fetchone()
        with self.k.db:
            self.k.db.execute(
                "INSERT INTO ogr_degerlendirme(zaman, toplam, gecen, kritik, model, ayrinti) VALUES(?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), sonuc["toplam"], sonuc["gecen"], sonuc["kritik"],
                 sonuc["model"], json.dumps({"kalanlar": sonuc["kalanlar"][:50]}, ensure_ascii=False)))
        oran = sonuc["gecen"] / sonuc["toplam"]
        metin = f"%{oran * 100:.0f} başarı ({sonuc['gecen']}/{sonuc['toplam']}), kritik hata {sonuc['kritik']}"
        if onceki and onceki["toplam"]:
            onceki_oran = onceki["gecen"] / onceki["toplam"]
            if oran + 1e-9 < onceki_oran or sonuc["kritik"] > onceki["kritik"]:
                self._kaydet("inceleme", f"Altın set başarısı düştü: %{onceki_oran * 100:.0f} → %{oran * 100:.0f}")
        return metin

    def _siralayici(self) -> str:
        r = self.sir.egit()
        if r is None:
            return "eğitim için henüz yeterli veri yok"
        self._kaydet("ogrenme", r.ozet)
        return r.ozet

    def _bosluklar(self) -> str:
        b = self.ogr.bilgi_bosluklari()
        return ", ".join(f"{x['terim']} ({x['sayi']})" for x in b) if b else ""
