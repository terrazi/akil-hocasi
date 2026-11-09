"""Güncelleme saatleri (saf mantık; Qt zamanlayıcısı arayüz tarafında bunu dakikada bir sorar).

Görevler:
  hafif    saat başı (aralık ayarlanabilir), makineye özgü sabit birkaç dakikalık kaydırmayla
  gece     günün Resmî Gazete'si tam tarama (varsayılan 00:30)
  sabah    "Bugün neler değişti" özeti (varsayılan 08:30, ağ kullanmaz)
  derin    günde bir, bilgisayar boştayken (48 saati geçerse beklemeden)
  haftalik üst kurum kılavuzları, Sayıştay / Danıştay / KİK kararları
  ogrenme  öz değerlendirme, öğrenen sıralayıcının eğitimi, paylaşım (günde bir, boştayken)
  siteler  Kaynak Havuzu'ndaki resmî sitelerin gömülü tarayıcıyla taranması (haftada bir, boştayken)

Kaçırılan zamanlar (bilgisayar kapalıydı) açılışta telafi edilir.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta

GOREVLER = {
    "hafif": "Saat başı değişiklik kontrolü",
    "gece": "Günün Resmî Gazete'si tam tarama",
    "sabah": "Bugün neler değişti özeti",
    "derin": "Derin tarama (TOGÜ siteleri, üst kurumlar, belge deposu)",
    "haftalik": "Haftalık tarama (kılavuzlar ve kararlar)",
    "ogrenme": "Öz değerlendirme ve kendi kendine eğitim",
    "siteler": "Resmî sitelerin gömülü tarayıcıyla taranması",
}


def _saat(metin: str, varsayilan: str) -> time:
    try:
        s, d = (int(x) for x in (metin or varsayilan).split(":"))
        return time(s, d)
    except (ValueError, AttributeError):
        s, d = (int(x) for x in varsayilan.split(":"))
        return time(s, d)


class Zamanlayici:
    def __init__(self, ayarlar: dict, makine_kimligi: str = ""):
        self.acik = ayarlar.get("acik", True)
        self.aralik = timedelta(minutes=max(15, int(ayarlar.get("aralik_dk", 60))))
        self.gece = _saat(ayarlar.get("gece_saati", ""), "00:30")
        self.sabah = _saat(ayarlar.get("sabah_saati", ""), "08:30")
        self.olculu_hafif = ayarlar.get("olculu_baglantida_hafif", True)
        # Tüm bilgisayarlar aynı anda TOGÜ sitelerine gitmesin: 1-9 dakikalık sabit kaydırma
        h = hashlib.sha256((makine_kimligi or "akilhocasi").encode()).digest()
        self.kaydirma = timedelta(minutes=1 + h[0] % 9)

    # -------------------------------------------------------------- yuva hesapları
    def _hafif_yuvalari(self, bas: datetime, son: datetime):
        """(bas, son] aralığındaki saat başı yuvaları."""
        gun_basi = datetime.combine(bas.date(), time(0, 0)) + self.kaydirma
        t = gun_basi
        while t <= bas:
            t += self.aralik
        while t <= son:
            yield t
            t += self.aralik

    def _sonraki_hafif(self, simdi: datetime) -> datetime:
        gun_basi = datetime.combine(simdi.date(), time(0, 0)) + self.kaydirma
        t = gun_basi
        while t <= simdi:
            t += self.aralik
        return t

    @staticmethod
    def _gunluk_yuva_var(saat: time, bas: datetime, son: datetime) -> bool:
        gun = bas.date()
        while gun <= son.date():
            t = datetime.combine(gun, saat)
            if bas < t <= son:
                return True
            gun += timedelta(days=1)
        return False

    @staticmethod
    def _sonraki_gunluk(saat: time, simdi: datetime) -> datetime:
        t = datetime.combine(simdi.date(), saat)
        return t if t > simdi else t + timedelta(days=1)

    # -------------------------------------------------------------- dış arayüz
    def bekleyenler(self, simdi: datetime, son: dict[str, datetime | None],
                    bostayken: bool = False, olculu: bool = False) -> list[str]:
        """Şimdi çalışması gereken görevleri öncelik sırasıyla döndürür."""
        if not self.acik:
            return []
        sonuc: list[str] = []

        def ilk_kez(ad: str) -> bool:
            return son.get(ad) is None

        s = son.get("gece")
        if ilk_kez("gece") or self._gunluk_yuva_var(self.gece, s, simdi):
            sonuc.append("gece")

        s = son.get("hafif")
        if ilk_kez("hafif") or any(True for _ in self._hafif_yuvalari(s, simdi)):
            sonuc.append("hafif")

        s = son.get("sabah")
        if ilk_kez("sabah") or self._gunluk_yuva_var(self.sabah, s, simdi):
            # Özeti yalnızca mesai başından sonra göster
            if simdi.time() >= self.sabah or not ilk_kez("sabah"):
                sonuc.append("sabah")

        s = son.get("derin")
        if s is None or simdi - s >= timedelta(hours=20):
            if bostayken or s is None or simdi - s >= timedelta(hours=48):
                sonuc.append("derin")

        s = son.get("haftalik")
        if s is None or simdi - s >= timedelta(days=7):
            sonuc.append("haftalik")

        # Öğrenme ağ kullanmaz (paylaşım klasörü yerel ağdadır); boştayken ya da 30 saati geçince
        s = son.get("ogrenme")
        if s is None or (simdi - s >= timedelta(hours=20) and (bostayken or simdi - s >= timedelta(hours=30))):
            sonuc.append("ogrenme")

        # Gömülü tarayıcıyla site taraması ağır iştir: haftada bir, bilgisayar boştayken (10 günü geçerse beklemeden)
        s = son.get("siteler")
        if (s is None or simdi - s >= timedelta(days=7)) and (bostayken or (s is not None and simdi - s >= timedelta(days=10))):
            sonuc.append("siteler")

        if olculu and self.olculu_hafif:
            sonuc = [g for g in sonuc if g in ("hafif", "sabah", "ogrenme")]
        return sonuc

    def sonraki(self, simdi: datetime) -> datetime:
        """Durum çubuğu için bir sonraki ağ kontrolünün zamanı."""
        adaylar = [self._sonraki_hafif(simdi), self._sonraki_gunluk(self.gece, simdi)]
        return min(adaylar)
