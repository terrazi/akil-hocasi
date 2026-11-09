@echo off
rem Akil Hocasi kurulum dosyasini (setup.exe) kendi bilgisayarinizda olusturur.
rem Gerekenler: internet, Python 3.12, Inno Setup 6. Ayrintilar: README.md
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0paketleme\paket_olustur.ps1" %*
echo.
if errorlevel 1 (echo [!] Paket olusturulamadi; yukaridaki hata mesajina bakin.) else (echo Kurulum dosyasi: derleme\cikti klasorunde.)
pause
