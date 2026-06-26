import json
import os
import sys
from pathlib import Path


DEFAULT_APP_USERNAME = "default"
DEFAULT_OSRS_ACCOUNT = "default"
NORMAL_INSTALL_DIR = Path(r"C:\OSRSFlipper")


def _has_project_markers(path):
    markers = [
        path / "dashboard.py",
        path / "osrs_control_center.py",
        path / "database.py",
        path / "account_context.py",
        path / "assets" / "style.css",
    ]
    return any(marker.exists() for marker in markers)


def resolve_app_base_dir():
    """
    Resolve the real OSRSFlipper project folder.

    This app is expected to run from C:\\OSRSFlipper. Prefer that folder first
    so copied test folders, PyInstaller temporary folders, and old working
    directories do not accidentally become the runtime database/log/session path.

    Fallbacks are only used if C:\\OSRSFlipper does not exist.
    """
    if NORMAL_INSTALL_DIR.exists():
        return NORMAL_INSTALL_DIR.resolve()

    env_dir = os.getenv("OSRSFLIPPER_BASE_DIR", "").strip()

    if env_dir:
        path = Path(env_dir).expanduser().resolve()

        if path.exists() and _has_project_markers(path):
            return path

    candidates = []

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

    try:
        candidates.append(Path.cwd().resolve())
    except Exception:
        pass

    for candidate in candidates:
        if candidate and candidate.exists() and _has_project_markers(candidate):
            return candidate

    # Last resort.
    return Path(__file__).resolve().parent


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
