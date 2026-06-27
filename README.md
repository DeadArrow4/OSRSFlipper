# OSRSFlipper

## Latest Release: 1.2.0

OSRSFlipper 1.2.0 adds capital-aware AI recommendations, local RuneLite telemetry import, a Capital-Aware RuneLite State panel, and Trade Board capital-fit quantities. RuneLite telemetry is read-only and local-only.


OSRSFlipper is a local Old School RuneScape Grand Exchange flipping dashboard for tracking trades, reviewing flip history, and finding potential item opportunities.

The project is designed to run locally on your machine. Private runtime data such as databases, logs, backups, exports, API keys, and account files should not be committed to GitHub.

## Features

* Local Dash dashboard
* SQLite trade tracking
* RuneLite Flipping Utilities JSON import
* FIFO matched completed flips
* Open and unmatched trade event tracking
* Latest flip candidate view
* Recurring flip candidate view
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
* Git
* RuneLite Flipping Utilities export data, optional
* OpenAI API key, optional

## Local Setup

Clone the repository:

```powershell
git clone https://github.com/DeadArrow4/OSRSFlipper.git
cd OSRSFlipper
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
