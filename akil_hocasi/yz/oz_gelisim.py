"""Gece YZ çalışması — Yordam Kitabı'nın Öğrenme grubunun yürütülmesi (bilgisayar boştayken, prizdeyken).

Sıra (süre bütçesiyle; durdurulursa kalan iş sonraki boş zamana kalır):
  1 Anlam dizinini tamamla (yeni ve değişen maddeler)
  2 Sentetik soru üret ve doğrula (kütüphaneden; bir payı sınava, kalanı eğitime)
  3 Hatalardan ders adayı çıkar (sınamada çıkarılan cümleler)
  4 Gelişim döngüsü: sınav → ders sınama → strateji ayarı → geri alma denetimi
  5 Model gelişimi: katalogda daha iyi aday varsa indir (izinliyse) ve yarıştır
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime

from ..cekirdek.ilkeler import sistem_cekirdegi
from ..core.turkce import katla

SEMA = """
CREATE TABLE IF NOT EXISTS yz_sentetik (
    id INTEGER PRIMARY KEY, madde_id INTEGER NOT NULL, soru TEXT NOT NULL UNIQUE, dayanak TEXT NOT NULL,
    kullanim TEXT NOT NULL, durum TEXT NOT NULL, olusturma TEXT NOT NULL
);
"""

SORU_SEMASI = {"type": "object", "properties": {"sorular": {"type": "array", "maxItems": 2, "items": {
    "type": "object", "properties": {"soru": {"type": "string"}}, "required": ["soru"]}}}, "required": ["sorular"]}
SORU_GOREVI = (
    "Aşağıdaki mevzuat maddesini oku. Bir üniversitenin idari personelinin (personel, maaş, satın alma, yazı işleri "
    "vb.) bu maddeyle cevaplanabilecek, gerçek hayatta sorabileceği en fazla iki soru yaz. Soruyu günlük dille, "
    "durum anlatarak sor; kanun numarası, madde numarası ve maddenin cümlelerini kopyalama. Madde idari personeli "
    "ilgilendirmiyorsa boş liste döndür.")


def _kapsama(soru: str, metin: str) -> float:
    terimler = [t for t in re.findall(r"[a-z]{4,}", katla(soru))]
    if not terimler:
        return 0.0
    hedef = katla(metin)
    return sum(1 for t in terimler if t[:5] in hedef) / len(terimler)


class GeceZekaCalismasi:
    def __init__(self, s, bildir=None):
        self.s = s
        self.k = s.kutuphane
        self.bildir = bildir or (lambda m: None)
        with self.k._kilit, self.k.db:
            self.k.db.executescript(SEMA)

    # ------------------------------------------------------------------ 1 anlam dizini
    def anlam_dizini(self, bitis: float, durdur=None) -> str:
        a = self.s.yz.anlam
        if not a.hazir:
            return "Anlam modeli çalışmıyor; dizin atlandı"
        toplam = 0
        while time.monotonic() < bitis and not (durdur and durdur.is_set()):
            n = a.eksikleri_isle(256, durdur)
            toplam += n
            if n == 0:
                break
        hazir, tum = a.ilerleme()
        return f"Anlam dizini: {toplam} madde işlendi ({hazir}/{tum})"

    # ------------------------------------------------------------------ 2 sentetik sorular
    def sentetik_uret(self, sinir: int, bitis: float, durdur=None) -> str:
        model = self.s.hat.model
        if not model.hazir:
            return "Dil modeli yok; sentetik soru üretilmedi"
        satirlar = self.k.db.execute(
            "SELECT m.id, m.madde_no, m.baslik, m.metin, b.kimlik, b.baslik AS belge FROM maddeler m"
            " JOIN belgeler b ON b.id=m.belge_id WHERE m.yururluk_bitis IS NULL AND m.mulga=0"
            " AND length(m.metin) > 120 AND b.tur IN ('kanun','yonetmelik','togu','rg')"
            " AND m.id NOT IN (SELECT madde_id FROM yz_sentetik) ORDER BY RANDOM() LIMIT ?", (sinir,)).fetchall()
        eklenen = 0
        from ..answer.llm import json_cikar
        for r in satirlar:
            if time.monotonic() > bitis or (durdur and durdur.is_set()):
                break
            try:
                cikti = model.sohbet(
                    [{"role": "system", "content": sistem_cekirdegi(SORU_GOREVI)},
                     {"role": "user", "content": f"{r['belge']} — madde {r['madde_no']} {r['baslik'] or ''}\n{r['metin'][:2000]}"}],
                    max_tokens=300, sicaklik=0.5, json_mod=True, json_sema=SORU_SEMASI)
            except Exception:  # noqa: BLE001
                continue
            for q in (json_cikar(cikti) or {}).get("sorular", [])[:2]:
                soru = str(q.get("soru", "")).strip()
                gecerli = 15 <= len(soru) <= 300 and _kapsama(soru, r["metin"] + " " + (r["baslik"] or "")) >= 0.25
                kullanim = "sinav" if int(hashlib.md5(soru.encode()).hexdigest(), 16) % 3 == 0 else "egitim"
                try:
                    with self.k._kilit, self.k.db:
                        self.k.db.execute(
                            "INSERT INTO yz_sentetik(madde_id, soru, dayanak, kullanim, durum, olusturma)"
                            " VALUES(?,?,?,?,?,?)",
                            (r["id"], soru, json.dumps([f"{r['kimlik']}/{r['madde_no']}"], ensure_ascii=False), kullanim,
                             "dogrulandi" if gecerli else "red", datetime.now().isoformat(timespec="seconds")))
                    eklenen += int(gecerli)
                except Exception:  # noqa: BLE001 - aynı soru tekrarı
                    continue
        return f"Sentetik soru: {eklenen} doğrulanmış soru eklendi"

    # ------------------------------------------------------------------ 3 dersler
    def ders_cikar(self, bitis: float) -> str:
        n = 0
        for h in self.s.dersler.islenmemis_hatalar(8):
            if time.monotonic() > bitis:
                break
            n += len(self.s.dersler.hatadan_cikar(self.s.hat.model, h["soru"], json.loads(h["hatalar"])))
            self.s.dersler.hata_islendi(h["id"])
        return f"Ders adayı: {n}"

    # ------------------------------------------------------------------ 5 model yarışı
    def model_gelisimi(self, gelisim, bitis: float, durdur=None) -> list[str]:
        yz = self.s.yz
        from .donanim import bellek_gb, prizde_mi
        mevcut = yz.secili("sohbet")
        adaylar = yz.katalog.yarisma_adaylari("sohbet", bellek_gb()[0], mevcut["kimlik"] if mevcut else None)
        if not adaylar:
            return ["Model yarışı: bu bilgisayar için daha iyi aday yok"]
        kurulu = {m["kimlik"] for m in yz.kurulu()}
        aday = adaylar[0]
        rapor = []
        if aday.kimlik not in kurulu:
            if not self.s.ayarlar.al("yz.kendini_gelistir", True) or prizde_mi() is False:
                return [f"Model yarışı: {aday.ad} adayı var; indirme için uygun zaman bekleniyor"]
            self.bildir(f"Aday model indiriliyor: {aday.ad}")
            try:
                yz.indir(aday.kimlik, durdur=durdur)
            except Exception as e:  # noqa: BLE001 - indirme sonraki gece sürer
                return [f"Model yarışı: aday indirilemedi ({e})"]
            rapor.append(f"Aday model indirildi: {aday.ad}")
        if time.monotonic() > bitis:
            return rapor + ["Model yarışı süre yetmediği için sonraki geceye kaldı"]
        self.bildir(f"Model yarışı: {aday.ad}")
        ok, gerekce = yz.yaris(gelisim, self.s.hat, aday.kimlik, bitis)
        return rapor + [f"Model yarışı ({aday.ad}): {'kazandı, devreye alındı' if ok else 'mevcut model korundu'} — {gerekce}"]

    # ------------------------------------------------------------------ tam çalışma
    def calistir(self, sure_dk: float = 45, durdur=None) -> list[str]:
        from ..cekirdek.gelisim import GelisimDongusu
        bitis = time.monotonic() + sure_dk * 60
        rapor: list[str] = []

        def adim(ad: str, fn):
            if durdur is not None and durdur.is_set():
                return
            self.bildir(ad)
            try:
                sonuc = fn()
                rapor.extend(sonuc if isinstance(sonuc, list) else [sonuc])
            except Exception as e:  # noqa: BLE001 - bir adımın hatası diğerlerini durdurmaz
                rapor.append(f"{ad}: HATA {e}")

        adim("Anlam dizini", lambda: self.anlam_dizini(time.monotonic() + sure_dk * 60 * 0.25, durdur))
        adim("Sentetik sorular", lambda: self.sentetik_uret(24, time.monotonic() + sure_dk * 60 * 0.2, durdur))
        adim("Dersler", lambda: self.ders_cikar(time.monotonic() + sure_dk * 60 * 0.1))
        gelisim = GelisimDongusu(self.s.hat, self.k, self.s.strateji, self.s.dersler, self.bildir)
        kalan = max(1.0, (bitis - time.monotonic()) / 60)
        adim("Gelişim döngüsü", lambda: gelisim.calistir(kalan * 0.7, durdur))
        if self.s.ayarlar.al("yz.kendini_gelistir", True):
            adim("Model gelişimi", lambda: self.model_gelisimi(gelisim, bitis, durdur))
        return rapor
