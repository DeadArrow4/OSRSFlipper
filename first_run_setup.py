import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path

from account_context import BASE_DIR, apply_account_env, get_account_scope
from account_manager import (
    authenticate_user,
    create_user,
    get_current_session,
    get_user_by_username,
    init_user_db,
    list_users,
    save_session
)
from health_check import run_health_check
from openai_key_manager import (
    get_api_key_status,
    init_api_key_db,
    save_api_key,
    validate_key_shape
)
from openai_usage_manager import init_ai_usage_db
from security_runtime import scrub_shared_openai_env
from settings_manager import ensure_default_settings, get_setting, set_setting
from runelite_paths import DEFAULT_RUNELITE_STATE_PATH, resolve_runelite_state_path


RUNELITE_STATE_PATH = DEFAULT_RUNELITE_STATE_PATH


def heading(title):
    print()
    print("=" * 38)
    print(f" {title}")
    print("=" * 38)


def pause():
    input("\nPress Enter to continue...")


def ask_text(prompt, default=None, required=True):
    while True:
        suffix = f" [{default}]" if default not in (None, "") else ""
        value = input(f"{prompt}{suffix}: ").strip()

        if not value and default not in (None, ""):
            return str(default)

        if value or not required:
            return value

        print("This value is required.")


def ask_int(prompt, default, minimum=None, maximum=None):
    while True:
        raw = ask_text(prompt, default=default, required=True)

        try:
            value = int(float(raw))
        except ValueError:
            print("Enter a whole number.")
            continue

        if minimum is not None and value < minimum:
            print(f"Value must be at least {minimum}.")
            continue

        if maximum is not None and value > maximum:
            print(f"Value must be no more than {maximum}.")
            continue

        return value


def ask_float(prompt, default, minimum=None, maximum=None):
    while True:
        raw = ask_text(prompt, default=default, required=True)

        try:
            value = float(raw)
        except ValueError:
            print("Enter a number.")
            continue

        if minimum is not None and value < minimum:
            print(f"Value must be at least {minimum}.")
            continue

        if maximum is not None and value > maximum:
            print(f"Value must be no more than {maximum}.")
            continue

        return value


def ask_yes_no(prompt, default=False):
    default_text = "Y/n" if default else "y/N"

    while True:
        value = input(f"{prompt} ({default_text}): ").strip().lower()

        if not value:
            return bool(default)

        if value in ("y", "yes"):
            return True

        if value in ("n", "no"):
            return False

        print("Choose yes or no.")


def choose_from(prompt, options, default):
    display = "/".join(options)

    while True:
        value = ask_text(f"{prompt} ({display})", default=default, required=True).lower()

        if value in options:
            return value

        print(f"Choose one of: {display}")


def locate_runelite_file(osrs_account_name):
    return resolve_runelite_state_path()


def show_runelite_status(osrs_account_name):
    runelite_file = locate_runelite_file(osrs_account_name)

    print()
    print("RuneLite / OSRSFlipper Telemetry")
    print("--------------------------------")
    print(f"Expected telemetry file: {runelite_file}")

    if runelite_file.exists():
        print("Status: found")
        return True

    print("Status: not found yet")
    print()
    print("If this is a new setup:")
    print("1. Install OSRSFlipper Telemetry from RuneLite Plugin Hub.")
    print("2. Start normal Jagex-launched RuneLite and log into the OSRS account.")
    print(f"3. Wait for {RUNELITE_STATE_PATH} to be written.")
    print("4. Use the dev client only as a local troubleshooting fallback.")

    return False


def login_existing_user():
    users = list_users()

    if not users:
        print("No existing OSRSFlipper users were found.")
        return None

    print()
    print("Existing users:")

    for index, user in enumerate(users, start=1):
        print(f"{index}. {user['username']} -> {user['osrs_account_name']}")

    while True:
        choice = ask_text("Choose user number or username", required=True)

        selected = None

        if choice.isdigit():
            idx = int(choice) - 1

            if 0 <= idx < len(users):
                selected = users[idx]["username"]

        if selected is None:
            selected = choice.strip().lower()

        user_record = get_user_by_username(selected)

        if not user_record:
            print("User not found.")
            continue

        password = getpass.getpass("Password: ")
        user = authenticate_user(selected, password)

        if not user:
            print("Invalid password.")
            continue

        print(f"Logged in as {user['username']} / {user['osrs_account_name']}")
        return user


def create_new_user():
    print()
    print("Create a local OSRSFlipper account.")
    print("Do NOT use your Jagex/OSRS password.")
    print()

    while True:
        username = ask_text("New local username", required=True).lower()

        if get_user_by_username(username):
            print("That username already exists.")
            continue

        break

    while True:
        password = getpass.getpass("New local password: ")
        confirm = getpass.getpass("Confirm password: ")

        if password != confirm:
            print("Passwords do not match.")
            continue

        if len(password) < 6:
            print("Password must be at least 6 characters.")
            continue

        break

    osrs_account_name = ask_text("RuneLite/OSRS account name", required=True)

    user = create_user(
        username=username,
        password=password,
        osrs_account_name=osrs_account_name
    )

    # Authenticate immediately to create/update session file.
    authenticated = authenticate_user(username, password)

    print(f"Created and logged in as {authenticated['username']} / {authenticated['osrs_account_name']}")
    return authenticated


def choose_or_create_user():
    init_user_db()
    users = list_users()
    session = get_current_session()

    heading("Account Setup")

    if session:
        print(f"Last login: {session.get('username')} / {session.get('osrs_account_name')}")
        if ask_yes_no("Use last login?", default=True):
            save_session(session)
            return session

    if users:
        print("1. Login to existing user")
        print("2. Create new user")
        choice = ask_text("Choose 1 or 2", default="1", required=True)

        if choice == "1":
            user = login_existing_user()

            if user:
                return user

    return create_new_user()


def setup_openai_key(user):
    heading("OpenAI API Key")
    apply_account_env(
        app_username=user["username"],
        osrs_account_name=user["osrs_account_name"]
    )
    init_api_key_db()

    status = get_api_key_status(
        app_username=user["username"],
        osrs_account_name=user["osrs_account_name"]
    )

    if status.get("has_key"):
        print(f"Saved encrypted key already exists: {status.get('key_hint')}")
        print(f"Last used: {status.get('last_used_at') or 'never'}")

        if not ask_yes_no("Replace saved OpenAI key?", default=False):
            return

    print()
    print("This app requires each user to provide their own OpenAI API key.")
    print("The key is encrypted locally with Windows DPAPI and saved for this OSRSFlipper account only.")
    print("The full key will not be displayed after saving.")

    if not ask_yes_no("Save an OpenAI API key now?", default=True):
        print("Skipping key setup. Ask AI will stay disabled until a key is saved.")
        return

    while True:
        api_key = getpass.getpass("Paste OpenAI API key: ").strip()
        valid, message = validate_key_shape(api_key)

        if not valid:
            print(f"Key was not saved: {message}")

            if not ask_yes_no("Try again?", default=True):
                return

            continue

        result = save_api_key(
            api_key,
            app_username=user["username"],
            osrs_account_name=user["osrs_account_name"]
        )

        print(f"Saved encrypted key: {result['key_hint']}")
        return


def setup_user_settings():
    heading("Trading / AI Settings")
    ensure_default_settings()

    cash_stack = ask_int(
        "Default cash stack",
        default=int(get_setting("cash_stack", 10_000_000)),
        minimum=0
    )

    minimum_profit = ask_int(
        "Minimum profit target",
        default=int(get_setting("minimum_profit", 50_000)),
        minimum=0
    )

    risk_profile = choose_from(
        "Risk profile",
        options=["low", "medium", "high"],
        default=str(get_setting("risk_profile", "medium"))
    )

    watch_seconds = ask_int(
        "RuneLite watcher polling seconds",
        default=int(get_setting("watch_seconds", 10)),
        minimum=5
    )

    max_ai_requests = ask_int(
        "Max AI requests per day for this account",
        default=int(get_setting("max_ai_requests_per_day", 20)),
        minimum=0
    )

    set_setting("cash_stack", cash_stack, "int")
    set_setting("minimum_profit", minimum_profit, "int")
    set_setting("risk_profile", risk_profile, "str")
    set_setting("watch_seconds", watch_seconds, "int")
    set_setting("max_ai_requests_per_day", max_ai_requests, "int")

    print()
    print("Saved settings:")
    print(f"- Cash stack: {cash_stack:,}")
    print(f"- Minimum profit: {minimum_profit:,}")
    print(f"- Risk profile: {risk_profile}")
    print(f"- Watch seconds: {watch_seconds}")
    print(f"- Max AI requests/day: {max_ai_requests}")


def initialize_databases(osrs_account_name):
    heading("Initialize Local Data")

    commands = [
        [sys.executable, "trade_tracker.py", "init"],
        [sys.executable, "trade_importer.py", "init"],
    ]

    for command in commands:
        try:
            subprocess.run(
                command,
                cwd=str(BASE_DIR),
                check=False
            )
        except Exception as error:
            print(f"Could not run {' '.join(command)}: {error}")

    init_ai_usage_db()
    ensure_default_settings()

    if show_runelite_status(osrs_account_name):
        if ask_yes_no("Import RuneLite history now?", default=True):
            try:
                subprocess.run(
                    [
                        sys.executable,
                        "trade_importer.py",
                        "import-runelite",
                        "--account",
                        osrs_account_name
                    ],
                    cwd=str(BASE_DIR),
                    check=False
                )
            except Exception as error:
                print(f"RuneLite import failed: {error}")


def run_final_health_check():
    heading("Health Check")

    if not ask_yes_no("Run health check now?", default=True):
        return

    text = run_health_check(write_report=True)
    print(text)
    print()
    print(f"Saved report to: {BASE_DIR / 'logs' / 'health_check.txt'}")


def run_first_run_setup(force=False):
    scrub_shared_openai_env()

    heading("OSRSFlipper First-Run Setup")
    print(f"Project folder: {BASE_DIR}")
    print()
    print("This wizard configures the local user, RuneLite account, encrypted OpenAI key, usage limits, and default trading settings.")

    init_user_db()
    init_api_key_db()
    init_ai_usage_db()

    user = choose_or_create_user()

    apply_account_env(
        app_username=user["username"],
        osrs_account_name=user["osrs_account_name"]
    )

    setup_openai_key(user)
    setup_user_settings()
    initialize_databases(user["osrs_account_name"])
    run_final_health_check()

    heading("Setup Complete")
    print(f"Local user: {user['username']}")
    print(f"OSRS/RuneLite account: {user['osrs_account_name']}")
    print()
    print("You can now start OSRSFlipper with:")
    print("python osrs_control_center.py")
    print()
    return user


def main():
    parser = argparse.ArgumentParser(
        description="OSRSFlipper first-run setup wizard."
    )

    parser.add_argument("--force", action="store_true")

    args = parser.parse_args()

    run_first_run_setup(force=args.force)


if __name__ == "__main__":
    main()
