@echo off
REM Self-updater for the CV screening engine. Safe to run any time.
REM The WorkBuddy expert also runs this quietly before the first screen.
cd /d "%~dp0"
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" scripts\update_engine.py %*
) else (
  where python >nul 2>nul && python scripts\update_engine.py %*
)
