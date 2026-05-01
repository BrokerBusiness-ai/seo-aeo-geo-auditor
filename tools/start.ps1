# =============================================================================
# start.ps1 — one-click launcher for seo-aeo-geo-auditor
#
# What it does (in order):
#   1. Loads API keys from C:\PYTHON\token\Api_AI.txt (or .env if present)
#   2. Verifies Python is on PATH
#   3. Starts gui.py + auto-opens http://127.0.0.1:8765 in default browser
#   4. Keeps the window open so you can read logs
#
# Triggered by: tools\start.cmd (which the desktop shortcut points to)
# =============================================================================

$Host.UI.RawUI.WindowTitle = "SEO/AEO/GEO Auditor"

# Move to the auditor root regardless of where this script was launched from.
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AuditorRoot = Split-Path -Parent $ScriptRoot
Set-Location $AuditorRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  SEO/AEO/GEO AUDITOR — local launcher" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# -----------------------------------------------------------------------------
# 1. Load API keys
# -----------------------------------------------------------------------------
$KeyFiles = @(
    "C:\PYTHON\token\Api_AI.txt",
    (Join-Path $AuditorRoot ".env")
)

$loaded = 0
foreach ($keyFile in $KeyFiles) {
    if (Test-Path $keyFile) {
        Write-Host "[+] Loading keys from: $keyFile" -ForegroundColor Green
        Get-Content $keyFile | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith("#")) {
                if ($line -match '^([A-Z][A-Z0-9_]*)\s*=\s*(.+)$') {
                    $name = $Matches[1]
                    $val = $Matches[2].Trim().Trim('"').Trim("'")
                    [Environment]::SetEnvironmentVariable($name, $val, "Process")
                    $loaded++
                }
            }
        }
    }
}

if ($loaded -gt 0) {
    Write-Host "    -> $loaded keys loaded into environment" -ForegroundColor Green
} else {
    Write-Host "[!] No key file found. PSI / AEO probe will be limited." -ForegroundColor Yellow
    Write-Host "    Put keys in: C:\PYTHON\token\Api_AI.txt or $AuditorRoot\.env" -ForegroundColor Yellow
}

# Status of important keys
Write-Host ""
Write-Host "[i] Provider status:" -ForegroundColor Cyan
$providers = @{
    "PSI_API_KEY"        = "Google PageSpeed Insights"
    "OPENAI_API_KEY"     = "OpenAI"
    "ANTHROPIC_API_KEY"  = "Anthropic"
    "DEEPSEEK_API_KEY"   = "DeepSeek"
    "XAI_API_KEY"        = "xAI Grok"
    "GEMINI_API_KEY"     = "Google Gemini"
    "PERPLEXITY_API_KEY" = "Perplexity"
}
foreach ($key in $providers.Keys | Sort-Object) {
    $val = [Environment]::GetEnvironmentVariable($key, "Process")
    if ($val) {
        Write-Host ("    [OK] {0,-20} {1}" -f $key, $providers[$key]) -ForegroundColor Green
    } else {
        Write-Host ("    [-]  {0,-20} {1}" -f $key, $providers[$key]) -ForegroundColor DarkGray
    }
}

# -----------------------------------------------------------------------------
# 2. Verify Python
# -----------------------------------------------------------------------------
Write-Host ""
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "[X] python not found on PATH." -ForegroundColor Red
    Write-Host "    Install Python 3.10+ from https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host ""
    Write-Host "Press any key to exit..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

$pyVersion = & python --version 2>&1
Write-Host "[OK] $pyVersion" -ForegroundColor Green
Write-Host "[OK] Working directory: $AuditorRoot" -ForegroundColor Green

# -----------------------------------------------------------------------------
# 3. Launch GUI (it opens the browser via --open)
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  STARTING GUI on http://127.0.0.1:8765" -ForegroundColor Cyan
Write-Host "  Browser will open automatically." -ForegroundColor Cyan
Write-Host "  Press Ctrl+C in this window to stop the server." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Run gui.py — --open automatically launches browser after 0.8s
python gui.py --open --port 8765

# After gui.py exits (Ctrl+C), keep window for one keypress so user reads logs
Write-Host ""
Write-Host "Server stopped. Press any key to close this window..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
