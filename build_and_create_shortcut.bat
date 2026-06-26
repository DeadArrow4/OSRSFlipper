@echo off
title Build OSRSFlipper and Create Shortcut
color 0A

set APPDIR=C:\OSRSFlipper

if not exist "%APPDIR%" (
    echo ERROR: Could not find %APPDIR%
    pause
    exit /b 1
)

cd /d "%APPDIR%"

if not exist "build_exe.bat" (
    echo ERROR: build_exe.bat was not found in %APPDIR%
    pause
    exit /b 1
)

call "%APPDIR%\build_exe.bat"

if errorlevel 1 (
    echo.
    echo Build failed. Shortcut was not created.
    pause
    exit /b 1
)

if not exist "create_desktop_shortcut.bat" (
    echo ERROR: create_desktop_shortcut.bat was not found in %APPDIR%
    pause
    exit /b 1
)

call "%APPDIR%\create_desktop_shortcut.bat"

echo.
echo Done.
pause
