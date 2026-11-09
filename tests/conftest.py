import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Testler için sentetik mevzuat metni (gerçek kanun metni değildir).
ORNEK_KANUN = """ÖRNEK PERSONEL KANUNU
Amaç
MADDE 1 – (1) Bu Kanunun amacı örnek personel düzenlemelerini belirlemektir.
Aylıksız izin
MADDE 2 – (1) Memura isteği üzerine en fazla 6 ay aylıksız izin verilebilir.
(2) Bu sürenin uzatılması 657 sayılı Kanunun 108 inci maddesine tabidir.
Yıllık izin
MADDE 3 – (1) Yıllık izin süresi hizmet süresine göre 20 veya 30 gündür.
EK MADDE 1 – (Mülga: 01.01.2020-0000/1 md.)
GEÇİCİ MADDE 1 – (1) Geçiş dönemine ilişkin hükümler 2 nci maddede belirtilmiştir.
"""

ORNEK_YONERGE = """TOGÜ ÖRNEK İZİN USUL VE ESASLARI
Dayanak
MADDE 1 – (1) Bu Usul ve Esaslar 657 sayılı Kanunun 108 inci maddesine dayanılarak hazırlanmıştır.
Başvuru
MADDE 2 – (1) Aylıksız izin talebi TOGÜ.FRM.396 formu ile birim amirine yapılır.
"""


@pytest.fixture
def kutuphane(tmp_path):
    from akil_hocasi.library.db import Kutuphane
    k = Kutuphane(tmp_path / "test.db")
    k.belge_kaydet(tur="kanun", kimlik="9999", baslik="9999 sayılı Örnek Personel Kanunu",
                   metin=ORNEK_KANUN, sha256="a1", kaynak_url="https://www.mevzuat.gov.tr/ornek/9999",
                   kaynak_turu="Mevzuat")
    k.belge_kaydet(tur="togu", kimlik="TOGÜ.USE.999", baslik="TOGÜ Örnek İzin Usul ve Esasları",
                   metin=ORNEK_YONERGE, sha256="b1", kaynak_url="https://kalite.gop.edu.tr/depo/ornek.pdf",
                   kaynak_turu="TOGÜ belgesi", yayin_tarihi="2024-01-01")
    yield k
    k.kapat()
