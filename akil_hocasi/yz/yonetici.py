"""YZ yöneticisi: modellerin kurulumu, seçimi, başlatılması ve yarışı.

- Bilgisayarın belleğine göre önerilen sohbet ve anlam modelini belirler.
- Kurulu modelleri (model klasöründeki doğrulanmış dosyalar) listeler; seçili olanı llama-server ile başlatır.
- Yarış: aday model aynı sınavda mevcut modelle karşılaştırılır, kapıdan geçerse seçili model olur.
- llama-server yoksa (geliştirme ortamı) eski llama-cpp-python yoluna düşer; o da yoksa alıntıya dayalı mod.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path

from ..answer.llm import BosModel, model_yukle
from .anlam import VARSAYILAN_TALIMAT, AnlamDizini
from .donanim import bellek_gb, ozet
from .indirici import ModelIndirici, kurulu_modeller
from .katalog import Katalog, ModelTanimi
from .sunucu import LlamaSunucusu, ModelHatasi, SunucuModeli, env_model_klasoru, sunucu_exe

log = logging.getLogger("akilhocasi")


class YZYoneticisi:
    def __init__(self, yollar, ayarlar, kutuphane):
        self.yollar, self.ayarlar, self.k = yollar, ayarlar, kutuphane
        katalog_dosyasi = Path(yollar.kok) / "yz_katalog.json"
        self.katalog = Katalog(katalog_dosyasi.read_text("utf-8") if katalog_dosyasi.is_file() else None)
        self.indirici = ModelIndirici(self.model_klasoru(), ayarlar.al("yz.ayna", ""), ayarlar.al("yz.ortak_klasor", ""))
        self.sohbet_sunucusu: LlamaSunucusu | None = None
        self.anlam_sunucusu: LlamaSunucusu | None = None
        self.model = BosModel()
        self.anlam = AnlamDizini(kutuphane)
        self.son_hata = ""
        self._kilit = threading.RLock()

    def model_klasoru(self) -> Path:
        return Path(env_model_klasoru() or self.ayarlar.al("yz.model_klasoru", "") or self.yollar.modeller)

    # ------------------------------------------------------------------ bilgi
    def kurulu(self) -> list[dict]:
        return kurulu_modeller(self.model_klasoru())

    def onerilen(self, tur: str) -> ModelTanimi | None:
        return self.katalog.onerilen(tur, bellek_gb()[0])

    def secili(self, tur: str) -> dict | None:
        kurulu = [m for m in self.kurulu() if m.get("tur") == tur]
        if not kurulu:
            return None
        tercih = self.ayarlar.al(f"yz.{tur}_modeli", "")
        for m in kurulu:
            if m["kimlik"] == tercih:
                return m

        def oncelik(m):
            t = self.katalog.getir(m["kimlik"])
            if t:
                return t.oncelik
            if (m.get("yerel_sinav") or {}).get("sonuc") == "reddedildi":
                return 0                              # bu bilgisayardaki sınavda temel modelden kötü çıktı
            return int(m.get("oncelik", 0))           # katalog dışı (ör. Kaggle'da eğitilmiş) model

        def bellek_yeter(m):
            t = self.katalog.getir(m["kimlik"])
            gerek = t.en_az_bellek_gb if t else float(m.get("en_az_bellek_gb", 0))
            return gerek <= bellek_gb()[0] + 0.5
        uygun = [m for m in kurulu if bellek_yeter(m)]
        return max(uygun or kurulu, key=oncelik)

    def ozel_modeller(self) -> list[dict]:
        """Katalog dışı kurulu modeller (Kaggle'da eğitilmiş ya da elle eklenmiş)."""
        return [m for m in self.kurulu() if self.katalog.getir(m["kimlik"]) is None]

    def ozel_model_ekle(self, gguf: str | Path) -> dict:
        """Eğitilmiş GGUF modelini (yanındaki aynı adlı .json üst bilgisiyle) model klasörüne ekler."""
        import shutil
        kaynak = Path(gguf)
        with open(kaynak, "rb") as f:
            if f.read(4) != b"GGUF":
                raise ModelHatasi("Seçilen dosya GGUF model dosyası değil")
        bilgi = {}
        js = kaynak.with_suffix(".json")
        if js.is_file():
            try:
                bilgi = json.loads(js.read_text(encoding="utf-8"))
            except ValueError:
                bilgi = {}
        kimlik = re.sub(r"[^a-z0-9._-]+", "-", str(bilgi.get("kimlik") or kaynak.stem).lower()).strip("-")[:60]
        if self.katalog.getir(kimlik):
            kimlik += "-ozel"
        bilgi.update({"kimlik": kimlik, "tur": bilgi.get("tur", "sohbet"), "ad": bilgi.get("ad") or kaynak.stem,
                      "baglam": int(bilgi.get("baglam", 8192)), "dusunme": bool(bilgi.get("dusunme", False)),
                      "dosya": f"{kimlik}.gguf", "boyut": kaynak.stat().st_size, "kaynak": bilgi.get("kaynak", "elle"),
                      "eklenme": datetime.now().isoformat(timespec="seconds")})
        bilgi.setdefault("oncelik", 75 if (bilgi.get("egitim") or {}).get("kapi") else 40)
        hedef = self.model_klasoru() / f"{kimlik}.gguf"
        if kaynak.resolve() != hedef.resolve():
            shutil.copy2(kaynak, hedef)
        hedef.with_suffix(".json").write_text(json.dumps(bilgi, ensure_ascii=False, indent=1), encoding="utf-8")
        bilgi["yol"] = str(hedef)
        return bilgi

    def ust_bilgi_guncelle(self, kimlik: str, **alanlar) -> None:
        for m in self.kurulu():
            if m["kimlik"] == kimlik:
                js = Path(m["yol"]).with_suffix(".json")
                veri = json.loads(js.read_text(encoding="utf-8"))
                veri.update(alanlar)
                js.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")

    def _sohbet_secimi(self) -> dict | None:
        """Kullanıcının elle seçtiği GGUF dosyası (Ayarlar) önceliklidir; yoksa katalogdan kurulu en uygun model."""
        ozel = self.ayarlar.al("llm.model_yolu", "")
        if ozel and Path(ozel).is_file():
            return {"kimlik": "ozel", "ad": Path(ozel).stem, "tur": "sohbet", "yol": ozel, "baglam": 8192,
                    "dusunme": False}
        return self.secili("sohbet")

    def eksik_kurulum(self) -> list[ModelTanimi]:
        eksik = []
        for tur in ("sohbet", "anlam"):
            if self.secili(tur) is None:
                m = self.onerilen(tur)
                if m:
                    eksik.append(m)
        return eksik

    def durum(self) -> dict:
        s = self._sohbet_secimi()
        a = self.secili("anlam")
        return {
            "donanim": ozet(), "sunucu_var": bool(sunucu_exe(self.ayarlar.al("yz.sunucu_yolu", ""))),
            "sohbet": s, "anlam": a, "sohbet_calisiyor": bool(self.sohbet_sunucusu and self.sohbet_sunucusu.calisiyor()),
            "anlam_calisiyor": bool(self.anlam_sunucusu and self.anlam_sunucusu.calisiyor()),
            "model_adi": self.model.ad, "hazir": self.model.hazir, "son_hata": self.son_hata,
            "anlam_ilerleme": self.anlam.ilerleme() if self.anlam.hazir else (0, 0),
            "onerilen": {t: (m.kimlik if (m := self.onerilen(t)) else None) for t in ("sohbet", "anlam")},
            "olcum": getattr(self.model, "olcum", {}),
        }

    # ------------------------------------------------------------------ kurulum
    def indir(self, kimlik: str, ilerleme=None, durdur: threading.Event | None = None) -> Path:
        m = self.katalog.getir(kimlik)
        if m is None:
            raise ModelHatasi(f"Katalogda olmayan model: {kimlik}")
        return self.indirici.indir(m, ilerleme, durdur)

    def sil(self, kimlik: str) -> bool:
        for m in self.kurulu():
            if m["kimlik"] == kimlik:
                if self.secili(m["tur"]) and self.secili(m["tur"])["kimlik"] == kimlik and self._calisiyor(m["tur"]):
                    raise ModelHatasi("Çalışan model silinemez; önce başka bir model seçin")
                Path(m["yol"]).unlink(missing_ok=True)
                Path(m["yol"]).with_suffix(".json").unlink(missing_ok=True)
                return True
        return False

    def _calisiyor(self, tur: str) -> bool:
        s = self.sohbet_sunucusu if tur == "sohbet" else self.anlam_sunucusu
        return bool(s and s.calisiyor())

    # ------------------------------------------------------------------ çalıştırma
    def baslat(self, ilerleme=None) -> dict:
        """Seçili modelleri başlatır (zaten çalışıyorsa dokunmaz)."""
        with self._kilit:
            self.son_hata = ""
            exe = sunucu_exe(self.ayarlar.al("yz.sunucu_yolu", ""))
            baglam = int(self.ayarlar.al("llm.baglam", 8192))
            is_parcacigi = int(self.ayarlar.al("llm.is_parcacigi", 0))
            a = self.secili("anlam")
            if exe and a and not self._calisiyor("anlam"):
                try:
                    if ilerleme:
                        ilerleme("Anlam modeli başlatılıyor")
                    sunucu = LlamaSunucusu(a["yol"], "anlam", 8192, max(1, is_parcacigi // 2), exe, self.yollar.gunluk,
                                           havuzlama=(a.get("ek") or {}).get("havuzlama", "last"))
                    sunucu.baslat(ilerleme=ilerleme)
                    self.anlam_sunucusu = sunucu
                    self.anlam.baglan(sunucu, a["kimlik"], (a.get("ek") or {}).get("sorgu_talimati", VARSAYILAN_TALIMAT))
                except ModelHatasi as e:
                    self.son_hata = f"Anlam modeli: {e}"
                    log.warning(self.son_hata)
            s = self._sohbet_secimi()
            if exe and s and not self._calisiyor("sohbet"):
                try:
                    if ilerleme:
                        ilerleme(f"{s.get('ad', s['kimlik'])} belleğe yükleniyor")
                    sunucu = LlamaSunucusu(s["yol"], "sohbet", baglam or int(s.get("baglam", 8192)), is_parcacigi, exe,
                                           self.yollar.gunluk)
                    sunucu.baslat(ilerleme=ilerleme)
                    self.sohbet_sunucusu = sunucu
                    self.model = SunucuModeli(sunucu, s.get("ad", s["kimlik"]), bool(s.get("dusunme")))
                except ModelHatasi as e:
                    self.son_hata = f"Dil modeli: {e}"
                    log.warning(self.son_hata)
            if not self.model.hazir and not exe:         # sunucu yoksa: llama-cpp-python ile elle seçilmiş dosya
                yol = self.ayarlar.al("llm.model_yolu", "")
                if yol:
                    self.model = model_yukle(yol, baglam, is_parcacigi)
            return self.durum()

    def dosyadan_model(self, yol: str):
        """Katalog dışı bir GGUF dosyasını (ör. kurum içinde eğitilmiş model) ayrı sunucuda açar: (model, sunucu)."""
        exe = sunucu_exe(self.ayarlar.al("yz.sunucu_yolu", ""))
        if not exe:
            return model_yukle(yol, int(self.ayarlar.al("llm.baglam", 8192))), None
        sunucu = LlamaSunucusu(yol, "sohbet", int(self.ayarlar.al("llm.baglam", 8192)),
                               int(self.ayarlar.al("llm.is_parcacigi", 0)), exe, self.yollar.gunluk)
        try:
            sunucu.baslat()
        except ModelHatasi as e:
            self.son_hata = f"Aday model: {e}"
            return BosModel(), None
        return SunucuModeli(sunucu, Path(yol).stem, False), sunucu

    def dis_modeli_benimse(self, model, sunucu, yol: str) -> None:
        """Altın sette daha iyi çıkan katalog dışı modeli kalıcı olarak dil modeli yapar."""
        with self._kilit:
            if self.sohbet_sunucusu and self.sohbet_sunucusu is not sunucu:
                self.sohbet_sunucusu.durdur()
            self.sohbet_sunucusu, self.model = sunucu, model
            self.ayarlar.ayarla("llm.model_yolu", yol)
            self.ayarlar.kaydet()

    def model_degistir(self, kimlik: str, ilerleme=None) -> dict:
        with self._kilit:
            m = next((x for x in self.kurulu() if x["kimlik"] == kimlik), None)
            if m is None:
                raise ModelHatasi("Model kurulu değil")
            self.ayarlar.ayarla(f"yz.{m['tur']}_modeli", kimlik)
            if m["tur"] == "sohbet":
                self.ayarlar.ayarla("llm.model_yolu", "")      # katalogdan seçim, elle seçilen dosyanın yerine geçer
            self.ayarlar.kaydet()
            if m["tur"] == "sohbet":
                if self.sohbet_sunucusu:
                    self.sohbet_sunucusu.durdur()
                self.sohbet_sunucusu, self.model = None, BosModel()
            else:
                if self.anlam_sunucusu:
                    self.anlam_sunucusu.durdur()
                self.anlam_sunucusu = None
                self.anlam.baglan(None, "")
            return self.baslat(ilerleme)

    def durdur(self) -> None:
        with self._kilit:
            for s in (self.sohbet_sunucusu, self.anlam_sunucusu):
                if s:
                    s.durdur()
            self.sohbet_sunucusu = self.anlam_sunucusu = None
            self.model = BosModel()
            self.anlam.baglan(None, "")

    # ------------------------------------------------------------------ model yarışı
    def yaris(self, gelisim, hat, aday_kimlik: str, bitis: float) -> tuple[bool, str]:
        """Aday sohbet modelini mevcutla aynı sınavda karşılaştırır; kapıdan geçerse seçili yapar."""
        from ..cekirdek.karne import kapi
        aday = next((x for x in self.kurulu() if x["kimlik"] == aday_kimlik and x["tur"] == "sohbet"), None)
        if aday is None:
            return False, "Aday kurulu değil"
        sorular = gelisim.sinav_seti()
        if len(sorular) < 5:
            return False, "Yarış için en az 5 sınav sorusu gerekir"
        eski_karne = gelisim.sinav(sorular, bitis)
        mevcut = self.secili("sohbet")
        with self._kilit:
            if self.sohbet_sunucusu:
                self.sohbet_sunucusu.durdur()
            sunucu = LlamaSunucusu(aday["yol"], "sohbet", int(aday.get("baglam", 8192)),
                                   int(self.ayarlar.al("llm.is_parcacigi", 0)),
                                   sunucu_exe(self.ayarlar.al("yz.sunucu_yolu", "")), self.yollar.gunluk)
            try:
                sunucu.baslat()
                # Aday kendi hat kopyasıyla sınanır: kullanıcının o sıradaki soruları adaya gitmez
                aday_hat = copy.copy(hat)
                aday_hat.model = SunucuModeli(sunucu, aday.get("ad", aday_kimlik), bool(aday.get("dusunme")))
                aday_gelisim = copy.copy(gelisim)
                aday_gelisim.hat = aday_hat
                yeni_karne = aday_gelisim.sinav(sorular, bitis)
            finally:
                sunucu.durdur()
                self.sohbet_sunucusu, self.model = None, BosModel()
        ok, gerekce = kapi(eski_karne, yeni_karne)
        gelisim.st.gelisim_yaz("model", f"{mevcut['kimlik'] if mevcut else '-'} → {aday_kimlik}",
                               "benimsendi" if ok else "reddedildi", gerekce, eski_karne=eski_karne.sozluk(),
                               yeni_karne=yeni_karne.sozluk())
        if ok:
            self.ayarlar.ayarla("yz.sohbet_modeli", aday_kimlik)
            self.ayarlar.kaydet()
        self.baslat()
        hat.model = self.model
        return ok, gerekce
