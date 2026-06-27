OSRSFlipper 1.2.0 - Capital-Aware AI and RuneLite Telemetry

Release type: feature release

Highlights:
- Added local RuneLite telemetry importer for live GP and Grand Exchange offer state.
- Added read-only RuneLite companion plugin scaffold/wrapper for local telemetry export.
- Added capital memory backend for usable GP, locked buy GP, sell-side value, open slots, and stuck offers.
- Added Capital-Aware RuneLite State panel to the Trade Board.
- Added live import/refresh controls and 30-second dashboard refresh for capital state.
- Added AI Advisor capital context so AI recommendations account for usable GP, locked offers, open slots, stuck offers, and low-margin risk.
- Added Trade Board capital-fit columns:
  - Capital Fit
  - Fit Qty
  - Fit Cost
  - Fit Profit
  - Capital Note
- Added capital-fit calculations to scale recommendation quantities to live usable GP and per-trade capital caps.
- Added inspection utilities for RuneLite import, capital dashboard, AI capital context, and Trade Board capital fit.

Safety:
- RuneLite integration is read-only.
- No OSRS clicks, buy/sell actions, cancels, repricing, or automation are performed.
- Telemetry is written to local runtime JSON only.
- Private runtime telemetry files are ignored by Git.
- API keys, database files, backups, and local runtime state remain excluded from releases.

Included:
- Python dashboard and backend updates.
- RuneLite telemetry importer.
- RuneLite companion plugin source/wrapper.
- Capital-aware dashboard panel.
- AI Advisor capital context helper.
- Trade Board capital-fit helper.
- Inspection scripts.
- Runtime example telemetry JSON.

Not included:
- Private database files.
- Saved account data.
- Saved OpenAI API keys.
- Local runtime telemetry JSON.
- Local backup folders.

========================================================================

# OSRSFlipper EXE Build Notes

## What this builds

This creates:

```text
C:\OSRSFlipper\dist\OSRSFlipper.exe
```

The EXE replaces the `.bat` file as the main launcher.

## Important design

This is a lightweight launcher EXE. It still expects the project folder to exist:

```text
C:\OSRSFlipper
```

and it still uses:

```text
C:\OSRSFlipper\.venv\Scripts\python.exe
```

to run child scripts like:

```text
dashboard.py
collector.py
trade_importer.py
advisor.py
```

That is intentional for now. It keeps updates and debugging much easier.

## Build steps

1. Put these files in `C:\OSRSFlipper`:

```text
osrs_control_center.py
build_exe.bat
```

2. Double-click:

```text
build_exe.bat
```

3. Run:

```text
C:\OSRSFlipper\dist\OSRSFlipper.exe
```

## Why osrs_control_center.py was updated

When Python is packaged with PyInstaller, `sys.executable` points to the built EXE instead of Python. The updated control center now detects the project virtual environment and uses:

```text
C:\OSRSFlipper\.venv\Scripts\python.exe
```

for dashboard, collector, and setup subprocesses.

## If the EXE opens then closes

Run it from PowerShell so you can see the error:

```powershell
cd C:\OSRSFlipper\dist
.\OSRSFlipper.exe
```

## If dashboard or collector does not start

Confirm the venv exists:

```powershell
C:\OSRSFlipper\.venv\Scripts\python.exe --version
```

Then confirm packages are installed:

```powershell
cd C:\OSRSFlipper
.\.venv\Scripts\activate
python -m pip install dash plotly pandas requests openai python-dotenv
```
