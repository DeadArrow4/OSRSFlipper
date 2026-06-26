import os
import re
from pathlib import Path

try:
    from account_context import BASE_DIR
except Exception:
    BASE_DIR = Path.cwd()


ENV_FILE = Path(BASE_DIR) / ".env"
SCRUBBED_KEYS = []


def read_dotenv_values(path=None):
    """
    Reads simple KEY=VALUE lines without injecting secrets into os.environ.
    This intentionally does not behave like python-dotenv; it is only for
    non-secret app configuration such as OPENAI_MODEL.
    """
    path = Path(path or ENV_FILE)
    values = {}

    if not path.exists():
        return values

    try:
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            if line.lower().startswith("export "):
                line = line[7:].strip()

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            values[key] = value
    except Exception:
        return values

    return values


def get_non_secret_env_value(key, default=None):
    """
    Reads non-secret config from process env first, then .env.
    This function must not be used for OPENAI_API_KEY.
    """
    if key == "OPENAI_API_KEY":
        raise RuntimeError("OPENAI_API_KEY must not be loaded from .env/environment.")

    value = os.getenv(key)

    if value is not None:
        return value

    return read_dotenv_values().get(key, default)


def dotenv_contains_openai_api_key(path=None):
    path = Path(path or ENV_FILE)

    if not path.exists():
        return False

    pattern = re.compile(r"^\s*(?:export\s+)?OPENAI_API_KEY\s*=", re.IGNORECASE)

    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if pattern.match(line):
                return True
    except Exception:
        return False

    return False


def scrub_shared_openai_env():
    """
    Removes shared OpenAI API keys from the current process environment.

    OSRSFlipper should use encrypted per-account keys only.
    """
    if os.getenv("OSRSFLIPPER_ALLOW_SHARED_OPENAI_KEY", "").strip().lower() in ("1", "true", "yes"):
        return False

    if "OPENAI_API_KEY" in os.environ:
        SCRUBBED_KEYS.append("OPENAI_API_KEY")
        os.environ.pop("OPENAI_API_KEY", None)
        return True

    return False


def scrub_status_text():
    if SCRUBBED_KEYS:
        return "Scrubbed shared OPENAI_API_KEY from current process environment."

    return "No shared OPENAI_API_KEY was present in current process environment."
