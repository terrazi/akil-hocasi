"""Arka plan iş parçacıkları: arayüz donmadan cevap, tarama, OCR ve model yükleme."""

from __future__ import annotations

import threading
import traceback

import numpy as np
from PySide6.QtCore import QThread, Signal


class CevapCalisani(QThread):
    ilerleme = Signal(int, int, str)
    bitti = Signal(object)
    hata = Signal(str)

    def __init__(self, hat, soru: str, mod: str, parent=None, baglam=None):
        super().__init__(parent)
        self.hat, self.soru, self.mod, self.baglam = hat, soru, mod, baglam

    def run(self) -> None:
        try:
            cevap = self.hat.cevapla(self.soru, self.mod, ilerleme=lambda a, t, m: self.ilerleme.emit(a, t, m),
                                     baglam=self.baglam)
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
        from ..ogrenme.egitim import modelleri_karsilastir
        yeni, sunucu = self.s.yz.dosyadan_model(self.yol)
        if not yeni.hazir:
            self.bitti.emit({"devreye_al": False, "neden": "Model yüklenemedi (llama.cpp veya dosya sorunu)"})
            return
        try:
            karar = modelleri_karsilastir(self.s.hat, self.s.kutuphane, self.s.hat.model, yeni)
        except Exception as e:  # noqa: BLE001
            karar = {"devreye_al": False, "neden": f"Karşılaştırma yapılamadı: {e}"}
        if not karar.get("devreye_al") and sunucu:
            sunucu.durdur()
        karar["model"], karar["sunucu"] = yeni, sunucu
        self.bitti.emit(karar)


class YZBaslatici(QThread):
    """Seçili yerel modelleri (dil + anlam) arka planda başlatır ve hızı ölçer."""
    ilerleme = Signal(str)
    bitti = Signal(object)              # dict durum

    def __init__(self, yz, degistir: str = "", parent=None):
        super().__init__(parent)
        self.yz, self.degistir = yz, degistir

    def run(self) -> None:
        try:
            durum = (self.yz.model_degistir(self.degistir, self.ilerleme.emit) if self.degistir
                     else self.yz.baslat(self.ilerleme.emit))
        except Exception as e:  # noqa: BLE001 - kullanıcıya gösterilir
            self.yz.son_hata = str(e)
            durum = self.yz.durum()
        if self.yz.model.hazir and hasattr(self.yz.model, "hiz_olc"):
            try:
                self.yz.model.hiz_olc()
            except Exception:  # noqa: BLE001 - ölçüm başarısızsa model yine kullanılır
                pass
            durum = self.yz.durum()
        self.bitti.emit(durum)


class ModelIndirmeCalisani(QThread):
    """Modelleri indirir ve doğrular (MB cinsinden ilerleme: 32 bitlik sinyal taşmasın)."""
    ilerleme = Signal(float, float, str)
    bitti = Signal(object)              # {"ok": bool, "mesaj": str}

    def __init__(self, yz, kimlikler: list[str], parent=None):
        super().__init__(parent)
        import threading
        self.yz, self.kimlikler = yz, kimlikler
        self.durdur = threading.Event()

    def run(self) -> None:
        mesajlar, ok = [], True
        for kimlik in self.kimlikler:
            m = self.yz.katalog.getir(kimlik)
            ad = m.ad if m else kimlik
            try:
                self.yz.indir(kimlik, lambda a, b, c, ad=ad: self.ilerleme.emit(a / 1e6, b / 1e6, f"{ad}: {c}"),
                              self.durdur)
                mesajlar.append(f"{ad} kuruldu")
            except Exception as e:  # noqa: BLE001 - kullanıcıya gösterilir
                ok = False
                mesajlar.append(f"{ad}: {e}")
                if self.durdur.is_set():
                    break
        self.bitti.emit({"ok": ok, "mesaj": "; ".join(mesajlar)})


class AnlamCalisani(QThread):
    """Anlam dizinini küçük partilerle tamamlar (boşta ya da yeni belge geldiğinde)."""
    bitti = Signal(int)

    def __init__(self, yz, parti: int = 128, parent=None):
        super().__init__(parent)
        import threading
        self.yz, self.parti = yz, parti
        self.durdur = threading.Event()

    def run(self) -> None:
        try:
            self.bitti.emit(self.yz.anlam.eksikleri_isle(self.parti, self.durdur))
        except Exception:  # noqa: BLE001
            self.bitti.emit(0)


class ZekaCalisani(QThread):
    """Gece YZ çalışması: anlam dizini, sentetik sorular, dersler, gelişim döngüsü, model yarışı."""
    ilerleme = Signal(str)
    bitti = Signal(object)              # list[str]

    def __init__(self, s, sure_dk: float, parent=None):
        super().__init__(parent)
        import threading
        self.s, self.sure_dk = s, sure_dk
        self.durdur = threading.Event()

    def run(self) -> None:
        from ..yz.oz_gelisim import GeceZekaCalismasi
        try:
            rapor = GeceZekaCalismasi(self.s, self.ilerleme.emit).calistir(self.sure_dk, self.durdur)
        except Exception as e:  # noqa: BLE001
            rapor = [f"Kendini geliştirme: HATA {e}"]
        self.bitti.emit(rapor)


class IsCalisani(QThread):
    """Uzun süren tek bir işi (dosya kopyalama, paket hazırlama) arka planda çalıştırır."""
    bitti = Signal(object)
    hata = Signal(str)

    def __init__(self, is_, parent=None):
        super().__init__(parent)
        self.is_ = is_

    def run(self) -> None:
        try:
            self.bitti.emit(self.is_())
        except Exception as e:  # noqa: BLE001 - kullanıcıya gösterilir
            self.hata.emit(str(e))


class SurumModeliCalisani(QThread):
    """GitHub sürümündeki (Kaggle'da eğitilmiş) en yeni modeli bulur, parçalarını indirip doğrular ve ekler."""
    ilerleme = Signal(float, float, str)        # alınan MB, toplam MB, açıklama
    bitti = Signal(object)                      # eklenen modelin bilgisi
    hata = Signal(str)

    def __init__(self, yz, parent=None):
        super().__init__(parent)
        self.yz = yz
        self.durdur = threading.Event()

    def run(self) -> None:
        from ..yz import surum_modeli
        try:
            b = surum_modeli.son_egitilmis()
            if b is None:
                self.hata.emit("Yayımlanmış eğitilmiş model bulunamadı (internet bağlantısını denetleyin).")
                return
            kimlik = b["bilgi"]["kimlik"]
            if any(m.get("kimlik") == kimlik for m in self.yz.ozel_modeller()):
                self.hata.emit(f"En yeni eğitilmiş model ({b['bilgi'].get('ad', kimlik)}) zaten kurulu.")
                return
            gguf = surum_modeli.indir(b, self.yz.model_klasoru(),
                                      lambda a, t, m: self.ilerleme.emit(a / 2**20, t / 2**20, m), self.durdur)
            self.bitti.emit(self.yz.ozel_model_ekle(gguf))
        except Exception as e:  # noqa: BLE001 - kullanıcıya gösterilir
            self.hata.emit(str(e))
