"""Arka plan iş parçacıkları: arayüz donmadan cevap, tarama, OCR ve model yükleme."""

from __future__ import annotations

import traceback

import numpy as np
from PySide6.QtCore import QThread, Signal


class CevapCalisani(QThread):
    ilerleme = Signal(int, int, str)
    bitti = Signal(object)
    hata = Signal(str)

    def __init__(self, hat, soru: str, mod: str, parent=None):
        super().__init__(parent)
        self.hat, self.soru, self.mod = hat, soru, mod

    def run(self) -> None:
        try:
            cevap = self.hat.cevapla(self.soru, self.mod, ilerleme=lambda a, t, m: self.ilerleme.emit(a, t, m))
            self.bitti.emit(cevap)
        except Exception:
            self.hata.emit(traceback.format_exc(limit=3))


class TaramaCalisani(QThread):
    """Bekleyen görevleri sırayla yürütür."""
    ilerleme = Signal(str)
    gorev_bitti = Signal(object)        # TaramaRaporu
    hepsi_bitti = Signal()

    def __init__(self, tarayici, gorevler: list[str], parent=None):
        super().__init__(parent)
        self.tarayici, self.gorevler = tarayici, gorevler

    def run(self) -> None:
        for g in self.gorevler:
            if self.tarayici.durdur.is_set():
                break
            rapor = self.tarayici.calistir(g, ilerleme=self.ilerleme.emit)
            self.gorev_bitti.emit(rapor)
        self.hepsi_bitti.emit()


class OcrCalisani(QThread):
    bitti = Signal(object)              # OcrSonuc
    hata = Signal(str)

    def __init__(self, hat, img: np.ndarray, seviye: int = 1, bolge=None, onceki=None, coklu: bool = False,
                 parent=None):
        super().__init__(parent)
        self.hat, self.img, self.seviye, self.bolge, self.onceki, self.coklu = hat, img, seviye, bolge, onceki, coklu

    def run(self) -> None:
        try:
            if self.onceki is not None and self.bolge:
                sonuc = self.hat.bolgeyi_yeniden_oku(self.img, self.onceki, self.bolge)
            elif self.coklu:
                sonuc = self.hat.coklu_oku(self.img, self.bolge)
            else:
                sonuc = self.hat.oku(self.img, self.seviye, self.bolge)
            self.bitti.emit(sonuc)
        except Exception:
            self.hata.emit(traceback.format_exc(limit=3))


class ModelYukleyici(QThread):
    bitti = Signal(object)

    def __init__(self, yol: str, baglam: int, is_parcacigi: int, parent=None):
        super().__init__(parent)
        self.yol, self.baglam, self.is_parcacigi = yol, baglam, is_parcacigi

    def run(self) -> None:
        from ..answer.llm import model_yukle
        self.bitti.emit(model_yukle(self.yol, self.baglam, self.is_parcacigi))


class OgrenmeCalisani(QThread):
    """Gece öz değerlendirmesi + (uygunsa) yerel ek katman eğitimi ve karşılaştırma."""
    ilerleme = Signal(str)
    bitti = Signal(object)              # list[str] rapor

    def __init__(self, s, parent=None):
        super().__init__(parent)
        self.s = s

    def run(self) -> None:
        from ..ogrenme.degerlendirme import GeceDegerlendirmesi
        s = self.s
        self.ilerleme.emit("Öz değerlendirme ve öğrenme")
        rapor = GeceDegerlendirmesi(
            s.hat, s.kutuphane, s.ogrenme, s.siralayici,
            paylasim_klasoru=s.ayarlar.al("ogrenme.paylasim_klasoru", ""),
            gecmis_gun=s.ayarlar.al("gizlilik.gecmis_gun", 30)).calistir()
        try:
            rapor.append(self._yerel_egitim())
        except Exception as e:
            rapor.append(f"Yerel eğitim: HATA {e}")
        s.kutuphane.zamanlayici_yaz("ogrenme")
        self.bitti.emit(rapor)

    def _yerel_egitim(self) -> str:
        from ..answer.llm import model_yukle
        from ..ogrenme.egitim import (egitim_verisi_disa_aktar, modelleri_karsilastir, yerel_egitim_uygun_mu,
                                      yerel_egitimi_calistir)
        s = self.s
        veri = s.yollar.kok / "egitim" / "egitim.jsonl"
        n = egitim_verisi_disa_aktar(s.ogrenme, veri)
        uygun, neden = yerel_egitim_uygun_mu(s.ayarlar, n)
        if not uygun:
            return f"Yerel eğitim: {neden}"
        temel = s.ayarlar.al("llm.model_yolu", "")
        aday = s.yollar.modeller / "aday" / "aday.gguf"
        aday.parent.mkdir(parents=True, exist_ok=True)
        self.ilerleme.emit("Dil modeli için ek katman eğitiliyor (uzun sürebilir)")
        ok, mesaj = yerel_egitimi_calistir(s.ayarlar, veri, temel, aday)
        if not ok:
            return f"Yerel eğitim: {mesaj}"
        yeni = model_yukle(str(aday), s.ayarlar.al("llm.baglam", 8192))
        if not yeni.hazir:
            return "Yerel eğitim: aday model yüklenemedi"
        karar = modelleri_karsilastir(s.hat, s.kutuphane, s.hat.model, yeni)
        if karar["devreye_al"]:
            s.hat.model = yeni
            s.ayarlar.ayarla("llm.model_yolu", str(aday))
            s.ayarlar.kaydet()
        return f"Yerel eğitim: {karar['neden']} ({karar['eski']['gecen']} → {karar['yeni']['gecen']} doğru)"


class AdayModelCalisani(QThread):
    """Kullanıcının seçtiği yeni modeli (ör. Kaggle çıktısı) altın sette eskisiyle karşılaştırır."""
    bitti = Signal(object)              # dict

    def __init__(self, s, yol: str, parent=None):
        super().__init__(parent)
        self.s, self.yol = s, yol

    def run(self) -> None:
        from ..answer.llm import model_yukle
        from ..ogrenme.egitim import modelleri_karsilastir
        yeni = model_yukle(self.yol, self.s.ayarlar.al("llm.baglam", 8192))
        if not yeni.hazir:
            self.bitti.emit({"devreye_al": False, "neden": "Model yüklenemedi (llama.cpp veya dosya sorunu)"})
            return
        karar = modelleri_karsilastir(self.s.hat, self.s.kutuphane, self.s.hat.model, yeni)
        karar["model"] = yeni
        self.bitti.emit(karar)
