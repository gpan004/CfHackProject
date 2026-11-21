# Starts the backend (FastAPI on :8000) and the frontend (Vite on :5173) in two windows,
# then opens the UI in the browser. Close a window (or press Ctrl+C in it) to stop that part.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root "..\env\Scripts\python.exe"
$frontend = Join-Path $root "frontend"

if (-not (Test-Path $python)) { throw "Python venv not found at $python" }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw "npm not found - install Node.js LTS and reopen the terminal" }
if (-not (Test-Path (Join-Path $root ".env"))) { Write-Warning ".env not found - copy .env.example to .env first" }

if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "Installing frontend dependencies (first run only)..."
    Push-Location $frontend; try { npm.cmd install } finally { Pop-Location }
}

# stop anything left over from a previous run, otherwise the new servers can't bind their ports
& (Join-Path $root "stop.ps1")

$llm = (Get-Content (Join-Path $root ".env") -ErrorAction SilentlyContinue | Where-Object { $_ -match '^LOCAL_LLM_BASE_URL=' }) -replace '^LOCAL_LLM_BASE_URL=', ''
if ($llm) {
    try { Invoke-RestMethod "$llm/models" -TimeoutSec 10 | Out-Null; Write-Host "Local LLM reachable: $llm" -ForegroundColor Green }
    catch { Write-Warning "Local LLM NOT reachable at $llm - is the Colab notebook running and the URL in .env up to date?" }
}

Start-Process powershell -WorkingDirectory $root -ArgumentList "-NoExit", "-Command",
    "`$Host.UI.RawUI.WindowTitle = 'Ingaze BACKEND :8000'; & '$python' -m uvicorn backend.main:app --reload --port 8000"
Start-Process powershell -WorkingDirectory $frontend -ArgumentList "-NoExit", "-Command",
    "`$Host.UI.RawUI.WindowTitle = 'Ingaze FRONTEND :5173'; npm.cmd run dev"

Write-Host "Waiting for the backend and frontend to come up..."
$deadline = (Get-Date).AddSeconds(90)
$up = $false
while ((Get-Date) -lt $deadline) {
    # check listening sockets, not HTTP: uvicorn binds IPv4 and Vite binds IPv6, and "localhost" fallback is slow
    $ports = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 8000, 5173 } |
               Select-Object -ExpandProperty LocalPort -Unique)
    if ($ports.Count -ge 2) { $up = $true; break }
    Start-Sleep -Seconds 2
}
if ($up) { Write-Host "Ready: http://localhost:5173" -ForegroundColor Green }
else { Write-Warning "Not up after 90s - check the two new windows for errors. Opening the browser anyway." }
Start-Process "http://localhost:5173"
