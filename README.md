# OSRSFlipper

## Latest Release: 1.2.4

OSRSFlipper 1.2.4 adds 24h market context to scanner recommendations, stores compact local market snapshots for candidate items, and adds optional official Jagex item cross-check helpers. It keeps the 1.2.x capital-aware AI and RuneLite telemetry behavior.


OSRSFlipper is a local Old School RuneScape Grand Exchange flipping dashboard for tracking trades, reviewing flip history, and finding potential item opportunities.

The project is designed to run locally on your machine. Private runtime data such as databases, logs, backups, exports, API keys, and account files should not be committed to GitHub.

## Features

* Local Dash dashboard
* SQLite trade tracking
* OSRSFlipper RuneLite telemetry JSON import
* FIFO matched completed flips
* Open and unmatched trade event tracking
* Latest flip candidate view
* Recurring flip candidate view
* 24h Wiki market context and local candidate market snapshots
* Safety review checklist before trading
* Account-scoped encrypted OpenAI API key support
* Health checks, release checks, backups, and update installer support

## Privacy and Security

This repository intentionally excludes private local runtime data, including:

* `.env` files
* SQLite databases
* logs
* backups
* exports
* release packages
* RuneLite runtime imports
* encrypted account API-key records
* current local user session data

Each user must provide their own OpenAI API key locally inside the app. Shared `.env` API-key fallback is disabled.

Never commit API keys, personal account files, local databases, backup ZIP files, or generated build folders.

## Requirements

* Windows 10 or newer
* Python 3.13 recommended
* Git, only needed when cloning the source repository
* OSRSFlipper RuneLite telemetry plugin, optional
* OpenAI API key, optional

## ZIP Release Setup

For normal local use, install OSRSFlipper into one stable folder:

```text
C:\OSRSFlipper
```

When downloading a GitHub release ZIP:

1. Extract the ZIP.
2. Move or rename the extracted app folder to `C:\OSRSFlipper`.
3. Confirm the final path is `C:\OSRSFlipper\osrs_control_center.py`.
4. Open PowerShell in `C:\OSRSFlipper`.

Current 1.2.x builds use `C:\OSRSFlipper` as the stable runtime folder for the local database, settings, saved session, and telemetry state. Running from a timestamped extracted folder can work on a brand-new machine, but using one stable install folder makes updates and local data safer to reason about.

Create and activate a virtual environment:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\activate
```

Install dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Run first-time setup:

```powershell
python first_run_setup.py
```

Start the control center:

```powershell
python osrs_control_center.py
```

Dashboard URL:

```text
http://127.0.0.1:8050
```

## Updating an Existing Install

Before replacing files in `C:\OSRSFlipper`, run:

```powershell
cd C:\OSRSFlipper
python backup_manager.py --reason pre-update
```

Then run the updater from the extracted release folder:

```powershell
python update_install.py --target C:\OSRSFlipper
```

Or copy the clean release files over the existing `C:\OSRSFlipper` folder, then run:

```powershell
cd C:\OSRSFlipper
python migration_manager.py
python release_check.py
```

## Source Setup

Clone the repository:

```powershell
cd C:\
git clone https://github.com/DeadArrow4/OSRSFlipper.git
cd C:\OSRSFlipper
```

Create and activate a virtual environment:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\activate
```

Install dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Run first-time setup:

```powershell
python first_run_setup.py
```

Start the control center:

```powershell
python osrs_control_center.py
```

Dashboard URL:

```text
http://127.0.0.1:8050
```

## Common Commands

Run the app:

```powershell
python osrs_control_center.py
```

Run a health check:

```powershell
python health_check.py
```

Run a release check:

```powershell
python release_check.py
```

Prepare a release package:

```powershell
python prepare_release.py --run-check
```

Build the executable:

```powershell
.\build_exe.bat
```

## GitHub Release Notes

Generated build folders and executable outputs should not be committed directly to the repository.

Use GitHub Releases for packaged `.exe`, `.zip`, or installer files.

Example release tags:

```text
v1.0.0
v1.0.1
v1.1.0
```

## Project Notes

This tool is for local analytics and decision support. It does not guarantee profit.

Old School RuneScape and RuneScape are trademarks of Jagex. This project is unofficial and is not affiliated with or endorsed by Jagex.
