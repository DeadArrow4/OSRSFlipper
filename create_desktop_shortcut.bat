@echo off
title Create OSRSFlipper Desktop Shortcut
color 0A

set APPDIR=C:\OSRSFlipper
set EXE=%APPDIR%\dist\OSRSFlipper.exe
set SHORTCUT_NAME=OSRSFlipper.lnk

if not exist "%APPDIR%" (
    echo ERROR: Could not find %APPDIR%
    pause
    exit /b 1
)

if not exist "%EXE%" (
    echo ERROR: Could not find:
    echo %EXE%
    echo.
    echo Build the EXE first by running:
    echo %APPDIR%\build_exe.bat
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$Desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$ShortcutPath = Join-Path $Desktop '%SHORTCUT_NAME%';" ^
  "$Shell = New-Object -ComObject WScript.Shell;" ^
  "$Shortcut = $Shell.CreateShortcut($ShortcutPath);" ^
  "$Shortcut.TargetPath = '%EXE%';" ^
  "$Shortcut.WorkingDirectory = '%APPDIR%';" ^
  "$Shortcut.IconLocation = '%EXE%,0';" ^
  "$Shortcut.Description = 'OSRSFlipper Control Center';" ^
  "$Shortcut.Save();" ^
  "Write-Host 'Created shortcut:' $ShortcutPath;"

if errorlevel 1 (
    echo.
    echo Shortcut creation failed.
    pause
    exit /b 1
)

echo.
echo Desktop shortcut created successfully.
echo You can now launch OSRSFlipper from your desktop.
echo.
pause
