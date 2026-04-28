$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Mozok launcher ===" -ForegroundColor Cyan
Write-Host ""

Set-Location $PSScriptRoot

if (!(Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "No .venv found. Creating venv..." -ForegroundColor Yellow

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        py -3.10 -m venv .venv
    } else {
        python -m venv .venv
    }
}

$python = ".\.venv\Scripts\python.exe"

Write-Host "Using Python:" -ForegroundColor Green
& $python --version

Write-Host ""
Write-Host "Checking Python packages..." -ForegroundColor Cyan

$needInstall = $false
& $python -c "import fastapi, uvicorn, sqlalchemy, pydantic_settings, faiss" 2>$null
if ($LASTEXITCODE -ne 0) {
    $needInstall = $true
}

if ($needInstall) {
    Write-Host "Installing requirements..." -ForegroundColor Yellow
    & $python -m pip install --upgrade pip
    & $python -m pip install -r requirements.txt
} else {
    Write-Host "Python packages look OK." -ForegroundColor Green
}

if (!(Test-Path ".\.env")) {
    if (Test-Path ".\.env.example") {
        Copy-Item ".\.env.example" ".\.env"
        Write-Host "Created .env from .env.example" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "Checking Docker..." -ForegroundColor Cyan

$docker = Get-Command docker -ErrorAction SilentlyContinue
if (!$docker) {
    Write-Host ""
    Write-Host "Docker is NOT installed or not in PATH." -ForegroundColor Red
    Write-Host ""
    Write-Host "Mozok currently needs Docker Desktop to run PostgreSQL easily." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Install Docker Desktop from:" -ForegroundColor Cyan
    Write-Host "https://www.docker.com/products/docker-desktop/"
    Write-Host ""
    Write-Host "After installation:"
    Write-Host "1. Restart Windows if Docker asks."
    Write-Host "2. Open Docker Desktop once and wait until it says it is running."
    Write-Host "3. Double-click start_mozok.bat again."
    Write-Host ""
    exit 1
}

Write-Host "Starting PostgreSQL container..." -ForegroundColor Cyan
docker compose up -d

Write-Host "Waiting for PostgreSQL to wake up..." -ForegroundColor Cyan
Start-Sleep -Seconds 5

Write-Host "Creating database tables if needed..." -ForegroundColor Cyan
& $python -m scripts.init_db

Write-Host ""
Write-Host "Starting Mozok API..." -ForegroundColor Green
Write-Host "Open this in browser:" -ForegroundColor Cyan
Write-Host "http://127.0.0.1:8000/docs"
Write-Host ""

& $python -m uvicorn mozok.api.main:app --reload
