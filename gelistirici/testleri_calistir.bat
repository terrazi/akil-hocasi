@echo off
cd /d "%~dp0.."
"%LOCALAPPDATA%\AkilHocasi\venv\Scripts\python.exe" -m pip install pytest >nul
"%LOCALAPPDATA%\AkilHocasi\venv\Scripts\python.exe" -m pytest -q tests
where node >nul 2>nul && node --test tests\js\kurallar.test.js tests\js\arka_plan.test.js
pause
