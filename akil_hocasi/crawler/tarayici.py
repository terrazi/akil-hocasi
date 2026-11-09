"""Sürekli tarayıcı: zamanlanmış görevleri yürütür, belgeleri depoya ve kütüphaneye işler.

Döngü: keşfet → indir (koşullu) → ayrıştır → doğrula (beyaz liste, özet, tür) → dizinle
→ etki analizi (kütüphane bağımlıları işaretler) → bildir (değişiklik kaydı).
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable

from ..library.db import Kutuphane
from . import beyaz_liste
from .depo import BelgeDeposu, dosya_turu, metin_cikar
from .indirici import Indirici, IndirmeSonucu
from .kaynaklar import (CEKIRDEK_KANUNLAR, CEKIRDEK_YONETMELIKLER, Mevzuat, ResmiGazete, Togu,
                        mevzuat_metni_gecerli)

IlerlemeFn = Callable[[str], None]


@dataclass
class TaramaRaporu:
    gorev: str
    baslangic: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    bitis: str = ""
    yeni: int = 0
    guncellenen: int = 0
    degismeyen: int = 0
    hatalar: list[str] = field(default_factory=list)
    notlar: list[str] = field(default_factory=list)

    @property
    def ozet(self) -> str:
        return f"{self.yeni} yeni, {self.guncellenen} güncellenen, {self.degismeyen} değişmeyen"


class Tarayici:
    def __init__(self, kutuphane: Kutuphane, depo: BelgeDeposu, indirici: Indirici | None = None):
        self.kutuphane = kutuphane
        self.depo = depo
        self.indirici = indirici or Indirici()
        self.rg = ResmiGazete()
        self.mevzuat = Mevzuat()
        self.togu = Togu()
        self.durdur = threading.Event()

    # ------------------------------------------------------------------ yardımcılar
    def _getir(self, url: str, rapor: TaramaRaporu, kosullu: bool = True) -> IndirmeSonucu:
        onceki = self.kutuphane.kaynak_durumu(url) if kosullu else None
        s = self.indirici.getir(url, etag=(onceki["etag"] if onceki else ""),
                                last_modified=(onceki["last_modified"] if onceki else ""))
        if s.degismedi:
            rapor.degismeyen += 1
            self.kutuphane.kaynak_durumu_yaz(url, s.etag, s.last_modified)
        elif s.basarili:
            if onceki and onceki["sha256"] == s.sha256:
                rapor.degismeyen += 1
            self.kutuphane.kaynak_durumu_yaz(url, s.etag, s.last_modified, s.sha256)
        elif s.hata:
            rapor.hatalar.append(f"{url}: {s.hata}")
        return s

    def belge_isle(self, s: IndirmeSonucu, rapor: TaramaRaporu, *, tur: str, kimlik: str, baslik: str,
                   kaynak_turu: str, kod: str = "", rv: str = "", birim: str = "", sayfa_url: str = "") -> str:
        """İndirilen içeriği depoya (dosyaysa) ve kütüphaneye (metin çıkarsa) işler."""
        dt = dosya_turu(s.icerik)
        dosya_yolu = ""
        if dt and dt != "html":
            kayit = self.depo.kaydet(s.icerik, s.url, kod=kod, ad=baslik, sayfa_url=sayfa_url, birim=birim, rv=rv)
            dosya_yolu = kayit["dosya_yolu"] if kayit else ""
        metin = metin_cikar(s.icerik, dt)
        if not metin.strip():
            rapor.notlar.append(f"Metin çıkarılamadı (yalnızca depoya alındı): {baslik}")
            return "metin_yok"
        sonuc = self.kutuphane.belge_kaydet(
            tur=tur, kimlik=kimlik, baslik=baslik, metin=metin, sha256=s.sha256, kaynak_url=s.url,
            kaynak_turu=kaynak_turu, birim=birim, rv=rv, dosya_yolu=dosya_yolu)
        if sonuc == "yeni":
            rapor.yeni += 1
        elif sonuc == "guncellendi":
            rapor.guncellenen += 1
        else:
            rapor.degismeyen += 1
        return sonuc

    # ------------------------------------------------------------------ görevler
    def calistir(self, gorev: str, ilerleme: IlerlemeFn | None = None) -> TaramaRaporu:
        rapor = TaramaRaporu(gorev)
        bildir = ilerleme or (lambda m: None)
        try:
            if gorev == "hafif":
                self._hafif(rapor, bildir)
            elif gorev == "gece":
                self._resmi_gazete(date.today(), rapor, bildir)
            elif gorev == "derin":
                self._derin(rapor, bildir)
            elif gorev == "haftalik":
                self._cekirdek_mevzuat(rapor, bildir)
            elif gorev == "sabah":
                rapor.notlar.append("Özet yerel değişiklik kaydından hazırlandı")
        except Exception as e:  # tarama hiçbir zaman programı düşürmemeli
            rapor.hatalar.append(f"{gorev}: {e}")
        rapor.bitis = datetime.now().isoformat(timespec="seconds")
        self.kutuphane.zamanlayici_yaz(gorev, rapor.bitis)
        return rapor

    def _hafif(self, rapor: TaramaRaporu, bildir: IlerlemeFn) -> None:
        bildir("Resmî Gazete'de yeni sayı kontrol ediliyor")
        bugun = date.today()
        for mukerrer in (0, 1, 2):
            url = self.rg.gunluk_url(bugun, mukerrer)
            s = self._getir(url, rapor)
            if s.basarili:
                self._rg_fihristi_isle(s, bugun, rapor)
            elif mukerrer and not s.degismedi:
                break
        bildir("TOGÜ kalite belgeleri listesi kontrol ediliyor")
        s = self._getir(self.togu.KALITE, rapor)
        if s.basarili:
            self._kalite_listesi_isle(s.icerik, rapor, bildir, sinir=25)

    def _resmi_gazete(self, g: date, rapor: TaramaRaporu, bildir: IlerlemeFn) -> None:
        for mukerrer in (0, 1, 2, 3):
            url = self.rg.gunluk_url(g, mukerrer)
            bildir(f"Resmî Gazete {g:%d.%m.%Y}" + (f" mükerrer {mukerrer}" if mukerrer else ""))
            s = self._getir(url, rapor, kosullu=False)
            if not s.basarili:
                if mukerrer:
                    break
                continue
            self._rg_fihristi_isle(s, g, rapor)

    def _rg_fihristi_isle(self, s: IndirmeSonucu, g: date, rapor: TaramaRaporu) -> None:
        for b in self.rg.maddeleri(s.icerik, s.url):
            if self.durdur.is_set():
                return
            if not self.rg.ilgili_mi(b.baslik):
                continue
            ds = self._getir(b.url, rapor)
            if ds.basarili:
                slug = re.sub(r"\W+", "-", b.url.rsplit("/", 1)[-1]).strip("-")
                self.belge_isle(ds, rapor, tur="rg", kimlik=f"RG:{g.isoformat()}:{slug}",
                                baslik=f"Resmî Gazete {g:%d.%m.%Y} — {b.baslik[:140]}",
                                kaynak_turu="Mevzuat", sayfa_url=s.url)

    def _kalite_listesi_isle(self, html: bytes, rapor: TaramaRaporu, bildir: IlerlemeFn, sinir: int = 0) -> None:
        belgeler = self.togu.kalite_belgeleri(html)
        islenen = 0
        for b in belgeler:
            if self.durdur.is_set() or (sinir and islenen >= sinir):
                break
            onceki = self.kutuphane.kaynak_durumu(b.url)
            if sinir and onceki:      # hafif kontrolde yalnızca yeni bağlantılar
                continue
            bildir(f"İndiriliyor: {b.kod or b.baslik[:50]}")
            ds = self._getir(b.url, rapor)
            islenen += 1
            if ds.basarili:
                self.belge_isle(ds, rapor, tur="togu", kimlik=b.kod or b.url, baslik=b.baslik or b.kod,
                                kaynak_turu="TOGÜ belgesi", kod=b.kod, rv=b.rv, sayfa_url=b.sayfa_url)

    def _derin(self, rapor: TaramaRaporu, bildir: IlerlemeFn) -> None:
        bildir("TOGÜ kalite belgeleri (tamamı) taranıyor")
        s = self._getir(self.togu.KALITE, rapor, kosullu=False)
        if s.basarili:
            self._kalite_listesi_isle(s.icerik, rapor, bildir)
        for birim in self.togu.BIRIMLER:
            if self.durdur.is_set():
                return
            ana = self.togu.birim_ana_sayfasi(birim)
            bildir(f"{birim}.gop.edu.tr taranıyor")
            s = self._getir(ana, rapor, kosullu=False)
            if not s.basarili:
                continue
            for liste in self.togu.liste_sayfalari(s.icerik, ana):
                ls = self._getir(liste, rapor, kosullu=False)
                if not ls.basarili:
                    continue
                from .kaynaklar import baglantilari_cikar
                for b in baglantilari_cikar(ls.icerik, liste, sadece_dosya=True):
                    if self.durdur.is_set():
                        return
                    if not beyaz_liste.birincil_mi(b.url):
                        continue
                    ds = self._getir(b.url, rapor)
                    if ds.basarili:
                        self.belge_isle(ds, rapor, tur="togu", kimlik=b.kod or b.url,
                                        baslik=b.baslik or b.kod or b.url.rsplit("/", 1)[-1],
                                        kaynak_turu="TOGÜ belgesi", kod=b.kod, rv=b.rv, birim=birim,
                                        sayfa_url=liste)
        self._cekirdek_mevzuat(rapor, bildir)

    def _cekirdek_mevzuat(self, rapor: TaramaRaporu, bildir: IlerlemeFn, sadece: list[str] | None = None) -> None:
        for no, ad in CEKIRDEK_KANUNLAR:
            if sadece and no not in sadece:
                continue
            if self.durdur.is_set():
                return
            bildir(f"{no} sayılı {ad} kontrol ediliyor")
            for url in self.mevzuat.kanun_adaylari(no):
                s = self._getir(url, rapor)
                if s.degismedi:
                    break
                if s.basarili and dosya_turu(s.icerik) in ("pdf", "doc", "docx", "html"):
                    if not mevzuat_metni_gecerli(metin_cikar(s.icerik, dosya_turu(s.icerik)), no):
                        continue                    # genel sayfa ya da başka metin: sıradaki adres denenir
                    self.belge_isle(s, rapor, tur="kanun", kimlik=no, baslik=f"{no} sayılı {ad}",
                                    kaynak_turu="Mevzuat")
                    break
        for no, ad, tur, tertip in CEKIRDEK_YONETMELIKLER:
            if sadece and no not in sadece:
                continue
            if self.durdur.is_set():
                return
            bildir(f"{ad} kontrol ediliyor")
            for url in self.mevzuat.metin_adaylari(no, tur, tertip):
                s = self._getir(url, rapor)
                if s.degismedi:
                    break
                if s.basarili and dosya_turu(s.icerik) in ("pdf", "doc", "docx", "html"):
                    if not mevzuat_metni_gecerli(metin_cikar(s.icerik, dosya_turu(s.icerik)), no):
                        continue
                    self.belge_isle(s, rapor, tur="yonetmelik", kimlik=f"MEV:{tur}.{tertip}.{no}", baslik=ad,
                                    kaynak_turu="Mevzuat")
                    break


class HedefliSaglayici:
    """Cevap hattının 4. basamağı: soruda geçen ama kütüphanede olmayan kanunu veya TOGÜ belgesini getirir."""
    ad = "Hedefli resmî kaynak araması"
    _KANUN = re.compile(r"\b(\d{3,4})\s*sayılı")

    def __init__(self, tarayici: Tarayici):
        self.tarayici = tarayici

    def ara(self, soru: str, terimler: list[str]) -> int:
        rapor = TaramaRaporu("hedefli")
        bilinen = {no for no, _ in CEKIRDEK_KANUNLAR}
        istenen = [no for no in self._KANUN.findall(soru) if no in bilinen
                   and not self.tarayici.kutuphane.belge_bilgisi(no)]
        if istenen:
            self.tarayici._cekirdek_mevzuat(rapor, lambda m: None, sadece=istenen)
        kodlar = re.findall(r"\b(?:TOGÜ\.)?(?:FRM|YÖN|USE|PRS)\.\d{3}\b", soru)
        eksik = [k for k in kodlar if not self.tarayici.kutuphane.belge_bilgisi(
            k if k.startswith("TOGÜ") else f"TOGÜ.{k}")]
        if eksik:
            s = self.tarayici._getir(self.tarayici.togu.KALITE, rapor, kosullu=False)
            if s.basarili:
                for b in self.tarayici.togu.kalite_belgeleri(s.icerik):
                    if b.kod and any(b.kod.endswith(k.replace("TOGÜ.", "")) for k in eksik):
                        ds = self.tarayici._getir(b.url, rapor)
                        if ds.basarili:
                            self.tarayici.belge_isle(ds, rapor, tur="togu", kimlik=b.kod, baslik=b.baslik,
                                                     kaynak_turu="TOGÜ belgesi", kod=b.kod, rv=b.rv)
        return rapor.yeni + rapor.guncellenen
