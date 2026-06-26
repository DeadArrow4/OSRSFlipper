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
