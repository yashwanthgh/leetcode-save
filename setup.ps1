# Installer for Windows. macOS and Linux users: run setup.sh instead.
#
#   .\setup.ps1
#
# If PowerShell refuses to run it, allow local scripts for this session first:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script = Join-Path $ScriptDir "leetcode_save.py"
$Rule = "------------------------------------------------------------"

Write-Host ""
Write-Host "Installing leetcode-save"
Write-Host $Rule
Write-Host ""

# ---------------------------------------------------------------- requirements
Write-Host "Step 1 of 4: checking what you already have"

$Python = $null
foreach ($candidate in @("python", "python3", "py")) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $found) { continue }
    $ok = & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $Python = $found.Source; break }
}

if (-not $Python) {
    Write-Host "  Python 3.8+   MISSING"
    Write-Host ""
    Write-Host "This tool is written in Python, so you need it installed first."
    Write-Host "Get it from https://python.org/downloads or the Microsoft Store."
    Write-Host "During install, tick 'Add Python to PATH'."
    exit 1
}
$PyVersion = & $Python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
Write-Host "  Python        $PyVersion"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "  git           MISSING"
    Write-Host ""
    Write-Host "Your solutions are stored in a git repo, so git is required."
    Write-Host "Get it from https://git-scm.com/download/win"
    exit 1
}
$GitVersion = (git --version) -replace 'git version ', ''
Write-Host "  git           $GitVersion"

if (Get-Command gh -ErrorAction SilentlyContinue) {
    $GhVersion = ((gh --version) -split "`n")[0] -replace 'gh version ', ''
    Write-Host "  GitHub CLI    $GhVersion"
} else {
    Write-Host "  GitHub CLI    not installed (optional)"
    Write-Host "                Without it, you'll be asked to point at a repo you"
    Write-Host "                cloned yourself instead of it making one for you."
}
Write-Host ""

# ------------------------------------------------------------------- packages
Write-Host "Step 2 of 4: installing the Python packages it needs"
Write-Host "  (requests, python-dotenv, html2text)"

& $Python -m pip install --quiet --user -r (Join-Path $ScriptDir "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "  FAILED to install packages."
    Write-Host ""
    Write-Host "Try running this yourself to see the error:"
    Write-Host "  $Python -m pip install --user -r `"$(Join-Path $ScriptDir 'requirements.txt')`""
    exit 1
}
Write-Host "  done"
Write-Host ""

# -------------------------------------------------------------------- command
Write-Host "Step 3 of 4: creating the 'leetcode-save' command"

$BinDir = Join-Path $env:LOCALAPPDATA "leetcode-save\bin"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

# A .cmd shim is the portable way to expose a Python script as a command.
$Shim = Join-Path $BinDir "leetcode-save.cmd"
"@echo off`r`n`"$Python`" `"$Script`" %*" | Set-Content -Path $Shim -Encoding ASCII
Write-Host "  installed at $Shim"
Write-Host ""

# --------------------------------------------------------------------- verify
Write-Host "Step 4 of 4: checking that it runs"

& $Python $Script --help | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  The command was installed but failed to start."
    Write-Host "  Run this to see why:  $Python `"$Script`" --help"
    exit 1
}
Write-Host "  works"
Write-Host ""

# ----------------------------------------------------------------- PATH notes
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $UserPath) { $UserPath = "" }

$NeedsNewTerminal = $false
if ($UserPath -split ';' -notcontains $BinDir) {
    [Environment]::SetEnvironmentVariable("Path", ($UserPath.TrimEnd(';') + ";" + $BinDir), "User")
    $NeedsNewTerminal = $true
}
if ($env:Path -split ';' -notcontains $BinDir) {
    $NeedsNewTerminal = $true
}

Write-Host $Rule
if ($NeedsNewTerminal) {
    Write-Host "IMPORTANT: close this window and open a NEW terminal now." -ForegroundColor Yellow
    Write-Host "Windows only picks up the updated PATH in new windows, so" -ForegroundColor Yellow
    Write-Host "'leetcode-save' will say 'not recognized' until you do." -ForegroundColor Yellow
    Write-Host ""
}
Write-Host "Setup finished. Two things left to do."
Write-Host ""
Write-Host "1. Log in to LeetCode:"
Write-Host ""
Write-Host "     leetcode-save --login"
Write-Host ""
Write-Host "   It prints instructions and waits. You'll copy one thing"
Write-Host "   out of Chrome and paste it in. Takes about 30 seconds."
Write-Host ""
Write-Host "2. From then on, whenever you solve a problem:"
Write-Host ""
Write-Host "     leetcode-save"
Write-Host ""
Write-Host "   That saves it to GitHub. Safe to run any time -- it only"
Write-Host "   saves what's new and never touches what's already saved."
Write-Host ""
Write-Host $Rule
