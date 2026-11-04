@echo off
setlocal
title CV Screening - environment check

set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "VPY=%REPO%\venv\Scripts\python.exe"

if not exist "%VPY%" (
  echo The environment has not been set up yet.
  echo Run setup.bat first, then run check.bat.
  echo.
  pause
  exit /b 1
)

"%VPY%" "%REPO%\setup_check.py"
echo.
pause
exit /b 0
