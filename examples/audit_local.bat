@echo off
REM Przyklad: audyt lokalnego katalogu z wygenerowana strona
REM Uzycie: audit_local.bat C:\sciezka\do\output

if "%1"=="" (
    echo Uzycie: audit_local.bat ^<sciezka_do_folderu^>
    exit /b 1
)

cd /d "%~dp0\.."
python auditor.py --folder %1
