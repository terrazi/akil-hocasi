"""Sistem Rehberi sayfası: EBYS, MYS, KBS, HİTAP, SGK, YÖKSİS, EKAP, Kariyer Kapısı, ÖSYM/KPSS... ekranlarında adım adım
yardım.

Akış: sistemi seç → "ne yapmak istiyorsunuz?" yaz ya da sık işlemlerden seç → kılavuzun ilgili bölümü, adımları,
ekran/düğme adları ve kılavuz sayfasının görüntüsü. "Ekranımda takıldım": ekran görüntüsü yerel OCR ile okunur,
sistem ve ekran tanınır, ilgili kılavuz sayfaları ve Danışma'ya hazır soru gelir. Program sistemlere bağlanmaz.
"""

from __future__ import annotations

import html
import tempfile
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QScrollArea, QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from ..rehber import sistem
from ..rehber.kilavuz import adimlari_bul, etiketleri_bul, yollari_bul
from .bilesenler import qimage_to_numpy
from .calisanlar import KilavuzCalisani, OcrCalisani
from .ikonlar import ikon
from .tema import R


def _dugme(metin: str, ikon_ad: str, fn, birincil: bool = False) -> QPushButton:
    d = QPushButton("  " + metin)
    if birincil:
        d.setObjectName("Birincil")
    d.setIcon(ikon(ikon_ad, "#FFFFFF" if birincil else R["metin2"], 16))
    d.clicked.connect(fn)
    return d


class RehberSayfasi(QWidget):
    yakala_istendi = Signal()            # ana pencere ekran bölgesi seçtirir, görüntüyü geri verir
    sor_istendi = Signal(str)            # Danışma'ya soru

    def __init__(self, s, parent=None):
        super().__init__(parent)
        self.s = s
        self.rehber = s.rehber
        self.calisan: KilavuzCalisani | None = None
        self.ocr_calisani: OcrCalisani | None = None
        self.secili_pasaj = None
        self.analiz = None
        self.olcek = 1.0
        self._pixmap: QPixmap | None = None

        ana = QVBoxLayout(self)
        ana.setContentsMargins(32, 26, 32, 22)
        ana.setSpacing(10)
        b = QLabel("Sistem Rehberi")
        b.setObjectName("SayfaBaslik")
        ana.addWidget(b)
        alt = QLabel("EBYS, MYS, KBS, HİTAP, SGK, YÖKSİS, YÖK PBS, EKAP, Kariyer Kapısı, ÖSYM/KPSS ve TOGÜ sistemlerinde "
                     "takıldığınız ekranda adım adım yol gösterir. Her adım resmî kullanım kılavuzunun sayfasıyla verilir. "
                     "Program bu sistemlere bağlanmaz, giriş yapmaz; işlemi siz yaparsınız.")
        alt.setObjectName("Ikincil")
        alt.setWordWrap(True)
        ana.addWidget(alt)

        ust = QHBoxLayout()
        ust.addWidget(_dugme("Ekranımda takıldım", "yakala", self.yakala_istendi.emit, birincil=True))
        ust.addWidget(_dugme("Panodaki ekran görüntüsünü oku", "kopyala", self.panodan))
        ust.addWidget(_dugme("Kılavuz ekle…", "ek", self.kilavuz_ekle))
        self.d_guncelle = _dugme("Kılavuzları bul / güncelle", "yenile", self.kilavuzlari_guncelle)
        ust.addWidget(self.d_guncelle)
        ust.addStretch(1)
        ana.addLayout(ust)
        self.durum = QLabel("")
        self.durum.setObjectName("Ikincil")
        self.durum.setWordWrap(True)
        ana.addWidget(self.durum)

        # ---- ekran analizi kutusu (görüntü okununca görünür)
        self.ekran_kutusu = QFrame()
        self.ekran_kutusu.setObjectName("Kart")
        ek = QVBoxLayout(self.ekran_kutusu)
        ek.setContentsMargins(14, 10, 14, 10)
        self.ekran_ozet = QLabel("")
        self.ekran_ozet.setWordWrap(True)
        self.ekran_ozet.setTextFormat(Qt.RichText)
        ek.addWidget(self.ekran_ozet)
        sat = QHBoxLayout()
        self.ekran_soru = QLineEdit()
        self.ekran_soru.setPlaceholderText("Danışma'ya gidecek soru (düzenleyebilirsiniz)")
        sat.addWidget(self.ekran_soru, 1)
        sat.addWidget(_dugme("Danışma'ya sor", "danisma", lambda: self._sor(self.ekran_soru.text()), birincil=True))
        sat.addWidget(_dugme("Kapat", "carpi", lambda: self.ekran_kutusu.hide()))
        ek.addLayout(sat)
        gizlilik = QLabel("Görüntü bu bilgisayarda okundu; kaydedilmedi ve hiçbir yere gönderilmedi. TC kimlik no, IBAN, "
                          "kart ve cep telefonu numaraları maskelendi.")
        gizlilik.setObjectName("Soluk")
        gizlilik.setWordWrap(True)
        ek.addWidget(gizlilik)
        self.ekran_kutusu.hide()
        ana.addWidget(self.ekran_kutusu)

        # ---- gövde: sistem listesi | sistem ayrıntısı
        govde = QSplitter(Qt.Horizontal)
        self.liste = QListWidget()
        self.liste.setMinimumWidth(220)
        self.liste.setMaximumWidth(300)
        self.liste.currentItemChanged.connect(lambda *_: self._sistem_secildi())
        govde.addWidget(self.liste)

        sag = QWidget()
        sy = QVBoxLayout(sag)
        sy.setContentsMargins(12, 0, 0, 0)
        bas = QHBoxLayout()
        self.s_ad = QLabel("")
        self.s_ad.setObjectName("BolumBaslik")
        self.s_ad.setWordWrap(True)
        bas.addWidget(self.s_ad, 1)
        self.d_tarayici = _dugme("Sistemi tarayıcıda aç", "dis", self.tarayicida_ac)
        self.d_tarayici.setToolTip("Resmî giriş sayfasını kendi tarayıcınızda açar. Akıl Hocası giriş yapmaz.")
        bas.addWidget(self.d_tarayici)
        sy.addLayout(bas)
        self.s_bilgi = QLabel("")
        self.s_bilgi.setObjectName("Ikincil")
        self.s_bilgi.setWordWrap(True)
        sy.addWidget(self.s_bilgi)
        ara = QHBoxLayout()
        self.ara = QLineEdit()
        self.ara.setPlaceholderText("Bu sistemde ne yapmak istiyorsunuz? (ör. kurum dışı evrak yazma, ödeme emri onaya gönderme)")
        self.ara.returnPressed.connect(self._ara)
        ara.addWidget(self.ara, 1)
        ara.addWidget(_dugme("Bul", "yol", self._ara, birincil=True))
        sy.addLayout(ara)
        self.sonuc_etiketi = QLabel("Sık işlemler")
        self.sonuc_etiketi.setObjectName("Soluk")
        sy.addWidget(self.sonuc_etiketi)
        self.sonuclar = QListWidget()
        self.sonuclar.setMaximumHeight(170)
        self.sonuclar.currentItemChanged.connect(lambda *_: self._sonuc_secildi())
        sy.addWidget(self.sonuclar)

        ayrinti = QSplitter(Qt.Horizontal)
        self.detay = QTextBrowser()
        self.detay.setOpenExternalLinks(True)
        ayrinti.addWidget(self.detay)
        gorsel_kutu = QWidget()
        gk = QVBoxLayout(gorsel_kutu)
        gk.setContentsMargins(0, 0, 0, 0)
        arac = QHBoxLayout()
        self.sayfa_etiketi = QLabel("Kılavuz sayfası")
        self.sayfa_etiketi.setObjectName("Soluk")
        arac.addWidget(self.sayfa_etiketi, 1)
        for ad, kat in (("kucult", 1 / 1.25), ("buyut", 1.25)):
            d = QPushButton()
            d.setIcon(ikon(ad, R["metin2"], 16))
            d.setObjectName("Hayalet")
            d.clicked.connect(lambda _=False, k=kat: self._yakinlas(k))
            arac.addWidget(d)
        gk.addLayout(arac)
        self.gorsel_alan = QScrollArea()
        self.gorsel_alan.setWidgetResizable(False)
        self.gorsel = QLabel("Bölüm seçince kılavuzun o sayfası burada görünür (PDF kılavuzlarda).")
        self.gorsel.setAlignment(Qt.AlignCenter)
        self.gorsel.setWordWrap(True)
        self.gorsel_alan.setWidget(self.gorsel)
        gk.addWidget(self.gorsel_alan, 1)
        ayrinti.addWidget(gorsel_kutu)
        ayrinti.setSizes([520, 420])
        sy.addWidget(ayrinti, 1)

        alt_d = QHBoxLayout()
        alt_d.addWidget(_dugme("Danışma'ya sor", "danisma", self._bolumu_sor))
        alt_d.addWidget(_dugme("Kılavuzu aç", "dosya", self._kilavuzu_ac))
        alt_d.addWidget(_dugme("Kaynağa git", "dis", self._kaynaga_git))
        alt_d.addStretch(1)
        sy.addLayout(alt_d)
        govde.addWidget(sag)
        govde.setSizes([250, 900])
        ana.addWidget(govde, 1)
        self.yenile()

    # ================================================================== liste
    def yenile(self) -> None:
        onceki = self._secili_kimlik()
        self.liste.blockSignals(True)
        self.liste.clear()
        toplam = 0
        for d in self.rehber.sistemler():
            toplam += d["kilavuz"]
            durum = f"{d['kilavuz']} kılavuz" if d["kilavuz"] else "kılavuz yok"
            item = QListWidgetItem(f"{d['kisa']}\n{durum}")
            item.setData(Qt.UserRole, d["kimlik"])
            item.setToolTip(d["ad"])
            item.setIcon(ikon("onay" if d["kilavuz"] else "bilgi", R["yesil"] if d["kilavuz"] else R["soluk"], 16))
            self.liste.addItem(item)
        self.liste.blockSignals(False)
        hedef = onceki or "EBYS"
        for i in range(self.liste.count()):
            if self.liste.item(i).data(Qt.UserRole) == hedef:
                self.liste.setCurrentRow(i)
                break
        if not toplam and not (self.calisan and self.calisan.isRunning()):
            self.durum.setText("Kütüphanede henüz sistem kılavuzu yok. “Kılavuzları bul / güncelle” resmî sitelerden "
                               "alır; elinizdeki kılavuzu (EBYS ile gelen, eğitimde verilen) “Kılavuz ekle…” ile ekleyin.")

    def _secili_kimlik(self) -> str:
        item = self.liste.currentItem()
        return item.data(Qt.UserRole) if item else ""

    def _sistem_secildi(self) -> None:
        s = sistem(self._secili_kimlik())
        if s is None:
            return
        bilgi = next((d for d in self.rehber.sistemler() if d["kimlik"] == s.kimlik), {})
        self.s_ad.setText(s.ad)
        parca = [f"İşleten: {s.sahip}"]
        if s.kullananlar:
            parca.append("Kullanan: " + ", ".join(s.kullananlar))
        if bilgi.get("kilavuz"):
            parca.append(f"{bilgi['kilavuz']} kılavuz, {bilgi['bolum']} bölüm"
                         + (f" · son güncelleme {bilgi['son_guncelleme'][:10]}" if bilgi.get("son_guncelleme") else ""))
        else:
            parca.append("Bu sistemin kılavuzu henüz yok" + (": “Kılavuzları bul” resmî sitelerden arar."
                                                             if s.tohumlar else ": elinizdeki kılavuzu ekleyebilirsiniz."))
        self.s_bilgi.setText(" · ".join(parca))
        self.d_tarayici.setEnabled(bool(s.adres))
        self.d_tarayici.setToolTip(s.adres or "Resmî adres kayıtlı değil")
        self.sonuc_etiketi.setText("Sık işlemler (kılavuz başlıklarından)")
        self.sonuclar.clear()
        for i in self.rehber.sik_islemler(s.kimlik):
            item = QListWidgetItem(f"{i['baslik']}  ·  s. {i['sayfa']}")
            item.setData(Qt.UserRole, i["madde_id"])
            self.sonuclar.addItem(item)
        if not self.sonuclar.count():
            self.detay.setHtml(self._bos_metin(s))

    @staticmethod
    def _bos_metin(s) -> str:
        return (f"<p><b>{html.escape(s.kisa)}</b> için gösterilecek kılavuz bölümü yok.</p>"
                "<p>Kılavuz eklendikçe burada adım adım yol tarifi, ekran ve düğme adları ve kılavuz sayfasının "
                "görüntüsü yer alır. Ne yapmak istediğinizi yukarıya yazarak tüm kılavuzlarda da arayabilirsiniz.</p>")

    # ================================================================== arama ve bölüm
    def _ara(self) -> None:
        metin = self.ara.text().strip()
        if not metin:
            return
        kimlik = self._secili_kimlik() or None
        bolumler = self.rehber.ara(metin, kimlik, limit=10)
        self.sonuc_etiketi.setText(f"“{metin}” için kılavuz bölümleri")
        self.sonuclar.clear()
        for p in bolumler:
            item = QListWidgetItem(p.etiket)
            item.setData(Qt.UserRole, p.madde_id)
            self.sonuclar.addItem(item)
        if bolumler:
            self.sonuclar.setCurrentRow(0)
        else:
            self.detay.setHtml("<p>Kılavuzlarda bu işlem için bölüm bulunamadı. Danışma'ya sorabilir ya da "
                               "elinizdeki kılavuzu ekleyebilirsiniz.</p>")

    def _sonuc_secildi(self) -> None:
        item = self.sonuclar.currentItem()
        if item is None:
            return
        p = self.s.kutuphane.pasaj_getir(int(item.data(Qt.UserRole)))
        if p is None:
            return
        self.secili_pasaj = p
        self.detay.setHtml(self._bolum_html(p))
        self._sayfayi_goster(p)

    @staticmethod
    def _bolum_html(p) -> str:
        satirlar = p.metin.splitlines()
        adimlar = adimlari_bul(satirlar)
        tum = p.baslik + "\n" + p.metin
        etiketler, yollar = etiketleri_bul(tum), yollari_bul(tum)
        h = [f"<h3>{html.escape(p.baslik or p.belge_baslik)}</h3>",
             f"<p style='color:{R['soluk']}'>Kaynak: {html.escape(p.etiket)}</p>"]
        if yollar:
            h.append("<p><b>Menü yolu:</b> " + "<br>".join(html.escape(y) for y in yollar[:4]) + "</p>")
        if adimlar:
            h.append("<p><b>Kılavuzdaki adımlar:</b></p><ol>" + "".join(f"<li>{html.escape(a)}</li>" for a in adimlar[:15])
                     + "</ol>")
        if etiketler:
            h.append("<p><b>Ekranda arayacağınız adlar:</b> " + ", ".join(f"“{html.escape(e)}”" for e in etiketler[:14])
                     + "</p>")
        h.append(f"<hr><p style='color:{R['metin2']}'>" + html.escape(p.metin).replace("\n", "<br>") + "</p>")
        return "".join(h)

    def _sayfayi_goster(self, p) -> None:
        png = self.rehber.sayfa_goruntusu(p.belge_kimlik, p.madde_no)
        if not png:
            self._pixmap = None
            self.gorsel.setPixmap(QPixmap())
            self.gorsel.setText("Bu bölüm için sayfa görüntüsü yok (Word/HTML kılavuz ya da dosya depoda değil).")
            self.gorsel.adjustSize()
            self.sayfa_etiketi.setText("Kılavuz sayfası")
            return
        pm = QPixmap()
        pm.loadFromData(png, "PNG")
        self._pixmap = pm
        self.olcek = max(0.4, min(1.0, (self.gorsel_alan.viewport().width() - 8) / max(1, pm.width())))
        self.sayfa_etiketi.setText(f"Kılavuz sayfası {p.madde_no}")
        self._yakinlas(1.0)

    def _yakinlas(self, kat: float) -> None:
        if self._pixmap is None:
            return
        self.olcek = max(0.25, min(3.0, self.olcek * kat))
        pm = self._pixmap.scaledToWidth(int(self._pixmap.width() * self.olcek), Qt.SmoothTransformation)
        self.gorsel.setPixmap(pm)
        self.gorsel.resize(pm.size())

    # ================================================================== eylemler
    def _sor(self, soru: str) -> None:
        soru = soru.strip()
        if soru:
            self.sor_istendi.emit(soru)

    def _bolumu_sor(self) -> None:
        s = sistem(self._secili_kimlik())
        konu = self.ara.text().strip() or (self.secili_pasaj.baslik if self.secili_pasaj else "")
        if not konu:
            return
        ad = s.kisa if s else ""
        self._sor(f"{ad} sisteminde “{konu}” işlemini adım adım nasıl yaparım?".strip())

    def _kilavuzu_ac(self) -> None:
        p = self.secili_pasaj
        if p is None:
            return
        for k in self.s.kutuphane.belgeleri_listele(p.belge_kimlik):
            if k["kimlik"] == p.belge_kimlik and k["dosya_yolu"] and Path(k["dosya_yolu"]).exists():
                hedef = Path(tempfile.gettempdir()) / "AkilHocasi" / Path(k["dosya_yolu"]).name
                hedef.parent.mkdir(parents=True, exist_ok=True)
                hedef.write_bytes(Path(k["dosya_yolu"]).read_bytes())    # depodaki orijinal değişmez
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(hedef)))
                return
        self._kaynaga_git()

    def _kaynaga_git(self) -> None:
        p = self.secili_pasaj
        if p is not None and p.kaynak_url:
            QDesktopServices.openUrl(QUrl(p.kaynak_url))

    def tarayicida_ac(self) -> None:
        s = sistem(self._secili_kimlik())
        if s and s.adres:
            QDesktopServices.openUrl(QUrl(s.adres))

    def kilavuz_ekle(self) -> None:
        yollar, _ = QFileDialog.getOpenFileNames(self, "Kılavuz dosyası seçin", "",
                                                 "Kılavuz (*.pdf *.docx *.htm *.html)")
        if not yollar:
            return
        secili = self._secili_kimlik()
        satirlar = []
        for yol in yollar:
            ad = Path(yol).name
            try:
                veri = Path(yol).read_bytes()
                sonuc = self.rehber.toplayici().dosya_ekle(veri, ad)
                if sonuc["sonuc"] == "sistem_belirlenemedi" and secili:
                    s = sistem(secili)
                    cevap = QMessageBox.question(self, "Kılavuz ekle",
                                                 f"“{ad}” hangi sisteme ait anlaşılamadı. {s.kisa} kılavuzu olarak "
                                                 "eklensin mi?")
                    if cevap == QMessageBox.Yes:
                        sonuc = self.rehber.toplayici().dosya_ekle(veri, ad, secili)
            except Exception as e:  # noqa: BLE001
                sonuc = {"sonuc": f"hata: {e}"}
            satirlar.append(f"{ad}: " + {
                "yeni": f"eklendi ({sonuc.get('sistem')}, {sonuc.get('bolum')} bölüm)",
                "guncellendi": f"güncellendi ({sonuc.get('sistem')})", "ayni": "zaten ekli",
                "taranmis": "taranmış görüntü PDF; metin katmanı yok (önce Yakala ile okutun)",
                "desteklenmiyor": "desteklenmeyen biçim", "sistem_belirlenemedi": "sistem belirlenemedi; eklenmedi",
            }.get(sonuc["sonuc"], sonuc["sonuc"]))
        self.durum.setText(" · ".join(satirlar))
        self.yenile()

    def kilavuzlari_guncelle(self) -> None:
        if self.calisan and self.calisan.isRunning():
            self.calisan.durdur.set()
            self.durum.setText("Durduruluyor…")
            return
        self.calisan = KilavuzCalisani(self.rehber.toplayici(), None, self)
        self.calisan.ilerleme.connect(self.durum.setText)
        self.calisan.bitti.connect(self._toplama_bitti)
        self.d_guncelle.setText("  Durdur")
        self.durum.setText("Resmî sitelerde kılavuzlar aranıyor…")
        self.calisan.start()

    def _toplama_bitti(self, rapor) -> None:
        self.d_guncelle.setText("  Kılavuzları bul / güncelle")
        metin = rapor.ozet()
        if rapor.hatalar:
            metin += " (ayrıntı günlükte)"
        self.durum.setText(metin)
        self.yenile()

    # ================================================================== ekran görüntüsü
    def panodan(self) -> None:
        pano = QGuiApplication.clipboard()
        img = pano.image()
        if img is not None and not img.isNull():
            self.ekran_goruntusu_isle(img)
        elif pano.text().strip():
            self.ekran_metni_isle(pano.text())
        else:
            self.durum.setText("Panoda görüntü yok. Ekranın görüntüsünü alın (Win+Shift+S) ya da "
                               "“Ekranımda takıldım” ile bölge seçin.")

    def ekran_goruntusu_isle(self, img: QImage) -> None:
        if img is None or img.isNull():
            return
        if not self.s.ocr.hazir:
            self.durum.setText("OCR motoru hazır değil (Ayarlar › OCR). Ekrandaki yazıyı kopyalayıp “Panodaki ekran "
                               "görüntüsünü oku” ile de verebilirsiniz.")
            return
        self.durum.setText("Ekran okunuyor (yerel OCR)…")
        self.ocr_calisani = OcrCalisani(self.s.ocr, qimage_to_numpy(img), 1, None, None, False, self)
        self.ocr_calisani.bitti.connect(lambda sonuc: self.ekran_metni_isle(sonuc.metin()))
        self.ocr_calisani.hata.connect(lambda m: self.durum.setText("Ekran okunamadı: " + m.splitlines()[-1][:160]))
        self.ocr_calisani.start()

    def ekran_metni_isle(self, metin: str, kullanici_notu: str = "") -> None:
        a = self.rehber.ekran(metin)
        self.analiz = a
        self.durum.setText("")
        if a.sistem is not None:
            for i in range(self.liste.count()):
                if self.liste.item(i).data(Qt.UserRole) == a.sistem.kimlik:
                    self.liste.setCurrentRow(i)
                    break
            ozet = f"<b>{html.escape(a.ozet())}</b>"
            if a.etiketler:
                ozet += "<br>Ekranda ve kılavuzda geçen: " + ", ".join(f"“{html.escape(e)}”" for e in a.etiketler[:8])
            if not a.bolumler:
                ozet += ("<br>Bu ekranla eşleşen kılavuz bölümü bulunamadı; Danışma'ya sorabilir ya da sistemin "
                         "kılavuzunu ekleyebilirsiniz.")
        else:
            ozet = ("<b>Ekrandaki sistem tanınamadı.</b> Soldan sistemi seçip ne yapmak istediğinizi yazın ya da "
                    "adres çubuğu ve pencere başlığı görünecek şekilde yeniden yakalayın.")
        self.ekran_ozet.setText(ozet)
        self.ekran_soru.setText(a.soru_onerisi(kullanici_notu))
        self.ekran_kutusu.show()
        if a.bolumler:
            self.sonuc_etiketi.setText("Bu ekranla ilgili kılavuz bölümleri")
            self.sonuclar.clear()
            for p in a.bolumler:
                item = QListWidgetItem(p.etiket)
                item.setData(Qt.UserRole, p.madde_id)
                self.sonuclar.addItem(item)
            self.sonuclar.setCurrentRow(0)

    def durdur(self) -> None:
        for c in (self.calisan, self.ocr_calisani):
            if c and c.isRunning():
                if hasattr(c, "durdur"):
                    c.durdur.set()
                c.wait(3000)
