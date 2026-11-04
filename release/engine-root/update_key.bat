@echo off
setlocal
title CV Screening - update API key

rem Sits in the engine root, next to .env, check.bat and venv.
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "VPY=%REPO%\venv\Scripts\python.exe"

set "PYTHONIOENCODING=utf-8"

if exist "%VPY%" (
  "%VPY%" "%REPO%\update_key.py"
) else (
  where python >nul 2>nul && python "%REPO%\update_key.py" || (
    echo Python was not found. Run setup.bat first.
  )
)
echo.
pause
exit /b 0
