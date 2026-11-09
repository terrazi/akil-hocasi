@echo off
chcp 65001 >nul
setlocal
title Akil Hocasi kurulumu
echo.
echo  ==============================================
echo   AKIL HOCASI gelistirici kurulumu (normal kullanim icin setup.exe)
echo  ==============================================
echo.
set "HEDEF=%LOCALAPPDATA%\AkilHocasi"
set "VENV=%HEDEF%\venv"

where py >nul 2>nul
if errorlevel 1 (
  echo [!] Python bulunamadi.
  echo     https://www.python.org adresinden Python 3.12 kurun.
  echo     Kurulumda "Add python.exe to PATH" kutusunu isaretleyin.
  pause
  exit /b 1
)

echo [1/4] Sanal ortam olusturuluyor: %VENV%
py -3 -m venv "%VENV%" || goto hata

echo [2/4] Temel paketler kuruluyor (birkac dakika surebilir)...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip >nul
"%VENV%\Scripts\python.exe" -m pip install -r "%~dp0..\requirements.txt" || goto hata

echo [3/4] OCR motorlari kuruluyor...
"%VENV%\Scripts\python.exe" -m pip install -r "%~dp0..\requirements-istege-bagli.txt"
if errorlevel 1 echo [i] Bazi istege bagli OCR paketleri kurulamadi; program kalan motorlarla calisir.

echo [4/4] Masaustu kisayolu olusturuluyor...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$k=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Akil Hocasi.lnk');" ^
  "$k.TargetPath='%VENV%\Scripts\pythonw.exe'; $k.Arguments='-m akil_hocasi'; $k.WorkingDirectory='%~dp0..';" ^
  "$k.Description='Akil Hocasi'; $k.Save()"

echo.
choice /C EH /M "Windows acilisinda Akil Hocasi sistem tepsisinde baslasin mi (saat basi guncelleme icin onerilir)"
if errorlevel 2 goto son
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$k=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Akil Hocasi.lnk');" ^
  "$k.TargetPath='%VENV%\Scripts\pythonw.exe'; $k.Arguments='-m akil_hocasi --tepside'; $k.WorkingDirectory='%~dp0..'; $k.Save()"

:son
echo.
echo Kurulum tamamlandi. Masaustundeki "Akil Hocasi" simgesiyle baslatabilirsiniz.
pause
exit /b 0

:hata
echo.
echo [!] Kurulum sirasinda hata olustu. Internet baglantisini ve proxy ayarlarini kontrol edin.
pause
exit /b 1
