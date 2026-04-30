@echo off
REM ============================================================
REM  Uruchom lokalne GUI seo-aeo-geo-auditor
REM  Otwiera przegladarke automatycznie na http://localhost:8765
REM ============================================================

cd /d "%~dp0\.."
python gui.py --open
pause
