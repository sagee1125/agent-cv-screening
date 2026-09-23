@echo off
REM One-click installer for the CV screening engine (Windows).
REM Installs to C:\agent-cv-screening by default and registers the WorkBuddy expert.
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 goto have_py
where python >nul 2>nul
if %errorlevel%==0 goto have_python
goto no_python

:have_py
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if %errorlevel%==0 (
  py -3 scripts\setup_engine.py %*
  goto done
)
goto no_python

:have_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if %errorlevel%==0 (
  python scripts\setup_engine.py %*
  goto done
)
goto no_python

:no_python
echo Python 3.10 or newer is required.
echo Trying winget (one-time, may take a few minutes)...
where winget >nul 2>nul
if not %errorlevel%==0 goto winget_missing
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
if not %errorlevel%==0 goto winget_missing
echo.
echo Python was installed. Please close this window and run setup.bat again.
pause
exit /b 1

:winget_missing
echo Please install Python first:
echo   1. Open https://www.python.org/downloads/
echo   2. Download and run the installer. IMPORTANT: tick "Add python.exe to PATH".
echo   3. Run setup.bat again.
pause
exit /b 1

:done
echo.
echo (If a window flashed by without messages, run setup.bat from a command prompt
echo  to see the error. Otherwise you can close this window.)
pause
exit /b 0
