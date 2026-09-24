@echo off
REM One-click installer for the CV screening engine (Windows).
REM Provisions a PRIVATE Python 3.12 with uv (about 30 MB, one time). The
REM machine's own Python is never used, changed or required - no admin rights,
REM nothing installed system-wide.
setlocal
cd /d "%~dp0"

set TARGET=C:\agent-cv-screening
mkdir "%TARGET%" >nul 2>nul
if not exist "%TARGET%" set TARGET=%USERPROFILE%\agent-cv-screening
mkdir "%TARGET%" >nul 2>nul
if not exist "%TARGET%" goto no_target

set TOOLS=%TARGET%\tools
mkdir "%TOOLS%" >nul 2>nul
set UV=%TOOLS%\uv.exe
if exist "%UV%" goto have_uv

echo Fetching the installer helper (uv, about 17 MB, one time)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile '%TEMP%\uv.zip' -UseBasicParsing; Expand-Archive -Force '%TEMP%\uv.zip' '%TEMP%\uvunpack' } catch { exit 1 }"
if not %errorlevel%==0 goto no_uv
copy /y "%TEMP%\uvunpack\uv.exe" "%UV%" >nul 2>nul
if not exist "%UV%" goto no_uv

:have_uv
echo Setting up a private Python 3.12 (about 30 MB, one time)...
"%UV%" python install 3.12
if not %errorlevel%==0 goto uv_failed

"%UV%" venv --python 3.12 "%TARGET%\venv"
if not %errorlevel%==0 goto uv_failed

echo Installing the screening components (a few minutes)...
"%UV%" pip install --python "%TARGET%\venv\Scripts\python.exe" -r "engine\requirements.txt"
if not %errorlevel%==0 goto uv_failed

"%TARGET%\venv\Scripts\python.exe" scripts\setup_engine.py --engine-target "%TARGET%" --skip-venv %*
goto done

:no_target
echo Could not create a folder for the engine. Please run this installer from
echo an account that can write to C:\ or to your own user folder.
pause
exit /b 1

:no_uv
echo.
echo Could not download the installer helper. Check the internet connection
echo (the download comes from github.com) and run setup.bat again.
pause
exit /b 1

:uv_failed
echo.
echo Setup did not finish. Scroll up for the last error message.
echo If it mentions the network, check the connection and run setup.bat again.
pause
exit /b 1

:done
echo.
echo (If a window flashed by without messages, run setup.bat from a command
echo  prompt to see the error. Otherwise you can close this window.)
pause
exit /b 0
