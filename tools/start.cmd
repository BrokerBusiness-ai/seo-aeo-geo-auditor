@echo off
REM ============================================================================
REM start.cmd - wrapper that launches the PowerShell starter.
REM This is the file the desktop shortcut points to (CMD bypasses Windows
REM SmartScreen's "PowerShell script blocked" warning).
REM ============================================================================
title SEO/AEO/GEO Auditor
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
    echo.
    echo ============================================================
    echo  Launcher exited with code %EXITCODE%
    echo ============================================================
    echo  If you see Python errors above, install Python 3.10+ from:
    echo    https://www.python.org/downloads/
    echo  If you see PowerShell parser errors, the start.ps1 file may
    echo  have wrong encoding. Re-run install_desktop_shortcut.ps1.
    echo.
    pause
)
