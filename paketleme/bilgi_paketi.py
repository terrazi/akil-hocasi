"""Derleme hattı: çekirdek mevzuatı resmî kaynaktan indirip kurulum paketine koyar (derleme/bilgi_paketi).

Kullanım: python paketleme/bilgi_paketi.py [klasör]
Programın kendi indiricisini ve adres listesini kullanır (aynı adresleri program da düzenli kontrol eder).
İndirilemeyen belge atlanır, derleme durmaz; program o belgeyi ilk internet bağlantısında kendisi indirir.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from akil_hocasi.crawler.depo import dosya_turu, metin_cikar  # noqa: E402
from akil_hocasi.crawler.indirici import Indirici  # noqa: E402
from akil_hocasi.crawler.kaynaklar import CEKIRDEK_KANUNLAR, CEKIRDEK_YONETMELIKLER, Mevzuat  # noqa: E402


def main() -> int:
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    klasor = Path(sys.argv[1] if len(sys.argv) > 1 else "derleme/bilgi_paketi")
    klasor.mkdir(parents=True, exist_ok=True)
    ind, mev = Indirici(), Mevzuat()
    hedefler = [(no, f"{no} sayılı {ad}", "kanun", no, mev.kanun_adaylari(no)) for no, ad in CEKIRDEK_KANUNLAR]
    hedefler += [(no, ad, "yonetmelik", f"MEV:{tur}.{tertip}.{no}", mev.metin_adaylari(no, tur, tertip))
                 for no, ad, tur, tertip in CEKIRDEK_YONETMELIKLER]
    belgeler = []
    for _no, baslik, tur, kimlik, adresler in hedefler:
        for url in adresler:
            s = ind.getir(url)
            if not s.basarili:
                continue
            dt = dosya_turu(s.icerik)
            if dt not in ("pdf", "doc", "docx", "html"):
                continue
            if len(metin_cikar(s.icerik, dt).strip()) < 500:
                continue                                    # boş sayfa ya da hata sayfası
            dosya = f"{kimlik.replace(':', '_')}.{dt}"
            (klasor / dosya).write_bytes(s.icerik)
            belgeler.append({"kimlik": kimlik, "baslik": baslik, "tur": tur, "url": url, "dosya": dosya,
                             "sha256": hashlib.sha256(s.icerik).hexdigest(), "kaynak_turu": "Mevzuat",
                             "boyut": len(s.icerik)})
            print(f"{baslik}: {dt}, {len(s.icerik) // 1024} KB")
            break
        else:
            print(f"UYARI: {baslik} indirilemedi (program ilk bağlantıda kendisi indirir)")
    (klasor / "manifest.json").write_text(json.dumps(
        {"olusturma": datetime.now().isoformat(timespec="seconds"), "kaynak": "mevzuat.gov.tr", "belgeler": belgeler},
        ensure_ascii=False, indent=1), "utf-8")
    print(f"Çekirdek bilgi paketi: {len(belgeler)}/{len(hedefler)} belge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
