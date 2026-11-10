"""Kaggle'da eğitilen modeli programın GitHub sürümü olarak yayımlar (GitHub Actions içinde çalışır).

GitHub sürüm eklerinde dosya başına 2 GB sınırı olduğundan GGUF 1.9 GiB'lık parçalara bölünür. model.json:
dosya adı, boyut, sha256, parçalar (ad, boyut, sha256) ve eğitim/sınav bilgisi (Kaggle'ın yan dosyası).
Program (Zekâ › Eğitilmiş modeli indir) parçaları indirip doğrular ve birleştirir. Etiket: model-<kimlik>.
Kullanım: python kaggle/surum_yayinla.py <kaggle_cikti_klasoru>   (GH_TOKEN ortam değişkeni gerekir)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

PARCA = 1900 * 1024 * 1024


def sha256(yol: Path) -> str:
    h = hashlib.sha256()
    with open(yol, "rb") as f:
        while b := f.read(16 * 1024 * 1024):
            h.update(b)
    return h.hexdigest()


def hazirla(cikti: Path, hedef: Path) -> tuple[dict, list[Path], Path | None]:
    ggufler = [p for p in cikti.rglob("akilhocasi-*.gguf") if "mmproj" not in p.name.lower()]
    if not ggufler:
        raise SystemExit("Çıktıda eğitilmiş GGUF yok")
    gguf = max(ggufler, key=lambda p: p.stat().st_mtime)
    yan = gguf.with_suffix(".json")
    bilgi = json.loads(yan.read_text("utf-8")) if yan.is_file() else {"kimlik": gguf.stem, "ad": gguf.stem}
    hedef.mkdir(parents=True, exist_ok=True)
    parcalar, yollar = [], []
    with open(gguf, "rb") as f:
        i = 1
        while b := f.read(PARCA):
            p = hedef / f"{gguf.name}.{i:03d}"
            p.write_bytes(b)
            parcalar.append({"ad": p.name, "boyut": len(b), "sha256": hashlib.sha256(b).hexdigest()})
            yollar.append(p)
            i += 1
    bildirim = {"dosya": gguf.name, "boyut": gguf.stat().st_size, "sha256": sha256(gguf), "parcalar": parcalar,
                "bilgi": bilgi}
    (hedef / "model.json").write_text(json.dumps(bildirim, ensure_ascii=False, indent=1), "utf-8")
    rapor = next(iter(cikti.rglob("EGITIM_RAPORU.md")), None)
    return bildirim, yollar + [hedef / "model.json"], rapor


def main() -> None:
    cikti = Path(sys.argv[1] if len(sys.argv) > 1 else "kaggle_cikti")
    bildirim, dosyalar, rapor = hazirla(cikti, Path("surum_dosyalari"))
    bilgi = bildirim["bilgi"]
    etiket = f"model-{bilgi['kimlik']}"
    kapi = bool((bilgi.get("egitim") or {}).get("kapi"))
    notlar = rapor.read_text("utf-8") if rapor else bilgi.get("ad", "")
    notlar += ("\n\n---\nProgramda: Zekâ › **Eğitilmiş modeli indir**. Parçalar sha256 ile doğrulanıp birleştirilir. "
               + ("Kaggle sınavında gelişim kapısını geçti; program bu modeli kullanır."
                  if kapi else "Kaggle sınavında kapıyı geçemedi; program yalnız yarışmada ve yerel sınavda dener."))
    subprocess.run(["gh", "release", "delete", etiket, "-y", "--cleanup-tag"], capture_output=True)
    komut = ["gh", "release", "create", etiket, *map(str, dosyalar), "--title", f"Eğitilmiş model: {bilgi.get('ad')}",
             "--notes", notes_kirp(notlar)] + ([] if kapi else ["--prerelease"])
    subprocess.run(komut, check=True)
    print(f"Yayımlandı: {etiket} ({len(bildirim['parcalar'])} parça, {bildirim['boyut'] / 1e9:.2f} GB)")


def notes_kirp(metin: str, sinir: int = 120000) -> str:
    return metin if len(metin) <= sinir else metin[:sinir] + "\n…"


if __name__ == "__main__":
    main()
