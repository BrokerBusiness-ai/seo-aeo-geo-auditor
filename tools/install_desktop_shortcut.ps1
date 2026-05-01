# =============================================================================
# install_desktop_shortcut.ps1
#
# One-shot installer that:
#   1. Generates tools\icon.ico (multi-resolution: 16, 32, 48, 64, 128, 256)
#   2. Creates a "SEO Auditor" shortcut on the user's Desktop pointing at
#      tools\start.cmd with the generated icon.
#
# Run with:
#   powershell -NoProfile -ExecutionPolicy Bypass -File install_desktop_shortcut.ps1
#
# Re-running is safe - overwrites existing icon and shortcut.
# =============================================================================

[CmdletBinding()]
param(
    [string]$ShortcutName = "SEO Auditor",
    [switch]$AllUsers
)

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AuditorRoot = Split-Path -Parent $ScriptRoot
$IconPath = Join-Path $ScriptRoot "icon.ico"
$LauncherPath = Join-Path $ScriptRoot "start.cmd"

if (-not (Test-Path $LauncherPath)) {
    Write-Host "[X] tools\start.cmd not found at $LauncherPath" -ForegroundColor Red
    exit 1
}

# -----------------------------------------------------------------------------
# 1. Render icon - uses System.Drawing
# -----------------------------------------------------------------------------
Write-Host "[+] Generating icon: $IconPath" -ForegroundColor Cyan

Add-Type -AssemblyName System.Drawing

function New-AuditorBitmap {
    param([int]$Size)

    $bmp = New-Object System.Drawing.Bitmap($Size, $Size)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAlias

    # Background - dark slate gradient
    $rect = New-Object System.Drawing.Rectangle(0, 0, $Size, $Size)
    $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
        $rect,
        [System.Drawing.Color]::FromArgb(15, 23, 42),
        [System.Drawing.Color]::FromArgb(30, 41, 59),
        45.0
    )

    # Rounded square - emulate rounded corners with FillEllipse + FillRectangle
    $radius = [int]($Size * 0.18)
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = $radius * 2
    $path.AddArc(0, 0, $d, $d, 180, 90)
    $path.AddArc($Size - $d - 1, 0, $d, $d, 270, 90)
    $path.AddArc($Size - $d - 1, $Size - $d - 1, $d, $d, 0, 90)
    $path.AddArc(0, $Size - $d - 1, $d, $d, 90, 90)
    $path.CloseFigure()
    $g.FillPath($brush, $path)

    # Magnifying-glass circle (suggests "audit/inspect")
    $cx = [int]($Size * 0.40)
    $cy = [int]($Size * 0.40)
    $r  = [int]($Size * 0.22)

    $penWidth = [Math]::Max(1, [int]($Size * 0.06))
    $glassPen = New-Object System.Drawing.Pen(
        [System.Drawing.Color]::FromArgb(56, 189, 248), $penWidth
    )
    # Pen has StartCap/EndCap (and DashCap) on .NET Framework — set both.
    $glassPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $glassPen.EndCap   = [System.Drawing.Drawing2D.LineCap]::Round
    $g.DrawEllipse($glassPen, $cx - $r, $cy - $r, $r * 2, $r * 2)

    # Magnifying-glass handle
    $handleStartX = $cx + [int]($r * 0.7)
    $handleStartY = $cy + [int]($r * 0.7)
    $handleEndX = [int]($Size * 0.78)
    $handleEndY = [int]($Size * 0.78)
    $g.DrawLine($glassPen, $handleStartX, $handleStartY, $handleEndX, $handleEndY)

    # "AI" mark inside the glass - only at sizes >= 32, otherwise a dot
    if ($Size -ge 32) {
        $fontSize = [Math]::Max(6, [int]($Size * 0.18))
        $font = New-Object System.Drawing.Font("Segoe UI", $fontSize, [System.Drawing.FontStyle]::Bold)
        $textBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(56, 189, 248))
        $sf = New-Object System.Drawing.StringFormat
        $sf.Alignment = [System.Drawing.StringAlignment]::Center
        $sf.LineAlignment = [System.Drawing.StringAlignment]::Center
        $textRect = New-Object System.Drawing.RectangleF(($cx - $r), ($cy - $r), ($r * 2), ($r * 2))
        $g.DrawString("AI", $font, $textBrush, $textRect, $sf)
        $font.Dispose()
        $textBrush.Dispose()
        $sf.Dispose()
    } else {
        $dotBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(56, 189, 248))
        $g.FillEllipse($dotBrush, $cx - 1, $cy - 1, 3, 3)
        $dotBrush.Dispose()
    }

    $glassPen.Dispose()
    $brush.Dispose()
    $g.Dispose()
    $path.Dispose()
    return $bmp
}

# Build multi-resolution ICO file
$sizes = @(16, 32, 48, 64, 128, 256)
$pngStreams = @()
foreach ($s in $sizes) {
    $bmp = New-AuditorBitmap -Size $s
    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $pngStreams += [pscustomobject]@{
        Size = $s
        Bytes = $ms.ToArray()
    }
    $ms.Dispose()
    $bmp.Dispose()
}

# ICO file format:
#   ICONDIR (6 bytes): reserved=0, type=1 (icon), count=N
#   ICONDIRENTRY (16 bytes per image): width, height, colors, reserved, planes,
#                                       bitcount, sizeInBytes, offset
#   ...image data (PNG-compressed for sizes >= 256, BMP/PNG for smaller - PNG is
#      universally supported on Vista+)
$fs = [System.IO.File]::Open($IconPath, [System.IO.FileMode]::Create)
$bw = New-Object System.IO.BinaryWriter($fs)

# ICONDIR
$bw.Write([uint16]0)                       # reserved
$bw.Write([uint16]1)                       # type = icon
$bw.Write([uint16]$pngStreams.Count)       # number of images

# Compute offset where image data starts (after all ICONDIRENTRYs)
$dataOffset = 6 + (16 * $pngStreams.Count)

# ICONDIRENTRY for each image
foreach ($img in $pngStreams) {
    $w = if ($img.Size -ge 256) { 0 } else { [byte]$img.Size }
    $h = if ($img.Size -ge 256) { 0 } else { [byte]$img.Size }
    $bw.Write([byte]$w)                    # width (0 = 256)
    $bw.Write([byte]$h)                    # height (0 = 256)
    $bw.Write([byte]0)                     # color count (0 = no palette)
    $bw.Write([byte]0)                     # reserved
    $bw.Write([uint16]1)                   # color planes
    $bw.Write([uint16]32)                  # bits per pixel
    $bw.Write([uint32]$img.Bytes.Length)   # image data size
    $bw.Write([uint32]$dataOffset)         # offset of image data
    $dataOffset += $img.Bytes.Length
}

# Image data
foreach ($img in $pngStreams) {
    $bw.Write($img.Bytes)
}

$bw.Flush()
$bw.Dispose()
$fs.Dispose()

Write-Host "    -> $($pngStreams.Count) sizes embedded ($($sizes -join ', ') px)" -ForegroundColor Green

# -----------------------------------------------------------------------------
# 2. Create desktop shortcut
# -----------------------------------------------------------------------------
$desktop = if ($AllUsers) {
    [Environment]::GetFolderPath("CommonDesktopDirectory")
} else {
    [Environment]::GetFolderPath("Desktop")
}

if (-not $desktop) {
    Write-Host "[X] Could not resolve Desktop folder." -ForegroundColor Red
    exit 1
}

$shortcutPath = Join-Path $desktop "$ShortcutName.lnk"
Write-Host ""
Write-Host "[+] Creating shortcut: $shortcutPath" -ForegroundColor Cyan

$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($shortcutPath)
$lnk.TargetPath       = $LauncherPath
$lnk.WorkingDirectory = $AuditorRoot
$lnk.IconLocation     = "$IconPath,0"
$lnk.Description      = "SEO/AEO/GEO Auditor - local web GUI"
$lnk.WindowStyle      = 1   # normal window
$lnk.Save()

Write-Host "    -> shortcut created" -ForegroundColor Green

# -----------------------------------------------------------------------------
# 3. Done
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  DONE." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Double-click '$ShortcutName' on your Desktop."
Write-Host "  It will load API keys, start the GUI, and open your browser."
Write-Host ""
Write-Host "  To uninstall: delete '$shortcutPath'" -ForegroundColor Gray
Write-Host ""
