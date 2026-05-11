# =============================================================================
# start.ps1 - one-click launcher for seo-aeo-geo-auditor
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
Write-Host "  SEO/AEO/GEO AUDITOR - local launcher" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# -----------------------------------------------------------------------------
# 1. Load API keys
# -----------------------------------------------------------------------------
$KeyFiles = @(
    "C:\PYTHON\token\Api_AI.txt",
    (Join-Path $AuditorRoot ".env")
)

# Fallback detection: if a bare value (no KEY=) appears, infer the variable
# name from a well-known prefix. Order matters - first match wins.
function Get-VarNameForValue {
    param([string]$val)
    switch -Regex ($val) {
        '^sk-ant-api'      { return "ANTHROPIC_API_KEY" }
        '^sk-proj-'        { return "OPENAI_API_KEY" }
        '^xai-'            { return "XAI_API_KEY" }
        '^pplx-'           { return "PERPLEXITY_API_KEY" }
        '^hf_'             { return "HF_TOKEN" }
        '^github_pat_'     { return "GITHUB_TOKEN" }
        '^AIza[0-9A-Za-z_-]{30,}' {
            # AIza... is the prefix for ALL Google API keys (Gemini, PSI, Maps).
            # Disambiguate by looking at the previous label line if present.
            return $null  # handled with context below
        }
        '^sk_live_'        { return "STRIPE_SECRET_KEY" }
        '^pk_live_'        { return "STRIPE_PUBLISHABLE_KEY" }
        '^whsec_'          { return "STRIPE_WEBHOOK_SECRET" }
        # DeepSeek uses sk- without proj/ant prefix - hard to disambiguate from
        # generic sk-... so we don't auto-detect those.
    }
    return $null
}

$loaded = 0
foreach ($keyFile in $KeyFiles) {
    if (Test-Path $keyFile) {
        Write-Host "[+] Loading keys from: $keyFile" -ForegroundColor Green
        $lines = Get-Content $keyFile
        $prevLabel = $null  # tracks the previous non-empty line for label-above-value format

        foreach ($rawLine in $lines) {
            $line = $rawLine.Trim()
            if ([string]::IsNullOrEmpty($line) -or $line.StartsWith("#")) {
                $prevLabel = $null
                continue
            }

            # Standard form: KEY=VALUE
            if ($line -match '^([A-Z][A-Z0-9_]*)\s*=\s*(.+)$') {
                $name = $Matches[1]
                $val = $Matches[2].Trim().Trim('"').Trim("'")
                [Environment]::SetEnvironmentVariable($name, $val, "Process")
                $loaded++
                $prevLabel = $null
                continue
            }

            # Bare value: try to infer KEY by prefix
            $inferred = Get-VarNameForValue $line
            if ($inferred) {
                [Environment]::SetEnvironmentVariable($inferred, $line.Trim().Trim('"').Trim("'"), "Process")
                $loaded++
                $prevLabel = $null
                continue
            }

            # AIza... + previous label = disambiguate Gemini / PSI / GitHub label
            if ($line -match '^AIza[0-9A-Za-z_-]{30,}$') {
                $lbl = if ($prevLabel) { $prevLabel.ToLower() } else { "" }
                $name = $null
                if ($lbl -match "gemini")            { $name = "GEMINI_API_KEY" }
                elseif ($lbl -match "psi|pagespeed") { $name = "PSI_API_KEY" }
                elseif ($lbl -match "maps")          { $name = "GOOGLE_MAPS_API_KEY" }
                else                                 { $name = "GEMINI_API_KEY" }  # default Google key bucket
                [Environment]::SetEnvironmentVariable($name, $line.Trim(), "Process")
                $loaded++
                $prevLabel = $null
                continue
            }

            # Otherwise treat as a label for the next bare value
            $prevLabel = $line
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

# Run gui.py - --open automatically launches browser after 0.8s
python gui.py --open --port 8765

# After gui.py exits (Ctrl+C), keep window for one keypress so user reads logs
Write-Host ""
Write-Host "Server stopped. Press any key to close this window..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
