@echo off
title OSRSFlipper Control Center
color 0A

set APPDIR=C:\OSRSFlipper

if not exist "%APPDIR%" (
    echo ERROR: Could not find %APPDIR%
    pause
    exit /b
)

cd /d "%APPDIR%"

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
)

python osrs_control_center.py

echo.
pause
