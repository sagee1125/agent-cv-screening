@echo off
REM Run one screening command with the private interpreter already installed here.
REM WorkBuddy must call this file. Do not create another Python environment.
cd /d "%~dp0"
"%~dp0venv\Scripts\python.exe" "%~dp0.codex\skills\host-envelope\scripts\run_workbuddy_tool.py" %*
