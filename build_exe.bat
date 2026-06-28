@echo off
title Build OSRSFlipper EXE
color 0A

set APPDIR=C:\OSRSFlipper
set ENTRY=osrs_control_center.py
set EXENAME=OSRSFlipper

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
    echo Create/repair your virtual environment first.
    pause
    exit /b 1
)

echo.
echo ==============================
echo  Installing build tools
echo ==============================
python -m pip install --upgrade pip
python -m pip install pyinstaller

echo.
echo ==============================
echo  Building %EXENAME%.exe
echo ==============================

pyinstaller ^
  --onefile ^
  --console ^
  --clean ^
  --name %EXENAME% ^
  --paths "%APPDIR%" ^
  --hidden-import account_context ^
  --hidden-import account_manager ^
  --hidden-import app_version ^
  --hidden-import prepare_release ^
  --hidden-import update_install ^
  --hidden-import backup_manager ^
  --hidden-import settings_manager ^
  --hidden-import migration_manager ^
  --hidden-import safety_manager ^
  --hidden-import release_check ^
  --hidden-import first_run_setup ^
  --hidden-import security_runtime ^
  --hidden-import openai_key_manager ^
  --hidden-import openai_key_tester ^
  --hidden-import openai_usage_manager ^
  --hidden-import trade_importer ^
  --hidden-import trade_tracker ^
  --hidden-import trade_ai_context ^
  --hidden-import advisor ^
  --hidden-import database ^
  --hidden-import dashboard_callbacks ^
  --hidden-import dashboard_tabs ^
  --hidden-import dashboard_tabs.admin ^
  --hidden-import dashboard_tabs.admin_about ^
  --hidden-import dashboard_tabs.admin_account ^
  --hidden-import dashboard_tabs.admin_data_health ^
  --hidden-import dashboard_tabs.admin_maintenance ^
  --hidden-import dashboard_tabs.admin_safety ^
  --hidden-import dashboard_tabs.admin_settings ^
  --hidden-import dashboard_tabs.admin_setup ^
  --hidden-import dashboard_tabs.admin_status ^
  --hidden-import dashboard_tabs.ai ^
  --hidden-import dashboard_tabs.app_layout ^
  --hidden-import dashboard_tabs.market ^
  --hidden-import dashboard_tabs.overview ^
  --hidden-import dashboard_tabs.trade_board ^
  --hidden-import dashboard_tabs.trades ^
  --hidden-import data_health ^
  --hidden-import data_health_modules ^
  --hidden-import data_health_modules.automation ^
  --hidden-import data_health_modules.backups ^
  --hidden-import data_health_modules.common ^
  --hidden-import data_health_modules.compaction ^
  --hidden-import data_health_modules.maintenance ^
  --hidden-import data_health_modules.metrics ^
  --hidden-import data_health_modules.retention ^
  --hidden-import data_health_modules.schema ^
  --hidden-import data_health_modules.snapshots ^
  --hidden-import data_health_modules.trends ^
  --hidden-import scanner ^
  --hidden-import market_features ^
  --hidden-import api ^
  --hidden-import trend_analyzer ^
  --hidden-import recommender ^
  "%ENTRY%"

if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo ==============================
echo  Build complete
echo ==============================
echo EXE location:
echo %APPDIR%\dist\%EXENAME%.exe
echo.
echo Copy this EXE anywhere inside C:\OSRSFlipper, or run it directly from dist.
echo.
pause
