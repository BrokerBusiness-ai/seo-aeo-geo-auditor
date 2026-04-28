@echo off
REM Pelny flow: audyt PRZED -> auto-fix -> audyt PO
REM Uzycie: full_flow.bat <folder> <site_name> <base_url>
REM Przyklad: full_flow.bat "C:\path\output\zdrowie-fit" "Zdrowie.fit" "https://zdrowie.fit"

if "%~3"=="" (
    echo Uzycie: full_flow.bat ^<folder^> ^<site_name^> ^<base_url^>
    echo Przyklad: full_flow.bat "C:\PYTHON\ARCHAIOS Demand Engine\zdrowie-fit-generator\output\zdrowie-fit" "Zdrowie.fit" "https://zdrowie.fit"
    exit /b 1
)

cd /d "%~dp0\.."

echo ================================================
echo  KROK 1/3: AUDYT PRZED (oryginal)
echo ================================================
python auditor.py --folder %1 --json before.json
if errorlevel 1 echo (kontynuuje mimo bledow audytu)

echo.
echo ================================================
echo  KROK 2/3: AUTO-FIX (do %~1_fixed)
echo ================================================
python fixer.py --folder %1 --apply all --base-url %3 --site-name %2

echo.
echo ================================================
echo  KROK 3/3: AUDYT PO (kopia _fixed)
echo ================================================
python auditor.py --folder %~1_fixed --json after.json

echo.
echo ================================================
echo  GOTOWE. Porownaj before.json vs after.json
echo  Naprawiona wersja: %~1_fixed
echo ================================================
