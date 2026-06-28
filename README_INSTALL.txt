OSRSFlipper Install / Update

Version:
OSRSFlipper 1.2.0 (stable)

New install:
1. Move or rename this extracted app folder to:
   C:\OSRSFlipper
2. Confirm this file exists:
   C:\OSRSFlipper\osrs_control_center.py
3. Open PowerShell in C:\OSRSFlipper.
4. Install packages:
   python -m pip install -r requirements.txt
5. Run setup:
   python first_run_setup.py
6. Run release check:
   python release_check.py
7. Start app:
   python osrs_control_center.py

Why C:\OSRSFlipper:
Current 1.2.x builds use C:\OSRSFlipper as the stable runtime folder for
the local database, settings, saved session, and telemetry state. Running
from a timestamped extracted folder can work on a brand-new machine, but
one stable install folder makes updates and local data safer to reason about.

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
2. From this extracted release folder, run:
   python update_install.py --target C:\OSRSFlipper
3. Or copy these release files over your existing C:\OSRSFlipper folder.
4. Run:
   python migration_manager.py
   python release_check.py
