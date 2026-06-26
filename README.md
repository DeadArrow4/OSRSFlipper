# OSRSFlipper

OSRSFlipper is a local Old School RuneScape Grand Exchange flipping dashboard.

## Features

- Local Dash dashboard
- SQLite trade tracking
- RuneLite Flipping Utilities JSON import
- FIFO matched completed flips
- Open/unmatched trade event tracking
- Latest flip candidates
- Recurring flip candidates
- Safety Review pre-trade checklist
- Account-scoped encrypted OpenAI API key support
- Health checks, release checks, backups, and update installer

## Privacy and security

This repository intentionally excludes private runtime data:

- `.env`
- SQLite databases
- logs
- backups
- exports
- release packages
- RuneLite runtime imports
- encrypted account API-key records
- current local user session data

Each user must provide their own OpenAI API key locally inside the app. Shared `.env` API-key fallback is disabled.

## Local setup

```powershell
cd C:\OSRSFlipper
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe first_run_setup.py
.\.venv\Scripts\python.exe osrs_control_center.py
```

Dashboard:

```text
http://127.0.0.1:8050
```

## Release check

```powershell
python release_check.py
```

## Package release

```powershell
python prepare_release.py --run-check
```

## Notes

This tool is for local analytics and decision support. It does not guarantee profit.
