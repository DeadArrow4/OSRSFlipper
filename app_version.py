from datetime import datetime, timezone
from pathlib import Path

try:
    from account_context import BASE_DIR
except Exception:
    BASE_DIR = Path(__file__).resolve().parent


APP_NAME = "OSRSFlipper"
APP_VERSION = "1.2.2"
BUILD_CHANNEL = "stable"
PROJECT_URL = ""
APP_DESCRIPTION = (
    "Local OSRS Grand Exchange flipping dashboard with trade tracking, "
    "OSRSFlipper RuneLite telemetry import, account-scoped OpenAI advisor, "
    "safety review, health checks, release checks, clean release packaging, "
    "and safe update installation."
)


def get_build_time():
    return "2026-06-28T01:54:04Z"


def get_project_root():
    return Path(BASE_DIR)


def get_version_info():
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "build_channel": BUILD_CHANNEL,
        "build_time": get_build_time(),
        "project_root": str(get_project_root()),
        "description": APP_DESCRIPTION,
    }


def get_version_line():
    info = get_version_info()
    return f"{info['app_name']} {info['app_version']} ({info['build_channel']})"


if __name__ == "__main__":
    info = get_version_info()

    print(f"{info['app_name']} {info['app_version']}")
    print(f"Channel: {info['build_channel']}")
    print(f"Build time: {info['build_time']}")
    print(f"Project root: {info['project_root']}")
