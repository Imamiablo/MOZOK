@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo === MOZOK Island full launcher ===
echo This starts PostgreSQL, Mozok API, imports the island pack, then opens the game in API mode.
echo.

where docker >nul 2>nul
if errorlevel 1 (
  echo Docker was not found in PATH.
  echo Install/open Docker Desktop first, then run this file again.
  pause
  exit /b 1
)

echo Starting PostgreSQL...
docker compose up -d
if errorlevel 1 (
  echo Failed to start PostgreSQL through Docker Compose.
  pause
  exit /b 1
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" --version >nul 2>nul
  if errorlevel 1 (
    echo Existing .venv looks broken. Moving it aside and creating a fresh one.
    ren ".venv" ".venv.broken.%RANDOM%.%RANDOM%"
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3.11 -m venv .venv 2>nul
    if errorlevel 1 py -3.10 -m venv .venv
  ) else (
    where python >nul 2>nul
    if errorlevel 1 (
      echo Python was not found. Install Python 3.10+ and run this file again.
      pause
      exit /b 1
    )
    python -m venv .venv
  )
)

set "PY=.venv\Scripts\python.exe"

echo Checking Python packages...
"%PY%" -c "import fastapi, uvicorn, sqlalchemy, pydantic_settings, faiss, pygame, requests" >nul 2>nul
if errorlevel 1 (
  echo Installing backend and game packages. This can take a few minutes.
  "%PY%" -m pip install --upgrade pip
  if errorlevel 1 goto pip_failed
  "%PY%" -m pip install -r requirements.txt -r requirements-game.txt
  if errorlevel 1 goto pip_failed
) else (
  echo Packages look OK.
)

if not exist ".env" (
  if exist ".env.example" (
    copy ".env.example" ".env" >nul
    echo Created .env from .env.example
  )
)

echo Waiting for PostgreSQL...
timeout /t 5 /nobreak >nul

echo Initialising database...
"%PY%" -m scripts.init_db
if errorlevel 1 (
  echo Database initialisation failed.
  pause
  exit /b 1
)

if exist "data\brain_packs\island_sandbox_demo_brain_pack.json" (
  echo Importing island brain pack...
  "%PY%" -m scripts.import_brain_pack data\brain_packs\island_sandbox_demo_brain_pack.json --world-id island_demo
  if errorlevel 1 echo Brain pack import reported a problem; continuing so the offline fallback can still run.
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8001/' -TimeoutSec 1; if ($r.StatusCode -lt 500) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
if errorlevel 1 (
  echo Starting Mozok API in a separate window...
  start "MOZOK API :8001" cmd /k call "%PY%" -m uvicorn mozok.api.main:app --host 127.0.0.1 --port 8001 --log-level info
) else (
  echo Mozok API already seems to be running on http://127.0.0.1:8001
)

echo Waiting for Mozok API...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; for ($i=0; $i -lt 45; $i++) { try { $r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8001/' -TimeoutSec 1; if ($r.StatusCode -lt 500) { $ok=$true; break } } catch { Start-Sleep -Seconds 1 } }; if ($ok) { exit 0 } else { exit 1 }"
if errorlevel 1 (
  echo Mozok API did not answer in time. The game will still open with its safe fallback if needed.
)

echo.
echo Starting Island Sandbox in MOZOK API mode...
echo API docs: http://127.0.0.1:8001/docs
echo.

set "MOZOK_GAME_USE_API=1"
set "MOZOK_API_BASE_URL=http://127.0.0.1:8001"
"%PY%" -m mozok_game.main
pause
exit /b 0

:pip_failed
echo Package installation failed.
echo Check your internet connection and the Python error above.
pause
exit /b 1
