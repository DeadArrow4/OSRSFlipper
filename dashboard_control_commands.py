"""Local dashboard-to-control-center command bridge."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from account_context import RUNTIME_DIR


COMMAND_FILE = Path(RUNTIME_DIR) / "dashboard_command.json"
ALLOWED_COMMANDS = {"refresh_status", "open_dashboard", "stop_all"}
DASHBOARD_URL = "http://127.0.0.1:8050"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_dashboard_command(command: str, source: str = "dashboard") -> dict:
    command = str(command or "").strip().lower()

    if command not in ALLOWED_COMMANDS:
        raise ValueError(f"Unsupported dashboard command: {command}")

    COMMAND_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": uuid4().hex,
        "command": command,
        "source": str(source or "dashboard"),
        "requested_at": _utc_now_iso(),
    }

    temp_path = COMMAND_FILE.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(COMMAND_FILE)

    return payload


def _command_age_seconds(payload: dict) -> float | None:
    try:
        requested_at = datetime.fromisoformat(str(payload.get("requested_at") or ""))
        return (datetime.now(timezone.utc) - requested_at).total_seconds()
    except Exception:
        return None


def consume_dashboard_command(max_age_seconds: int = 30) -> dict | None:
    if not COMMAND_FILE.exists():
        return None

    try:
        payload = json.loads(COMMAND_FILE.read_text(encoding="utf-8"))
    except Exception:
        payload = None

    try:
        COMMAND_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    if not isinstance(payload, dict):
        return None

    command = str(payload.get("command") or "").strip().lower()
    if command not in ALLOWED_COMMANDS:
        return None

    age_seconds = _command_age_seconds(payload)
    if age_seconds is None or age_seconds > max_age_seconds:
        return None

    payload["command"] = command
    return payload


def _windows_creationflags() -> int:
    if os.name != "nt":
        return 0

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return flags


def _windows_dashboard_root_pid(default_pid: int) -> int:
    """Find the top dashboard.py process in Dash's local parent/child pair."""

    if os.name != "nt":
        return default_pid

    script = f"""
$current = Get-CimInstance Win32_Process -Filter "ProcessId = {int(default_pid)}"
$target = {int(default_pid)}
while ($null -ne $current -and $current.ParentProcessId) {{
    $parent = Get-CimInstance Win32_Process -Filter ("ProcessId = {{0}}" -f $current.ParentProcessId)
    if ($null -eq $parent) {{ break }}
    $cmd = [string]$parent.CommandLine
    if ($cmd -notmatch 'dashboard\\.py') {{ break }}
    if ($cmd -notmatch 'OSRSFlipper') {{ break }}
    $target = [int]$parent.ProcessId
    $current = $parent
}}
Write-Output $target
"""

    try:
        output = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
            creationflags=_windows_creationflags(),
        ).strip()
        return int(output.splitlines()[-1])
    except Exception:
        return default_pid


def close_dashboard_app_windows(dashboard_url: str = DASHBOARD_URL) -> None:
    """Close Edge/Chrome app-mode windows opened for the local dashboard."""

    if os.name != "nt":
        return

    url = str(dashboard_url or DASHBOARD_URL).rstrip("/")
    url_slash = f"{url}/"

    script = f"""
$url = @'
{url}
'@
$urlSlash = @'
{url_slash}
'@
$targets = Get-CimInstance Win32_Process | Where-Object {{
    $name = [string]$_.Name
    $cmd = [string]$_.CommandLine
    ($name -match '^(msedge|chrome)(\\.exe)?$') -and
    ($cmd.Contains("--app=$url") -or $cmd.Contains("--app=$urlSlash"))
}}
foreach ($target in $targets) {{
    try {{
        Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
    }} catch {{}}
}}
"""

    try:
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_windows_creationflags(),
        )
    except Exception:
        pass


def schedule_dashboard_shutdown(delay_seconds: float = 1.0) -> None:
    """Terminate the app window and Dash server shortly after the button responds."""

    def shutdown_later() -> None:
        time.sleep(max(0.1, float(delay_seconds or 1.0)))
        current_pid = os.getpid()

        if os.name == "nt":
            close_dashboard_app_windows()
            target_pid = _windows_dashboard_root_pid(current_pid)
            try:
                subprocess.Popen(
                    ["taskkill", "/PID", str(target_pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_windows_creationflags(),
                )
                return
            except Exception:
                pass

        os._exit(0)

    thread = threading.Thread(target=shutdown_later, name="dashboard-shutdown", daemon=True)
    thread.start()
