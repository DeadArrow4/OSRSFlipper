from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from account_context import resolve_app_base_dir
except Exception:
    resolve_app_base_dir = None

PROJECT_ROOT = resolve_app_base_dir() if resolve_app_base_dir else Path(__file__).resolve().parent
RUNTIME_DIR = PROJECT_ROOT / "runtime"
LOG_DIR = PROJECT_ROOT / "logs"
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
    last_offers = data.get("lastOffers") or {}
    last_offer_count = len(last_offers) if isinstance(last_offers, dict) else 0
    trades = data.get("trades") or []
    completed_offer_count = 0

    if isinstance(trades, list):
        for trade in trades:
            if not isinstance(trade, dict):
                continue

            history = trade.get("h") or {}
            offers = history.get("sO") if isinstance(history, dict) else []

            if isinstance(offers, list):
                completed_offer_count += len(offers)

    ready = bool(exists and not stale and (data.get("payload_kind") or "unknown") != "minimal")
    if not exists:
        problem = "telemetry file is missing"
    elif stale:
        problem = "telemetry file is stale"
    elif (data.get("payload_kind") or "unknown") == "minimal":
        problem = "telemetry payload is minimal; log into OSRS in the telemetry client for full capital data"
    else:
        problem = ""

    account_name = data.get("account_name") or os.environ.get("RUNELITE_ACCOUNT") or "default"
    preserved_raw_gp = 0
    preserved_snapshot_id = None

    if exists and raw_gp <= 0 and account_name != "default":
        try:
            from capital_ai_memory import latest_nonzero_capital_snapshot

            preserved = latest_nonzero_capital_snapshot(str(account_name))
            if preserved:
                preserved_raw_gp = _safe_int(preserved.get("raw_gp_available"))
                preserved_snapshot_id = preserved.get("id")
        except Exception:
            preserved_raw_gp = 0
            preserved_snapshot_id = None

    effective_raw_gp = preserved_raw_gp if preserved_raw_gp > 0 and raw_gp <= 0 else raw_gp

    return {
        "exists": exists,
        "path": str(state_path),
        "modified_at": modified_at,
        "age_seconds": age_seconds,
        "stale": stale,
        "ready": ready,
        "problem": problem,
        "payload_kind": data.get("payload_kind") or "unknown",
        "account_name": account_name,
        "captured_at": data.get("captured_at") or "",
        "raw_gp_available": raw_gp,
        "effective_raw_gp_available": effective_raw_gp,
        "preserved_raw_gp_available": preserved_raw_gp,
        "preserved_snapshot_id": preserved_snapshot_id,
        "inventory_gp": inventory_gp,
        "bank_gp": bank_gp,
        "active_offer_count": active_count,
        "open_slots": max(0, 8 - active_count),
        "last_offer_count": last_offer_count,
        "completed_offer_count": completed_offer_count,
    }


def format_runelite_telemetry_status(path: str | Path = STATE_PATH) -> str:
    status = build_runelite_telemetry_status(path)

    if not status["exists"]:
        return (
            "RuneLite telemetry: missing\n"
            f"  Expected file: {status['path']}\n"
            "  Normal Jagex-launched RuneLite only writes this if the OSRSFlipper plugin is installed there.\n"
            "  Until then, run: python runelite_telemetry_control.py start-dev"
        )

    freshness = "stale" if status["stale"] else "fresh"
    age = status["age_seconds"]
    age_text = f"{age}s old" if age is not None else "unknown age"
    readiness = "ready" if status["ready"] else f"not ready - {status['problem']}"

    gp_line = f"  Raw GP: {_format_gp(status['raw_gp_available'])}"
    if status.get("preserved_raw_gp_available"):
        gp_line += (
            f" (file), effective {_format_gp(status['effective_raw_gp_available'])} "
            f"from preserved snapshot {status.get('preserved_snapshot_id')}"
        )

    text = (
        f"RuneLite telemetry: {freshness} ({age_text})\n"
        f"  Readiness: {readiness}\n"
        f"  Account: {status['account_name']}\n"
        f"  Payload: {status['payload_kind']}\n"
        f"  Captured: {status['captured_at']}\n"
        f"{gp_line}\n"
        f"  GE offers: {status['active_offer_count']} active, {status['open_slots']} open slots\n"
        f"  Trade telemetry: {status['last_offer_count']} last offers, {status['completed_offer_count']} completed offer events\n"
        f"  File: {status['path']}"
    )

    if not status["ready"]:
        text += (
            "\n  Guidance: launch the telemetry dev client, log into OSRS there, "
            "and wait for a fresh full payload."
        )

    return text


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
    LOG_DIR.mkdir(exist_ok=True)
    stdout_path = LOG_DIR / "runelite_telemetry_dev_client.log"
    stderr_path = LOG_DIR / "runelite_telemetry_dev_client_error.log"
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    stdout = None
    stderr = None

    try:
        stdout = stdout_path.open("a", encoding="utf-8")
        stderr = stderr_path.open("a", encoding="utf-8")
        subprocess.Popen(
            cmd,
            cwd=str(WRAPPER_DIR),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )
        return (
            "Started RuneLite telemetry dev client. Log into OSRS there to write live capital telemetry. "
            f"Dev output is logged to {stdout_path}."
        )
    except Exception as exc:
        return f"Could not start RuneLite telemetry dev client: {exc}"
    finally:
        for handle in (stdout, stderr):
            if handle is not None:
                handle.close()


def import_runelite_state_now() -> str:
    status = build_runelite_telemetry_status()

    if not status["exists"]:
        return f"RuneLite telemetry file is missing: {STATE_PATH}"

    if not status["ready"]:
        return f"Skipped RuneLite telemetry import: {status['problem']}."

    try:
        from runelite_state_importer import import_runelite_state

        result = import_runelite_state(STATE_PATH)
        return f"Imported RuneLite telemetry: {result}"
    except Exception as exc:
        return f"Could not import RuneLite telemetry: {exc}"


def plugin_package_status() -> str:
    try:
        from runelite_plugin_packager import format_plugin_package_status

        return format_plugin_package_status()
    except Exception as exc:
        return f"Could not inspect RuneLite plugin package: {exc}"


def package_runelite_plugin() -> str:
    try:
        from runelite_plugin_packager import format_plugin_package_status, package_plugin_repository

        result = package_plugin_repository()
        return result["message"] + "\n\n" + format_plugin_package_status(result["status"])
    except Exception as exc:
        return f"Could not package RuneLite plugin: {exc}"


def build_runelite_plugin() -> str:
    try:
        from runelite_plugin_packager import build_plugin

        result = build_plugin()
        prefix = "RuneLite plugin build passed." if result["ok"] else f"RuneLite plugin build failed with exit code {result['returncode']}."
        return prefix + "\n" + str(result.get("output", "")).strip()
    except Exception as exc:
        return f"Could not build RuneLite plugin: {exc}"


def dashboard_startup_telemetry_message() -> str:
    return (
        format_runelite_telemetry_status()
        + "\n"
        + "  Control Center commands: python runelite_telemetry_control.py status | open-launcher | start-dev | import | plugin-status | package-plugin"
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

    if command in {"plugin-status", "package-status"}:
        print(plugin_package_status())
        return 0

    if command in {"package-plugin", "plugin-package"}:
        print(package_runelite_plugin())
        return 0

    if command in {"build-plugin", "plugin-build"}:
        print(build_runelite_plugin())
        return 0

    if command in {"stack", "dashboard-stack"}:
        print(open_jagex_launcher())
        print(start_runelite_telemetry_dev_client())
        print(format_runelite_telemetry_status())
        return 0

    print("Usage: python runelite_telemetry_control.py [status|open-launcher|start-dev|import|plugin-status|package-plugin|build-plugin|stack]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
