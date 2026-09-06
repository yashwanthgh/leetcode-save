# Windows installer for leetcode-save.
# Run in PowerShell:  .\setup.ps1

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script = Join-Path $ScriptDir "leetcode_save.py"

# Find a Python 3. 'python3' is not always present on Windows.
$Python = $null
foreach ($candidate in @("python", "python3", "py")) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) {
        $version = & $candidate -c "import sys; print(sys.version_info[0])" 2>$null
        if ($version -eq "3") { $Python = $found.Source; break }
    }
}

if (-not $Python) {
    Write-Host "Python 3 not found. Install it from https://python.org or the Microsoft Store."
    exit 1
}

Write-Host "==> Using $Python"
Write-Host "==> Installing Python dependencies..."
& $Python -m pip install --quiet --user -r (Join-Path $ScriptDir "requirements.txt")

# Put a .cmd shim somewhere stable and add it to the user PATH.
$BinDir = Join-Path $env:LOCALAPPDATA "leetcode-save\bin"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

$Shim = Join-Path $BinDir "leetcode-save.cmd"
"@echo off`r`n`"$Python`" `"$Script`" %*" | Set-Content -Path $Shim -Encoding ASCII

Write-Host "==> Installed shim to $Shim"

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$UserPath;$BinDir", "User")
    Write-Host "==> Added $BinDir to your user PATH"
    Write-Host ""
    Write-Host "IMPORTANT: open a NEW terminal window before continuing," -ForegroundColor Yellow
    Write-Host "so it picks up the updated PATH." -ForegroundColor Yellow
} else {
    Write-Host "==> $BinDir is already on your PATH"
}

Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Log in (it tells you exactly what to paste):"
Write-Host "       leetcode-save --login"
Write-Host ""
Write-Host "  2. Solve something on leetcode.com, then run:"
Write-Host "       leetcode-save"
Write-Host ""
Write-Host "That's it. --login finds your solutions repo, or offers to create"
Write-Host "one for you. You never have to edit a config file by hand."
