@echo off
REM Przyklad: audyt strony na zywo
REM Uzycie: audit_url.bat https://twoja-strona.pl

if "%1"=="" (
    echo Uzycie: audit_url.bat ^<url^>
    echo Przyklad: audit_url.bat https://zdrowie.fit
    exit /b 1
)

cd /d "%~dp0\.."
python auditor.py --url %1 --pages 15
