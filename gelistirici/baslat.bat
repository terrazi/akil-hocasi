@echo off
cd /d "%~dp0.."
if exist "%LOCALAPPDATA%\AkilHocasi\venv\Scripts\pythonw.exe" (
  start "" "%LOCALAPPDATA%\AkilHocasi\venv\Scripts\pythonw.exe" -m akil_hocasi %*
) else (
  echo Once kur.bat dosyasini calistirin.
  pause
)
