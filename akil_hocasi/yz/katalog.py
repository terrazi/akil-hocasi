"""Model kataloğu: hangi bilgisayara hangi model.

Dosya adları yayıncıya göre değişebildiği için katalog yalnızca depo ve dosya desenini tutar; indirici
dosyayı Hugging Face'ten çözümler ve sha256 ile doğrular. Katalog, programın deposundaki yz_katalog.json
ile güncellenebilir (yeni ve daha iyi modeller çıktıkça): program yeni adayı indirir, kendi soru setinde
sınar ve yalnızca daha başarılıysa devreye alır.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field


@dataclass
class ModelTanimi:
    kimlik: str
    ad: str
    tur: str                    # "sohbet" | "anlam"
    depo: str                   # Hugging Face deposu
    desen: str                  # dosya adı deseni (regex)
    yaklasik_gb: float
    en_az_bellek_gb: float      # bu modeli rahat çalıştıracak toplam bellek
    baglam: int = 8192
    dusunme: bool = False       # "düşünme" kipini destekler (zor sorularda açılır)
    oncelik: int = 50           # kalite sırası (büyük = daha iyi)
    aday: bool = False          # yalnız yarışmada denenir, kendiliğinden kurulmaz
    aciklama: str = ""
    ek: dict = field(default_factory=dict)

    def dosya_eslesir(self, yol: str) -> bool:
        ad = yol.rsplit("/", 1)[-1]
        return bool(re.search(self.desen, ad, re.IGNORECASE)) and "mmproj" not in ad.lower()


VARSAYILAN_KATALOG: list[ModelTanimi] = [
    ModelTanimi("qwen3.5-9b", "Qwen3.5 9B", "sohbet", "unsloth/Qwen3.5-9B-GGUF", r"Q4_K_M\.gguf$", 5.7, 15.5,
                dusunme=True, oncelik=90, aciklama="En güçlü yerel danışman; 16 GB ve üstü bellek"),
    ModelTanimi("gemma-4-e4b", "Gemma 4 E4B", "sohbet", "unsloth/gemma-4-E4B-it-GGUF", r"Q4_K_M\.gguf$", 5.0, 11.5,
                oncelik=72, aday=True, aciklama="Çok dilli güçlü aday; yarışmada sınanır"),
    ModelTanimi("qwen3.5-4b", "Qwen3.5 4B", "sohbet", "unsloth/Qwen3.5-4B-GGUF", r"Q4_K_M\.gguf$", 2.8, 7.5,
                dusunme=True, oncelik=70, aciklama="Ofis bilgisayarları için dengeli seçim; 8 GB ve üstü"),
    ModelTanimi("qwen3.5-2b", "Qwen3.5 2B", "sohbet", "unsloth/Qwen3.5-2B-GGUF", r"Q4_K_M\.gguf$", 1.3, 5.5,
                dusunme=True, oncelik=45, aciklama="Az bellekli bilgisayarlar için"),
    ModelTanimi("qwen3.5-0.8b", "Qwen3.5 0.8B", "sohbet", "unsloth/Qwen3.5-0.8B-GGUF", r"Q4_K_M\.gguf$", 0.6, 3.5,
                dusunme=True, oncelik=20, aciklama="En küçük model (deneme ve çok eski bilgisayarlar)"),
    ModelTanimi("qwen3-embedding-0.6b", "Qwen3 Embedding 0.6B", "anlam", "Qwen/Qwen3-Embedding-0.6B-GGUF",
                r"Q8_0\.gguf$", 0.64, 3.5, oncelik=60, aciklama="Anlamsal arama (100+ dil, Türkçe dahil)",
                ek={"havuzlama": "last", "sorgu_talimati": "Given a question from a Turkish public university "
                    "administrative employee, retrieve the legislation articles that answer it"}),
]


class Katalog:
    def __init__(self, ek_json: str | None = None):
        self.modeller: dict[str, ModelTanimi] = {m.kimlik: m for m in VARSAYILAN_KATALOG}
        if ek_json:
            self.birlestir(ek_json)

    def birlestir(self, metin: str) -> int:
        """Uzak katalog (yz_katalog.json) ile birleştirir; geçersiz girdiler atlanır."""
        try:
            veri = json.loads(metin)
        except ValueError:
            return 0
        n = 0
        for g in veri.get("modeller", []) if isinstance(veri, dict) else []:
            try:
                m = ModelTanimi(**{k: v for k, v in g.items() if k in ModelTanimi.__dataclass_fields__})
                re.compile(m.desen)
                if m.tur in ("sohbet", "anlam") and "/" in m.depo:
                    self.modeller[m.kimlik] = m
                    n += 1
            except (TypeError, re.error):
                continue
        return n

    def getir(self, kimlik: str) -> ModelTanimi | None:
        return self.modeller.get(kimlik)

    def onerilen(self, tur: str, bellek_gb: float) -> ModelTanimi | None:
        """Bu bilgisayarda rahat çalışacak en iyi (aday olmayan) model."""
        uygun = [m for m in self.modeller.values() if m.tur == tur and not m.aday and m.en_az_bellek_gb <= bellek_gb]
        if not uygun:
            uygun = [m for m in self.modeller.values() if m.tur == tur and not m.aday]
            return min(uygun, key=lambda m: m.en_az_bellek_gb) if uygun else None
        return max(uygun, key=lambda m: m.oncelik)

    def yarisma_adaylari(self, tur: str, bellek_gb: float, mevcut: str | None) -> list[ModelTanimi]:
        """Mevcut modelden daha iyi olabilecek ve bu bilgisayara sığan modeller (en umut vericisi önce)."""
        m0 = self.modeller.get(mevcut or "")
        taban = m0.oncelik if m0 else -1
        return sorted((m for m in self.modeller.values() if m.tur == tur and m.kimlik != mevcut
                       and m.en_az_bellek_gb <= bellek_gb and m.oncelik >= taban), key=lambda m: -m.oncelik)

    def json(self) -> str:
        return json.dumps({"modeller": [asdict(m) for m in self.modeller.values()]}, ensure_ascii=False, indent=2)
