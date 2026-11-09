"""Tarama kuralları (eklentideki kurallar.js ile aynı davranış; testler iki tarafı aynı örneklerle sınar)."""

from __future__ import annotations

import random
import re
from urllib.parse import parse_qsl, urlparse

HIZ = {"yavas": (6.0, 2.0), "normal": (3.0, 1.2), "hizli": (1.5, 0.6)}


def bekleme(hiz: str) -> float:
    taban, sapma = HIZ.get(hiz, HIZ["normal"])
    return max(0.2, taban + random.uniform(-sapma, sapma))  # noqa: S311 - kibarlık gecikmesi, güvenlik değil


def yol_kalibi(adres: str) -> str:
    u = urlparse(adres)
    parcalar = [":n" if p.isdigit() and p else ":id" if re.search(r"\d{3,}", p) else p.lower() for p in u.path.split("/")]
    sorgu = "&".join(sorted(k.lower() + "=*" for k, _ in parse_qsl(u.query, keep_blank_values=True)))
    return (u.hostname or "").lower() + "/".join(parcalar) + (("?" + sorgu) if sorgu else "")


def benzerlik(a, b) -> float:
    A, B = set(a or []), set(b or [])
    if not A and not B:
        return 1.0
    kesisim = len(A & B)
    return kesisim / (len(A) + len(B) - kesisim)


def genisletilsin_mi(imza, kalip: str, gecmis: list[dict], esik: float = 0.9, sinir: int = 5) -> bool:
    benzer = 0
    for g in gecmis:
        if g.get("kalip") == kalip and benzerlik(g.get("imza"), imza) >= esik:
            benzer += 1
            if benzer >= sinir:
                return False
    return True


def robots_ayristir(metin: str) -> list[dict]:
    gruplar: list[dict] = []
    grup = None
    son_ajan = False
    for satir0 in (metin or "").splitlines():
        satir = re.sub(r"#.*$", "", satir0).strip()
        m = re.match(r"^([A-Za-z-]+)\s*:\s*(.*)$", satir)
        if not m:
            continue
        alan, deger = m.group(1).lower(), m.group(2).strip()
        if alan == "user-agent":
            if not son_ajan:
                grup = {"ajanlar": [], "kurallar": []}
                gruplar.append(grup)
            grup["ajanlar"].append(deger.lower())
            son_ajan = True
        else:
            son_ajan = False
            if grup is not None and alan in ("allow", "disallow"):
                grup["kurallar"].append({"izin": alan == "allow", "onek": deger})
    ozel = [g for g in gruplar if any("akilhocasi" in a for a in g["ajanlar"])]
    secilen = ozel or [g for g in gruplar if "*" in g["ajanlar"]]
    return [k for g in secilen for k in g["kurallar"] if k["onek"] != "" or not k["izin"]]


def robots_izinli(kurallar: list[dict], yol: str) -> bool:
    en_uzun, izin = -1, True
    for k in kurallar or []:
        onek = k["onek"]
        if onek == "":
            continue
        desen = "^" + re.escape(onek).replace(r"\*", ".*")
        if desen.endswith(r"\$"):
            desen = desen[:-2] + "$"
        if re.match(desen, yol) and (len(onek) > en_uzun or (len(onek) == en_uzun and k["izin"])):
            en_uzun, izin = len(onek), k["izin"]
    return izin
