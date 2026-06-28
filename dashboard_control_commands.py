"""Local dashboard-to-control-center command bridge."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from account_context import RUNTIME_DIR


COMMAND_FILE = Path(RUNTIME_DIR) / "dashboard_command.json"
ALLOWED_COMMANDS = {"refresh_status", "open_dashboard", "stop_all"}


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
