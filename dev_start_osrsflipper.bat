@echo off
title OSRSFlipper Dev Launcher
color 0B

set APPDIR=C:\OSRSFlipper

if not exist "%APPDIR%" (
    echo ERROR: Could not find %APPDIR%
    pause
    exit /b 1
)

cd /d "%APPDIR%"

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo ERROR: Could not find .venv\Scripts\activate.bat
    echo Create or repair your virtual environment first.
    pause
    exit /b 1
)

echo.
echo ==============================
echo  OSRSFlipper Dev Launcher
echo ==============================
echo Uses current source files directly. No EXE build.
echo Close the dashboard app window or press Q here to stop services.
echo.

python osrs_control_center.py --skip-first-run-check --quiet --dashboard-open-mode app

echo.
echo Dev run stopped.
pause
