@echo off
setlocal
title CV Screening - collect diagnostics for support

set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "VPY=%REPO%\venv\Scripts\python.exe"

set "PYTHONIOENCODING=utf-8"

if exist "%VPY%" (
  "%VPY%" "%REPO%\collect_diagnostics.py"
) else (
  where python >nul 2>nul && python "%REPO%\collect_diagnostics.py" || (
    echo Python was not found. Run setup.bat first.
  )
)
echo.
pause
exit /b 0
