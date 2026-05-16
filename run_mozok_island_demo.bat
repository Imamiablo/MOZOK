@echo off
setlocal EnableExtensions
cd /d "%~dp0"

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

echo Checking game packages...
"%PY%" -c "import pygame, requests" >nul 2>nul
if errorlevel 1 (
  echo Installing game packages. This can take a few minutes.
  "%PY%" -m pip install --upgrade pip
  if errorlevel 1 goto pip_failed
  "%PY%" -m pip install -r requirements-game.txt
  if errorlevel 1 goto pip_failed
) else (
  echo Packages look OK.
)

REM Offline by default. Uncomment these two lines to force live MOZOK API mode.
REM set MOZOK_GAME_USE_API=1
REM set MOZOK_API_BASE_URL=http://127.0.0.1:8001

"%PY%" -m mozok_game.main
pause
exit /b 0

:pip_failed
echo Package installation failed.
echo Check your internet connection and the Python error above.
pause
exit /b 1
