@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Could not find .venv\Scripts\python.exe
  echo Run from the prototype root, or create/install the venv first.
  pause
  exit /b 1
)

REM Offline by default. Uncomment these two lines to force live MOZOK API mode.
REM set MOZOK_GAME_USE_API=1
REM set MOZOK_API_BASE_URL=http://127.0.0.1:8001

".venv\Scripts\python.exe" -m mozok_game.main
pause
