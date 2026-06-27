from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = PROJECT_ROOT / "runtime"
STATE_PATH = RUNTIME_DIR / "runelite_state.json"
WRAPPER_DIR = PROJECT_ROOT / "runelite_companion" / "osrsflipper-telemetry-plugin-wrapper"
STALE_AFTER_SECONDS = 120


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return default


def _format_gp(value: Any) -> str:
    amount = _safe_int(value)
    if abs(amount) >= 1_000_000_000:
        return f"{amount / 1_000_000_000:.2f}B gp"
    if abs(amount) >= 1_000_000:
        return f"{amount / 1_000_000:.2f}M gp"
    if abs(amount) >= 1_000:
        return f"{amount / 1_000:.1f}K gp"
    return f"{amount:,} gp"


def read_runelite_state(path: str | Path = STATE_PATH) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        return {}

    try:
        with state_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def build_runelite_telemetry_status(path: str | Path = STATE_PATH) -> dict[str, Any]:
    state_path = Path(path)
    exists = state_path.exists()
    data = read_runelite_state(state_path) if exists else {}

    now = time.time()
    modified_at = state_path.stat().st_mtime if exists else 0
    age_seconds = int(max(0, now - modified_at)) if exists else None
    stale = bool(exists and age_seconds is not None and age_seconds > STALE_AFTER_SECONDS)

    inventory_gp = _safe_int(data.get("inventory_gp"))
    include_bank = bool(data.get("include_bank_gp", True))
    bank_gp = _safe_int(data.get("bank_gp")) if include_bank else 0
    raw_gp = _safe_int(data.get("raw_gp_available"), inventory_gp + bank_gp)

    active_offers = data.get("active_ge_offers") or []
    active_count = len(active_offers) if isinstance(active_offers, list) else 0

    return {
        "exists": exists,
        "path": str(state_path),
        "modified_at": modified_at,
        "age_seconds": age_seconds,
        "stale": stale,
        "payload_kind": data.get("payload_kind") or "unknown",
        "account_name": data.get("account_name") or os.environ.get("RUNELITE_ACCOUNT") or "default",
        "captured_at": data.get("captured_at") or "",
        "raw_gp_available": raw_gp,
        "inventory_gp": inventory_gp,
        "bank_gp": bank_gp,
        "active_offer_count": active_count,
        "open_slots": max(0, 8 - active_count),
    }


def format_runelite_telemetry_status(path: str | Path = STATE_PATH) -> str:
    status = build_runelite_telemetry_status(path)

    if not status["exists"]:
        return (
            "RuneLite telemetry: missing\n"
            f"  Expected file: {status['path']}\n"
            "  Start RuneLite with the OSRSFlipper telemetry plugin, then open the dashboard.\n"
            "  The dashboard will auto-pull once runtime\\runelite_state.json is being written."
        )

    freshness = "stale" if status["stale"] else "fresh"
    age = status["age_seconds"]
    age_text = f"{age}s old" if age is not None else "unknown age"

    return (
        f"RuneLite telemetry: {freshness} ({age_text})\n"
        f"  Account: {status['account_name']}\n"
        f"  Payload: {status['payload_kind']}\n"
        f"  Captured: {status['captured_at']}\n"
        f"  Raw GP: {_format_gp(status['raw_gp_available'])}\n"
        f"  GE offers: {status['active_offer_count']} active, {status['open_slots']} open slots\n"
        f"  File: {status['path']}"
    )


def find_jagex_launcher() -> Path | None:
    candidates: list[Path] = []

    local_appdata = os.environ.get("LOCALAPPDATA")
    program_files = os.environ.get("ProgramFiles")
    program_files_x86 = os.environ.get("ProgramFiles(x86)")

    if local_appdata:
        candidates.append(Path(local_appdata) / "Jagex Launcher" / "JagexLauncher.exe")
    if program_files_x86:
        candidates.append(Path(program_files_x86) / "Jagex Launcher" / "JagexLauncher.exe")
    if program_files:
        candidates.append(Path(program_files) / "Jagex Launcher" / "JagexLauncher.exe")

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def open_jagex_launcher() -> str:
    launcher = find_jagex_launcher()
    if launcher is None:
        return (
            "Jagex Launcher not found in standard locations. "
            "Open it manually, choose RuneLite, then watch telemetry status."
        )

    try:
        os.startfile(str(launcher))  # type: ignore[attr-defined]
        return f"Opened Jagex Launcher: {launcher}"
    except Exception as exc:
        return f"Could not open Jagex Launcher: {exc}"


def start_runelite_telemetry_dev_client() -> str:
    if not WRAPPER_DIR.exists():
        return f"RuneLite telemetry wrapper not found: {WRAPPER_DIR}"

    run_script = WRAPPER_DIR / "run_osrsflipper_telemetry_plugin.bat"
    gradlew = WRAPPER_DIR / "gradlew.bat"

    if run_script.exists():
        cmd = ["cmd", "/c", str(run_script)]
    elif gradlew.exists():
        cmd = ["cmd", "/c", str(gradlew), "run"]
    else:
        return f"No RuneLite telemetry launch script found in {WRAPPER_DIR}"

    env = os.environ.copy()
    env["OSRSFLIPPER_HOME"] = str(PROJECT_ROOT)
    env.setdefault("OSRSFLIPPER_RUNELITE_STATE", str(STATE_PATH))

    try:
        subprocess.Popen(
            cmd,
            cwd=str(WRAPPER_DIR),
            env=env,
            stdin=subprocess.DEVNULL,
        )
        return "Started RuneLite telemetry dev client. Log into OSRS there to write live capital telemetry."
    except Exception as exc:
        return f"Could not start RuneLite telemetry dev client: {exc}"


def import_runelite_state_now() -> str:
    if not STATE_PATH.exists():
        return f"RuneLite telemetry file is missing: {STATE_PATH}"

    try:
        from runelite_state_importer import import_runelite_state

        result = import_runelite_state(STATE_PATH)
        return f"Imported RuneLite telemetry: {result}"
    except Exception as exc:
        return f"Could not import RuneLite telemetry: {exc}"


def dashboard_startup_telemetry_message() -> str:
    return (
        format_runelite_telemetry_status()
        + "\n"
        + "  Control Center commands: python runelite_telemetry_control.py status | open-launcher | start-dev | import"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    command = (args[0].strip().lower() if args else "status")

    if command in {"status", "check"}:
        print(format_runelite_telemetry_status())
        return 0

    if command in {"open-launcher", "launcher", "jagex"}:
        print(open_jagex_launcher())
        return 0

    if command in {"start-dev", "dev", "runelite-dev"}:
        print(start_runelite_telemetry_dev_client())
        return 0

    if command in {"import", "import-now"}:
        print(import_runelite_state_now())
        return 0

    if command in {"stack", "dashboard-stack"}:
        print(open_jagex_launcher())
        print(start_runelite_telemetry_dev_client())
        print(format_runelite_telemetry_status())
        return 0

    print("Usage: python runelite_telemetry_control.py [status|open-launcher|start-dev|import|stack]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
