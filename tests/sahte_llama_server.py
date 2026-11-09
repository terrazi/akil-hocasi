#!/usr/bin/env python3
"""Testler için sahte llama-server: aynı komut satırını ve OpenAI uyumlu uç noktaları taklit eder.

Gerçek model GitHub derleme sunucusunda (Windows) gerçek llama-server ile ayrıca sınanır.
"""

import hashlib
import json
import math
import re
import sys
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BAS = time.monotonic()
ARG = sys.argv[1:]
if "--version" in ARG:
    print("version: 0 (sahte llama-server)")
    sys.exit(0)
PORT = int(ARG[ARG.index("--port") + 1])
GOMME = "--embeddings" in ARG
MODEL = ARG[ARG.index("-m") + 1]


def katla(s):
    s = s.replace("İ", "i").replace("I", "ı").lower()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).replace("ı", "i")


def vektor(metin, boyut=64):
    v = [0.0] * boyut
    for kelime in re.findall(r"[a-z0-9]{3,}", katla(metin)):
        kok = kelime[:5]
        h = int(hashlib.md5(kok.encode()).hexdigest(), 16)
        v[h % boyut] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n * 3.0 for x in v]          # normalleştirilmemiş döner (istemci normalleştirmeli)


def sohbet_cevabi(govde):
    sistem = " ".join(m["content"] for m in govde["messages"])     # görev bölümü kullanıcı içeriğinin sonunda olabilir
    sema = (govde.get("response_format") or {}).get("json_schema", {}).get("schema", {})
    if "çözümle" in sistem:
        return json.dumps({"konu": "izin", "niyet": "bilgi", "personel_turu": "657/4-A memur", "olgular": ["memur"],
                           "alt_sorular": [govde["messages"][-1]["content"][-120:]], "terimler": ["aylıksız izin"],
                           "eksik": [], "zorluk": "kolay"})
    if "properties" in sema and "kisa_cevap" in sema["properties"]:
        return json.dumps({"dogrudan_cevap": False, "kisa_cevap": [], "uygulama": [], "adimlar": [], "dikkat": [],
                           "degerlendirme": [], "guven": "hukum_yok", "acik_nokta": "sahte"})
    if sema.get("properties"):                   # başka şemalar: şemaya uyan en sade nesne
        bos = {"string": "Ankara", "array": [], "boolean": False, "integer": 0, "number": 0, "object": {}}
        return json.dumps({ad: bos.get(oz.get("type"), "") for ad, oz in sema["properties"].items()})
    return "<think>düşünüyorum</think>Ankara"


class Isleyici(BaseHTTPRequestHandler):
    def log_message(self, *a):
        return

    def _json(self, kod, veri):
        b = json.dumps(veri).encode()
        self.send_response(kod)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/health":
            if time.monotonic() - BAS < 0.3:
                return self._json(503, {"error": {"message": "Loading model"}})
            return self._json(200, {"status": "ok"})
        return self._json(404, {})

    def do_POST(self):
        govde = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/v1/embeddings":
            if not GOMME:
                return self._json(501, {"error": "embeddings disabled"})
            girdi = govde["input"] if isinstance(govde["input"], list) else [govde["input"]]
            return self._json(200, {"data": [{"index": i, "embedding": vektor(t)} for i, t in enumerate(girdi)]})
        if self.path == "/v1/chat/completions":
            metin = sohbet_cevabi(govde)
            if govde.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for parca in re.findall(r".{1,4}", metin, re.S):
                    self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': parca}}]})}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                return
            return self._json(200, {"choices": [{"message": {"content": metin}}]})
        return self._json(404, {})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Isleyici).serve_forever()
