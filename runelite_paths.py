from __future__ import annotations

import os
from pathlib import Path

try:
    from account_context import resolve_app_base_dir
except Exception:
    resolve_app_base_dir = None


TELEMETRY_FILE_NAME = "runelite_state.json"
PLUGIN_TELEMETRY_DIR_NAME = "osrsflipper-telemetry"

APP_BASE_DIR = resolve_app_base_dir() if resolve_app_base_dir else Path(__file__).resolve().parent
RUNELITE_DIR = Path.home() / ".runelite"
PLUGIN_TELEMETRY_DIR = RUNELITE_DIR / PLUGIN_TELEMETRY_DIR_NAME
DEFAULT_RUNELITE_STATE_PATH = PLUGIN_TELEMETRY_DIR / TELEMETRY_FILE_NAME
LEGACY_RUNELITE_STATE_PATH = APP_BASE_DIR / "runtime" / TELEMETRY_FILE_NAME


def _expand_path(path: str | Path) -> Path:
    return Path(os.path.expandvars(str(path))).expanduser()


def runelite_state_candidates() -> list[Path]:
    paths: list[Path] = []
    env_path = os.getenv("OSRSFLIPPER_RUNELITE_STATE")

    if env_path:
        paths.append(_expand_path(env_path))

    paths.extend([DEFAULT_RUNELITE_STATE_PATH, LEGACY_RUNELITE_STATE_PATH])

    unique: list[Path] = []
    seen: set[str] = set()

    for path in paths:
        key = str(path.resolve() if path.exists() else path.absolute()).lower()
        if key in seen:
            continue

        seen.add(key)
        unique.append(path)

    return unique


def resolve_runelite_state_path(path: str | Path | None = None) -> Path:
    if path:
        return _expand_path(path).resolve()

    existing = [candidate for candidate in runelite_state_candidates() if candidate.exists()]

    if existing:
        return max(existing, key=lambda candidate: candidate.stat().st_mtime).resolve()

    return DEFAULT_RUNELITE_STATE_PATH.resolve()
