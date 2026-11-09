# Akıl Hocası — kurulum paketi oluşturma (Windows, PowerShell 5.1+ / 7+)
# Aynı betik hem GitHub Actions'ta hem kendi bilgisayarınızda çalışır.
# Gerekenler: internet, Python 3.12 (PATH'te), Inno Setup 6 (yoksa choco ile kurulmaya çalışılır).
# Çıktı: derleme\cikti\AkilHocasi-Kurulum-<sürüm>.exe
param(
    [switch]$TestleriAtla,
    [switch]$TesseractAtla
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Kok = Split-Path -Parent $PSScriptRoot
Set-Location $Kok
$Derleme = Join-Path $Kok "derleme"
New-Item -ItemType Directory -Force $Derleme | Out-Null

function Adim([string]$m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Kontrol([string]$m) { if ($LASTEXITCODE -ne 0) { throw $m } }

Adim "1/7 Python ortamı ve paketler"
python --version; Kontrol "Python bulunamadı. python.org'dan Python 3.12 kurun (Add to PATH)."
$venv = Join-Path $Derleme "venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) { python -m venv $venv; Kontrol "Sanal ortam oluşturulamadı" }
$vpy = Join-Path $venv "Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r requirements.txt -r requirements-istege-bagli.txt pyinstaller pytest --quiet
Kontrol "Paket kurulumu başarısız"

Adim "2/7 Testler"
if (-not $TestleriAtla) { & $vpy -m pytest -q tests; Kontrol "Testler başarısız" }
if (-not $TestleriAtla -and (Get-Command node -ErrorAction SilentlyContinue)) {
    # Gözlemci eklentisinin kuralları ve tarama akışı (Node yerleşik test çalıştırıcısı)
    & node --test (Get-ChildItem tests\js\*.test.js).FullName; Kontrol "Eklenti testleri başarısız"
}

Adim "3/7 Taşınabilir Tesseract + Türkçe dil dosyası"
$tess = Join-Path $Derleme "tesseract"
if (-not $TesseractAtla -and -not (Test-Path (Join-Path $tess "tesseract.exe"))) {
    $kaynak = "C:\Program Files\Tesseract-OCR"
    if (-not (Test-Path (Join-Path $kaynak "tesseract.exe"))) {
        if (Get-Command choco -ErrorAction SilentlyContinue) { choco install tesseract -y --no-progress | Out-Null }
    }
    if (Test-Path (Join-Path $kaynak "tesseract.exe")) {
        New-Item -ItemType Directory -Force $tess | Out-Null
        Copy-Item (Join-Path $kaynak "*") $tess -Recurse -Force
        Get-ChildItem $tess -Filter "*uninstall*" -Recurse | Remove-Item -Force -ErrorAction SilentlyContinue
        $tur = Join-Path $tess "tessdata\tur.traineddata"
        if (-not (Test-Path $tur)) {
            Invoke-WebRequest "https://github.com/tesseract-ocr/tessdata_fast/raw/main/tur.traineddata" -OutFile $tur
        }
        Write-Host "Tesseract pakete eklendi: $tess"
    } else {
        Write-Warning "Tesseract bulunamadı; paket Windows OCR ve RapidOCR ile oluşturulacak."
    }
}

Adim "3b/7 Yerel model sunucusu (llama.cpp llama-server, CPU) ve test modelleri"
$llama = Join-Path $Derleme "llama"
if (-not (Test-Path (Join-Path $llama "llama-server.exe"))) {
    $basliklar = @{ "User-Agent" = "akilhocasi-derleme"; "Accept" = "application/vnd.github+json" }
    if ($env:GITHUB_TOKEN) { $basliklar["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
    $yayin = Invoke-RestMethod "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest" -Headers $basliklar
    $varlik = $yayin.assets | Where-Object { $_.name -match "bin-win-cpu-x64\.zip$" } | Select-Object -First 1
    if (-not $varlik) { $varlik = $yayin.assets | Where-Object { $_.name -match "bin-win-avx2-x64\.zip$" } | Select-Object -First 1 }
    if (-not $varlik) { throw "llama.cpp Windows CPU paketi bulunamadı ($($yayin.tag_name))" }
    $zip = Join-Path $Derleme "llama.zip"
    $gecici = Join-Path $Derleme "llama_acik"
    Remove-Item $gecici -Recurse -Force -ErrorAction SilentlyContinue
    Invoke-WebRequest $varlik.browser_download_url -OutFile $zip
    Expand-Archive $zip -DestinationPath $gecici -Force
    $sunucu = Get-ChildItem $gecici -Recurse -Filter "llama-server.exe" | Select-Object -First 1
    if (-not $sunucu) { throw "llama-server.exe zip içinde yok" }
    New-Item -ItemType Directory -Force $llama | Out-Null
    # Yalnızca sunucu ve DLL'ler pakete girer (diğer araçlar gereksiz yer kaplar)
    Copy-Item $sunucu.FullName $llama -Force
    Get-ChildItem $sunucu.DirectoryName -Filter "*.dll" | Copy-Item -Destination $llama -Force
    Get-ChildItem $sunucu.DirectoryName -Filter "LICENSE*" | Copy-Item -Destination $llama -Force -ErrorAction SilentlyContinue
    Set-Content (Join-Path $llama "SURUM.txt") "llama.cpp $($yayin.tag_name) ($($varlik.name))" -Encoding UTF8
    Remove-Item $zip, $gecici -Recurse -Force -ErrorAction SilentlyContinue
}
Get-Content (Join-Path $llama "SURUM.txt") -ErrorAction SilentlyContinue | Write-Host
& (Join-Path $llama "llama-server.exe") --version 2>&1 | Select-Object -First 3 | Write-Host
$modeller = Join-Path $Derleme "modeller"
& $vpy paketleme\test_modelleri.py $modeller

Adim "4/7 PyInstaller (Python gömülü uygulama klasörü)"
Remove-Item (Join-Path $Derleme "dist"), (Join-Path $Derleme "work"), (Join-Path $Derleme "kopru"), (Join-Path $Derleme "work_kopru") -Recurse -Force -ErrorAction SilentlyContinue
& $vpy -m PyInstaller paketleme\akilhocasi.spec --noconfirm --distpath (Join-Path $Derleme "dist") --workpath (Join-Path $Derleme "work")
Kontrol "PyInstaller başarısız"
# Eklenti köprüsü: küçük konsol programı, AkilHocasi.exe'nin yanına
& $vpy -m PyInstaller paketleme\kopru.spec --noconfirm --distpath (Join-Path $Derleme "kopru") --workpath (Join-Path $Derleme "work_kopru")
Kontrol "Köprü derlenemedi"
Copy-Item (Join-Path $Derleme "kopru\AkilHocasiKopru.exe") (Join-Path $Derleme "dist\AkilHocasi\") -Force

Adim "5/7 Paket öz testi (gerçek Qt, ekransız)"
$exe = Join-Path $Derleme "dist\AkilHocasi\AkilHocasi.exe"
$rapor = Join-Path $Derleme "oz_test_raporu.txt"
Remove-Item $rapor -ErrorAction SilentlyContinue
# Küçük test modelleri varsa öz test gerçek llama-server ile uçtan uca sınama da yapar
if (Get-ChildItem $modeller -Filter "*.gguf" -ErrorAction SilentlyContinue) { $env:AKILHOCASI_MODELLER = $modeller }
$p = Start-Process -FilePath $exe -ArgumentList "--oz-test=`"$rapor`"" -PassThru
if (-not $p.WaitForExit(1200000)) {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    throw "Paket öz testi 20 dakikada bitmedi (program bir hata penceresinde beklemiş olabilir)"
}
Remove-Item Env:AKILHOCASI_MODELLER -ErrorAction SilentlyContinue
if (Test-Path $rapor) { Get-Content $rapor -Encoding UTF8 | Write-Host } else { Write-Warning "Öz test raporu oluşmadı" }
if ($p.ExitCode -ne 0) { throw "Paket öz testi başarısız (çıkış kodu $($p.ExitCode))" }

Adim "6/7 Inno Setup ile kurulum dosyası"
$surum = (& $vpy -c "import akil_hocasi; print(akil_hocasi.__version__)").Trim()
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($y in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                     "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $y) { $iscc = $y; break }
    }
}
if (-not $iscc -and (Get-Command choco -ErrorAction SilentlyContinue)) {
    choco install innosetup -y --no-progress | Out-Null
    $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
}
if (-not $iscc -or -not (Test-Path $iscc)) { throw "Inno Setup 6 bulunamadı: https://jrsoftware.org/isdl.php adresinden kurun." }
& $iscc "/DSurum=$surum" paketleme\akilhocasi.iss
Kontrol "Inno Setup başarısız"

Adim "7/7 Tamamlandı"
Get-ChildItem (Join-Path $Derleme "cikti\*.exe") | ForEach-Object {
    Write-Host ("{0}  ({1:N0} MB)" -f $_.FullName, ($_.Length / 1MB)) -ForegroundColor Green
}
