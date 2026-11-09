"""Yerel dil modeli adaptörü (llama.cpp).

Dil modeli yalnızca soruyu anlama, pasaj seçme ve kısa bağlaç cümleleri için kullanılır.
Model yoksa program alıntıya dayalı modda çalışır; doğrulama her iki modda da aynıdır.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Protocol


class DilModeli(Protocol):
    hazir: bool
    ad: str

    def sohbet(self, mesajlar: list[dict], max_tokens: int = 700, sicaklik: float = 0.1,
               json_mod: bool = False) -> str: ...


class BosModel:
    """Model yüklenmediğinde kullanılan yer tutucu."""
    hazir = False
    ad = "Alıntıya dayalı mod (model yok)"

    def sohbet(self, mesajlar, max_tokens=700, sicaklik=0.1, json_mod=False) -> str:
        raise RuntimeError("Dil modeli yüklü değil")


class LlamaCppModel:
    def __init__(self, model_yolu: str, baglam: int = 8192, is_parcacigi: int = 0):
        from llama_cpp import Llama  # isteğe bağlı bağımlılık

        self.ad = Path(model_yolu).stem
        self.llm = Llama(
            model_path=model_yolu,
            n_ctx=baglam,
            n_threads=is_parcacigi or max(2, (os.cpu_count() or 4) - 1),
            verbose=False,
        )
        self.hazir = True

    def sohbet(self, mesajlar, max_tokens=700, sicaklik=0.1, json_mod=False) -> str:
        kw = {"messages": mesajlar, "max_tokens": max_tokens, "temperature": sicaklik}
        if json_mod:
            kw["response_format"] = {"type": "json_object"}
        cikti = self.llm.create_chat_completion(**kw)
        return cikti["choices"][0]["message"]["content"] or ""


def model_yukle(model_yolu: str, baglam: int = 8192, is_parcacigi: int = 0) -> DilModeli:
    """Model dosyası varsa yükler, yoksa ya da kütüphane eksikse BosModel döner."""
    if not model_yolu or not Path(model_yolu).is_file():
        return BosModel()
    try:
        return LlamaCppModel(model_yolu, baglam, is_parcacigi)
    except Exception:  # llama_cpp kurulu değil veya model bozuk
        return BosModel()


def json_cikar(metin: str) -> dict | None:
    """Model çıktısından ilk JSON nesnesini ayıklar."""
    if not metin:
        return None
    try:
        return json.loads(metin)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", metin, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


ANLAMA_ISTEMI = (
    "Sen bir üniversite idari personeline yardım eden arama asistanısın. Görevin yalnızca soruyu "
    "çözümlemek; cevap verme. Yalnızca şu JSON'u döndür: "
    '{"niyet": "kısa açıklama", "personel_turu": "657/4-A | 4/B | 2547 | belirsiz", '
    '"terimler": ["arama terimi", "..."], "eksik_bilgi": "cevap için mutlaka gereken eksik bilgi veya null"}'
)

TASLAK_ISTEMI = (
    "Sen kaynak gösteren bir mevzuat asistanısın. KURALLAR: (1) Yalnızca verilen kaynak parçalarını kullan. "
    "(2) Kaynakta olmayan hiçbir bilgi, sayı, süre, oran, madde numarası veya form adı yazma. "
    "(3) Her cümlenin dayandığı kaynak kimliklerini 'kaynaklar' alanına yaz (ör. [\"K1\"]). "
    "(4) Alıntı yaparsan kaynaktaki metni harfi harfine ve çift tırnak içinde yaz. "
    "(5) 'ilgili mevzuat çerçevesinde', 'duruma göre değişir' gibi genel kalıplar kullanma; somut ol. "
    "(6) Kaynaklar soruyu doğrudan cevaplamıyorsa dogrudan_cevap=false yap ve neyin açık kaldığını yaz. "
    "Yalnızca şu JSON'u döndür: "
    '{"dogrudan_cevap": true, "kisa_cevap": [{"metin": "...", "kaynaklar": ["K1"]}], '
    '"adimlar": [{"metin": "...", "kaynaklar": ["K2"]}], "dikkat": [{"metin": "...", "kaynaklar": ["K1"]}], '
    '"acik_nokta": ""}'
)
