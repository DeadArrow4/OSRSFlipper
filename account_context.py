import json
import os
import sys
from pathlib import Path


DEFAULT_APP_USERNAME = "default"
DEFAULT_OSRS_ACCOUNT = "default"


def resolve_app_base_dir():
    """
    Finds the real C:\\OSRSFlipper folder.

    This matters for the .exe build because PyInstaller extracts bundled
    modules to a temporary folder. We do not want sessions/settings/database
    stored in that temporary folder.
    """
    env_dir = os.getenv("OSRSFLIPPER_BASE_DIR")

    if env_dir:
        path = Path(env_dir).expanduser().resolve()

        if path.exists():
            return path

    candidates = []

    try:
        candidates.append(Path.cwd().resolve())
    except Exception:
        pass

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir)

        if exe_dir.name.lower() == "dist":
            candidates.append(exe_dir.parent)

    try:
        file_dir = Path(__file__).resolve().parent
        candidates.append(file_dir)

        if file_dir.name.lower() == "dist":
            candidates.append(file_dir.parent)

    except Exception:
        pass

    for candidate in candidates:
        if not candidate:
            continue

        markers = [
            candidate / "dashboard.py",
            candidate / "osrs_control_center.py",
            candidate / "osrs_flip_scanner.db",
            candidate / ".venv"
        ]

        if any(marker.exists() for marker in markers):
            return candidate

    # Final fallback for your current install location.
    default_path = Path("C:/OSRSFlipper")

    if default_path.exists():
        return default_path

    # Last resort.
    return Path.cwd().resolve()


BASE_DIR = resolve_app_base_dir()
RUNTIME_DIR = BASE_DIR / ".osrs_runtime"
SESSION_FILE = RUNTIME_DIR / "current_user.json"


def _read_session():
    if not SESSION_FILE.exists():
        return {}

    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_current_app_username(default=DEFAULT_APP_USERNAME):
    value = os.getenv("OSRSFLIPPER_USERNAME")

    if value:
        return str(value).strip().lower()

    session = _read_session()
    value = session.get("username")

    if value:
        return str(value).strip().lower()

    return default


def get_current_osrs_account(default=DEFAULT_OSRS_ACCOUNT):
    value = os.getenv("RUNELITE_ACCOUNT")

    if value:
        return str(value).strip()

    session = _read_session()
    value = session.get("osrs_account_name")

    if value:
        return str(value).strip()

    return default


def get_account_scope(app_username=None, osrs_account_name=None):
    return {
        "app_username": str(app_username or get_current_app_username()).strip().lower(),
        "osrs_account_name": str(osrs_account_name or get_current_osrs_account()).strip()
    }


def apply_account_env(app_username=None, osrs_account_name=None):
    scope = get_account_scope(
        app_username=app_username,
        osrs_account_name=osrs_account_name
    )

    os.environ["OSRSFLIPPER_USERNAME"] = scope["app_username"]
    os.environ["RUNELITE_ACCOUNT"] = scope["osrs_account_name"]
    os.environ["OSRSFLIPPER_BASE_DIR"] = str(BASE_DIR)

    return scope


def account_label(app_username=None, osrs_account_name=None):
    scope = get_account_scope(app_username, osrs_account_name)
    return f"{scope['app_username']} / {scope['osrs_account_name']}"
