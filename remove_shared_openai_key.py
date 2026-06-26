import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from account_context import BASE_DIR


ENV_FILE = BASE_DIR / ".env"

OPENAI_KEY_LINE_RE = re.compile(
    r"^\s*(?:export\s+)?OPENAI_API_KEY\s*=",
    re.IGNORECASE
)


def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def mask(value):
    value = str(value or "")

    if not value:
        return "not set"

    if len(value) <= 12:
        return "***"

    return value[:7] + "..." + value[-4:]


def find_openai_key_lines():
    if not ENV_FILE.exists():
        return []

    matches = []

    lines = ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines()

    for index, line in enumerate(lines, start=1):
        if OPENAI_KEY_LINE_RE.match(line):
            matches.append(index)

    return matches


def remove_openai_key_from_env_file(dry_run=False):
    if not ENV_FILE.exists():
        return {
            "changed": False,
            "message": f".env not found: {ENV_FILE}",
            "backup": None,
            "removed_count": 0
        }

    original = ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    kept = []
    removed = []

    for line in original:
        if OPENAI_KEY_LINE_RE.match(line):
            removed.append(line)
            continue

        kept.append(line)

    if not removed:
        return {
            "changed": False,
            "message": "No OPENAI_API_KEY line was found in .env.",
            "backup": None,
            "removed_count": 0
        }

    backup = ENV_FILE.with_name(f".env.backup_before_key_removal_{timestamp()}")

    if dry_run:
        return {
            "changed": True,
            "message": f"Would remove {len(removed)} OPENAI_API_KEY line(s) from .env.",
            "backup": str(backup),
            "removed_count": len(removed)
        }

    shutil.copy2(ENV_FILE, backup)
    ENV_FILE.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")

    return {
        "changed": True,
        "message": f"Removed {len(removed)} OPENAI_API_KEY line(s) from .env.",
        "backup": str(backup),
        "removed_count": len(removed)
    }


def powershell(command):
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command
        ],
        text=True,
        capture_output=True
    )

    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def get_windows_env_var(scope):
    if os.name != "nt":
        return None

    command = (
        f"[Environment]::GetEnvironmentVariable('OPENAI_API_KEY','{scope}')"
    )

    code, stdout, stderr = powershell(command)

    if code != 0:
        return None

    return stdout or None


def remove_windows_env_var(scope):
    if os.name != "nt":
        return False, "Not Windows."

    command = (
        f"[Environment]::SetEnvironmentVariable('OPENAI_API_KEY',$null,'{scope}')"
    )

    code, stdout, stderr = powershell(command)

    if code == 0:
        return True, f"Removed OPENAI_API_KEY from Windows {scope} environment."

    return False, stderr or f"Could not remove OPENAI_API_KEY from Windows {scope} environment."


def inspect_sources():
    sources = []

    env_file_lines = find_openai_key_lines()

    if env_file_lines:
        sources.append(
            f".env contains OPENAI_API_KEY on line(s): {', '.join(str(x) for x in env_file_lines)}"
        )
    else:
        sources.append(".env does not contain an OPENAI_API_KEY assignment.")

    process_value = os.environ.get("OPENAI_API_KEY")

    if process_value:
        sources.append(f"Current process environment has OPENAI_API_KEY: {mask(process_value)}")
    else:
        sources.append("Current process environment does not have OPENAI_API_KEY.")

    if os.name == "nt":
        for scope in ("User", "Machine"):
            value = get_windows_env_var(scope)

            if value:
                sources.append(f"Windows {scope} environment has OPENAI_API_KEY: {mask(value)}")
            else:
                sources.append(f"Windows {scope} environment does not have OPENAI_API_KEY.")

    return sources


def main():
    parser = argparse.ArgumentParser(
        description="Find and safely remove shared OPENAI_API_KEY sources."
    )

    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--remove-user-env", action="store_true")
    parser.add_argument("--remove-machine-env", action="store_true")

    args = parser.parse_args()

    print("Checking shared OPENAI_API_KEY sources...")
    print(f"Project folder: {BASE_DIR}")
    print()

    for line in inspect_sources():
        print(line)

    if args.inspect:
        return

    print()
    result = remove_openai_key_from_env_file(dry_run=args.dry_run)
    print(result["message"])

    if result["backup"]:
        print(f"Backup: {result['backup']}")

    if args.remove_user_env:
        ok, message = remove_windows_env_var("User")
        print(message)

    if args.remove_machine_env:
        ok, message = remove_windows_env_var("Machine")
        print(message)
        if not ok:
            print("Machine-level environment changes may require running PowerShell as Administrator.")

    print()
    print("Important:")
    print("- If the key came from the current PowerShell process, close and reopen PowerShell after removing it.")
    print("- Then run: python health_check.py")
    print("- Keep OPENAI_MODEL in .env if you want; it is not secret.")


if __name__ == "__main__":
    main()
