@echo off
REM ============================================================================
REM start.cmd — wrapper that launches the PowerShell starter.
REM This is the file the desktop shortcut points to (CMD bypasses Windows
REM SmartScreen's "PowerShell script blocked" warning).
REM ============================================================================
title SEO/AEO/GEO Auditor
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
