@echo off
title Find / Remove Shared OpenAI Key
color 0A

set APPDIR=C:\OSRSFlipper

if not exist "%APPDIR%" (
    echo ERROR: Could not find %APPDIR%
    pause
    exit /b 1
)

cd /d "%APPDIR%"

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
)

echo This tool checks .env, current environment, and Windows User/Machine environment variables.
echo.
python remove_shared_openai_key.py --inspect

echo.
echo Choose what to remove:
echo 1. Remove from .env only
echo 2. Remove from .env and Windows USER environment
echo 3. Remove from .env, Windows USER environment, and Windows MACHINE environment
echo 4. Cancel
echo.
set /p CHOICE=Choose 1, 2, 3, or 4: 

if "%CHOICE%"=="1" (
    python remove_shared_openai_key.py
) else if "%CHOICE%"=="2" (
    python remove_shared_openai_key.py --remove-user-env
) else if "%CHOICE%"=="3" (
    python remove_shared_openai_key.py --remove-user-env --remove-machine-env
) else (
    echo Cancelled.
)

echo.
echo Close and reopen PowerShell/control center, then run:
echo python health_check.py
echo.
pause
