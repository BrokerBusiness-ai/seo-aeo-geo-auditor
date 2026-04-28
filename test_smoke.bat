@echo off
REM ============================================================
REM  SMOKE TEST — sprawdza czy wszystkie 8 modulow startuje
REM  i robi pelny audyt na zdrowie-fit
REM ============================================================

cd /d "%~dp0"

set TARGET=C:\PYTHON\ARCHAIOS Demand Engine\zdrowie-fit-generator\output\zdrowie-fit
set BASE_URL=https://zdrowie.fit
set SITE=zdrowie-fit

echo.
echo ============================================================
echo  SMOKE TEST — seo-aeo-geo-auditor
echo  Cel: %TARGET%
echo ============================================================
echo.

REM 1. Python check
echo [1/9] Python version check...
python --version
if errorlevel 1 (
    echo BLAD: Python nie jest w PATH. Zainstaluj Python 3.10+ ze strony python.org
    pause
    exit /b 1
)
echo.

REM 2. Syntax check wszystkich modulow
echo [2/9] Syntax check wszystkich modulow...
python -m py_compile auditor.py ai_bots.py templates.py fixer.py validator.py auditor_advanced.py monitor.py report_html.py keyword_strategy.py
if errorlevel 1 (
    echo BLAD: Bledy skladniowe. Sprawdz wynik powyzej.
    pause
    exit /b 1
)
echo  OK - wszystkie 9 modulow skompilowane
echo.

REM 3. Audyt podstawowy
echo [3/9] Audyt podstawowy (auditor.py)...
python auditor.py --folder "%TARGET%" --json _smoke_main.json
echo.

REM 4. Audyt zaawansowany
echo [4/9] Audyt zaawansowany (auditor_advanced.py — Performance + A11y + Content)...
python auditor_advanced.py --folder "%TARGET%" --json _smoke_adv.json
echo.

REM 5. Walidacja schema.org
echo [5/9] Walidacja schema.org (validator.py)...
python validator.py --folder "%TARGET%" --json _smoke_val.json --md _smoke_val.md
echo.

REM 6. Strategia keywords
echo [6/9] Strategia keywords (keyword_strategy.py)...
python keyword_strategy.py --folder "%TARGET%" --json _smoke_kw.json --md _smoke_kw.md --suggest 15
echo.

REM 7. Monitor (snapshot + diff)
echo [7/9] Monitor — snapshot + diff (monitor.py)...
python monitor.py --folder "%TARGET%" --site %SITE%
echo.

REM 8. Generuj wizualny raport HTML
echo [8/9] Generuj wizualny raport HTML (report_html.py)...
python report_html.py --inputs _smoke_main.json,_smoke_adv.json,_smoke_val.json --history --site %SITE% --out raport_zdrowie-fit.html
echo.

REM 9. Otworz raport
echo [9/9] Otwieram raport w przegladarce...
start "" "%~dp0raport_zdrowie-fit.html"
echo.

echo ============================================================
echo  GOTOWE. Wygenerowane pliki:
echo  - _smoke_main.json    (audyt podstawowy)
echo  - _smoke_adv.json     (Performance + A11y + Content)
echo  - _smoke_val.json     (walidacja schema.org)
echo  - _smoke_val.md       (walidacja jako markdown)
echo  - _smoke_kw.json      (strategia keywords)
echo  - _smoke_kw.md        (strategia jako markdown — top 15 sugestii)
echo  - history\*.json      (snapshot do trendow)
echo  - raport_zdrowie-fit.html (gotowy do druku jako PDF)
echo ============================================================
echo.
pause
