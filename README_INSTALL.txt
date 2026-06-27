OSRSFlipper Install / Update

Version:
OSRSFlipper 1.0.7-rc1 (release-candidate)

Quick start:
1. Open PowerShell in this folder.
2. Install packages:
   python -m pip install -r requirements.txt
3. Run setup:
   python first_run_setup.py
4. Run release check:
   python release_check.py
5. Start app:
   python osrs_control_center.py

For EXE use:
- If dist\OSRSFlipper.exe is included, run that.
- If not included, run build_exe.bat first.

Private data:
This clean release package intentionally does not include:
- osrs_flip_scanner.db
- .env
- logs
- backups
- exports
- .osrs_runtime
- saved encrypted OpenAI keys

Before updating an existing install:
1. Run:
   python backup_manager.py --reason pre-update
2. Copy these release files over your existing C:\OSRSFlipper folder.
3. Run:
   python migration_manager.py
   python release_check.py
