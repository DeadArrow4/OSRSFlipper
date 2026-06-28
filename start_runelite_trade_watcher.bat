@echo off
title OSRSFlipper RuneLite Telemetry Watcher
color 0A

set APPDIR=C:\OSRSFlipper
set ACCOUNT=DeadArrow98

if not exist "%APPDIR%" (
    echo ERROR: Could not find %APPDIR%
    pause
    exit /b
)

cd /d "%APPDIR%"

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
)

python trade_importer.py init
python trade_importer.py watch-runelite --account %ACCOUNT%

pause
