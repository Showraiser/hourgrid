# HourGrid one-command local demo for Windows PowerShell:
#   anvil (local blockchain) + backend (deploys contracts automatically) + frontend.
#
#   Run from the repo root:   powershell -ExecutionPolicy Bypass -File .\run_local.ps1
#
# Needs: Python 3.11+, Node 20+, and anvil.exe (Foundry). If anvil is missing this
# script downloads Foundry for Windows into %USERPROFILE%\.foundry\bin and adds it to PATH.
# `forge build` is NOT required: prebuilt contracts ship in contracts\artifacts.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---- Foundry (anvil) -------------------------------------------------------
if (-not (Get-Command anvil -ErrorAction SilentlyContinue)) {
    $bin = Join-Path $env:USERPROFILE ".foundry\bin"
    if (-not (Test-Path (Join-Path $bin "anvil.exe"))) {
        Write-Host "> downloading Foundry for Windows..."
        New-Item -ItemType Directory -Force $bin | Out-Null
        $zip = Join-Path $env:TEMP "foundry_win.zip"
        Invoke-WebRequest "https://github.com/foundry-rs/foundry/releases/download/stable/foundry_stable_win32_amd64.zip" -OutFile $zip
        Expand-Archive $zip -DestinationPath $bin -Force
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        if ($userPath -notlike "*$bin*") { [Environment]::SetEnvironmentVariable("Path", "$userPath;$bin", "User") }
    }
    $env:Path += ";$bin"
}

# ---- local chain ----------------------------------------------------------
Write-Host "> anvil (local chain on :8545)"
$anvil = Start-Process anvil -ArgumentList "--block-time", "1" -PassThru -WindowStyle Minimized

# ---- backend --------------------------------------------------------------
Write-Host "> backend (:8000)"
Set-Location (Join-Path $root "backend")
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    .\.venv\Scripts\python -m pip install -q -r requirements.txt
}
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
$env:CHAIN_ENABLED = "1"
$backend = Start-Process ".\.venv\Scripts\python" -ArgumentList "-m", "uvicorn", "hourgrid.api:app", "--port", "8000" -PassThru -NoNewWindow

# ---- frontend -------------------------------------------------------------
Write-Host "> frontend (:3000)"
Set-Location (Join-Path $root "frontend")
if (-not (Test-Path "node_modules")) { npm install }
if (-not (Test-Path ".env.local")) { Copy-Item ".env.example" ".env.local" }

Write-Host ""
Write-Host "  Dashboard: http://localhost:3000    API docs: http://localhost:8000/docs"
Write-Host "  First start deploys the contracts and onboards 25 meters (~1 minute)."
Write-Host "  Press Ctrl+C to stop everything."
try {
    npm run dev
} finally {
    Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $anvil.Id -ErrorAction SilentlyContinue
}
