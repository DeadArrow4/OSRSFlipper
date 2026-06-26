@echo off
setlocal

cd /d "%~dp0"

echo.
echo ==============================
echo  OSRSFlipper 1.0.0 Release
echo ==============================
echo.

echo Step 1/5: Creating private backup...
python backup_manager.py --reason v1.0.0-release
if errorlevel 1 goto failed

echo.
echo Step 2/5: Running strict release check before build...
python release_check.py --strict
if errorlevel 1 goto failed

echo.
echo Step 3/5: Building OSRSFlipper.exe...
call build_exe.bat
if errorlevel 1 goto failed

echo.
echo Step 4/5: Running strict release check after build...
python release_check.py --strict
if errorlevel 1 goto failed

echo.
echo Step 5/5: Preparing clean release package...
python prepare_release.py --run-check
if errorlevel 1 goto failed

echo.
echo ==============================
echo  OSRSFlipper 1.0.0 is packaged
echo ==============================
echo.
echo Check this folder:
echo C:\OSRSFlipper\releases
echo.
pause
exit /b 0

:failed
echo.
echo ==============================
echo  RELEASE FAILED
echo ==============================
echo.
echo Review the error above and the logs folder:
echo C:\OSRSFlipper\logs
echo.
pause
exit /b 1
