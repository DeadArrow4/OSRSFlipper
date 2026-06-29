import argparse
import getpass
import hashlib
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from account_context import BASE_DIR, RUNTIME_DIR, SESSION_FILE
from openai_key_manager import save_api_key, validate_key_shape

DB_FILE = BASE_DIR / "osrs_flip_scanner.db"
PBKDF2_ITERATIONS = 260_000
PIN_MIN_LENGTH = 4
PIN_MAX_LENGTH = 8


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    return sqlite3.connect(DB_FILE)


def init_user_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            osrs_account_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_login_at TEXT
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_app_users_username
        ON app_users(username)
    """)

    cursor.execute("PRAGMA table_info(app_users)")
    existing_columns = {str(row[1]) for row in cursor.fetchall()}

    if "dashboard_pin_hash" not in existing_columns:
        cursor.execute("ALTER TABLE app_users ADD COLUMN dashboard_pin_hash TEXT")

    if "dashboard_pin_salt" not in existing_columns:
        cursor.execute("ALTER TABLE app_users ADD COLUMN dashboard_pin_salt TEXT")

    conn.commit()
    conn.close()
    RUNTIME_DIR.mkdir(exist_ok=True)


def normalize_username(username):
    return str(username or "").strip().lower()


def clean_display_text(value):
    return str(value or "").strip()


def hash_password(password, salt_hex=None):
    if salt_hex is None:
        salt = secrets.token_bytes(32)
    else:
        salt = bytes.fromhex(salt_hex)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS
    )
    return salt.hex(), password_hash.hex()


def verify_password(password, salt_hex, expected_hash_hex):
    _, actual_hash_hex = hash_password(password=password, salt_hex=salt_hex)
    return secrets.compare_digest(actual_hash_hex, expected_hash_hex)


def validate_dashboard_pin(pin):
    pin = str(pin or "").strip()
    if not pin:
        return False, f"PIN is required."
    if not pin.isdigit():
        return False, "PIN must use numbers only."
    if len(pin) < PIN_MIN_LENGTH or len(pin) > PIN_MAX_LENGTH:
        return False, f"PIN must be {PIN_MIN_LENGTH}-{PIN_MAX_LENGTH} digits."
    return True, "PIN is valid."


def hash_dashboard_pin(pin, salt_hex=None):
    return hash_password(f"dashboard-pin:{str(pin or '').strip()}", salt_hex=salt_hex)


def verify_pin_value(pin, salt_hex, expected_hash_hex):
    _, actual_hash_hex = hash_dashboard_pin(pin=pin, salt_hex=salt_hex)
    return secrets.compare_digest(actual_hash_hex, expected_hash_hex)


def get_user_by_username(username):
    init_user_db()
    username = normalize_username(username)
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, password_hash, password_salt,
               dashboard_pin_hash, dashboard_pin_salt,
               osrs_account_name, created_at, updated_at, last_login_at
        FROM app_users
        WHERE username = ?
    """, (username,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_safe_user(username):
    user = get_user_by_username(username)
    if user is None:
        return None
    user.pop("password_hash", None)
    user.pop("password_salt", None)
    user.pop("dashboard_pin_hash", None)
    user.pop("dashboard_pin_salt", None)
    return user


def create_user(username, password, osrs_account_name, dashboard_pin=None):
    init_user_db()
    username = normalize_username(username)
    osrs_account_name = clean_display_text(osrs_account_name)

    if not username:
        raise ValueError("Username cannot be blank.")
    if not password or len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    if not osrs_account_name:
        raise ValueError("OSRS/RuneLite account name cannot be blank.")
    if get_user_by_username(username):
        raise ValueError(f"Username already exists: {username}")

    salt_hex, password_hash_hex = hash_password(password)
    pin_hash_hex = None
    pin_salt_hex = None

    if dashboard_pin is not None:
        valid_pin, pin_message = validate_dashboard_pin(dashboard_pin)
        if not valid_pin:
            raise ValueError(pin_message)
        pin_salt_hex, pin_hash_hex = hash_dashboard_pin(dashboard_pin)

    timestamp = now_utc()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO app_users (
            username, password_hash, password_salt, osrs_account_name,
            dashboard_pin_hash, dashboard_pin_salt,
            created_at, updated_at, last_login_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        username,
        password_hash_hex,
        salt_hex,
        osrs_account_name,
        pin_hash_hex,
        pin_salt_hex,
        timestamp,
        timestamp,
        None,
    ))
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": user_id,
        "username": username,
        "osrs_account_name": osrs_account_name,
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_login_at": None
    }


def save_session(user):
    RUNTIME_DIR.mkdir(exist_ok=True)
    safe_user = {
        "id": user.get("id"),
        "username": user.get("username"),
        "osrs_account_name": user.get("osrs_account_name"),
        "login_at": now_utc()
    }
    SESSION_FILE.write_text(json.dumps(safe_user, indent=2), encoding="utf-8")
    return safe_user


def get_current_session():
    if not SESSION_FILE.exists():
        return None
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def logout():
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
    return True


def user_has_dashboard_pin(username):
    user = get_user_by_username(username)
    if not user:
        return False
    return bool(user.get("dashboard_pin_hash") and user.get("dashboard_pin_salt"))


def verify_dashboard_pin(username, dashboard_pin):
    user = get_user_by_username(username)
    if not user:
        return False
    if not user.get("dashboard_pin_hash") or not user.get("dashboard_pin_salt"):
        return False
    return verify_pin_value(
        pin=dashboard_pin,
        salt_hex=user["dashboard_pin_salt"],
        expected_hash_hex=user["dashboard_pin_hash"]
    )


def set_dashboard_pin(username, password, dashboard_pin):
    init_user_db()
    username = normalize_username(username)
    user = get_user_by_username(username)

    if user is None:
        raise ValueError("User not found.")

    password_valid = verify_password(
        password=password,
        salt_hex=user["password_salt"],
        expected_hash_hex=user["password_hash"]
    )

    if not password_valid:
        raise ValueError("Invalid local password.")

    valid_pin, pin_message = validate_dashboard_pin(dashboard_pin)

    if not valid_pin:
        raise ValueError(pin_message)

    pin_salt_hex, pin_hash_hex = hash_dashboard_pin(dashboard_pin)
    timestamp = now_utc()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE app_users
        SET dashboard_pin_hash = ?,
            dashboard_pin_salt = ?,
            updated_at = ?
        WHERE username = ?
    """, (pin_hash_hex, pin_salt_hex, timestamp, username))
    conn.commit()
    conn.close()

    return get_safe_user(username)


def authenticate_user(username, password):
    init_user_db()
    user = get_user_by_username(username)
    if user is None:
        return None
    valid = verify_password(
        password=password,
        salt_hex=user["password_salt"],
        expected_hash_hex=user["password_hash"]
    )
    if not valid:
        return None

    timestamp = now_utc()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE app_users SET last_login_at = ? WHERE id = ?", (timestamp, user["id"]))
    conn.commit()
    conn.close()

    user["last_login_at"] = timestamp
    user.pop("password_hash", None)
    user.pop("password_salt", None)
    user.pop("dashboard_pin_hash", None)
    user.pop("dashboard_pin_salt", None)
    save_session(user)
    return user


def update_osrs_account(username, osrs_account_name):
    init_user_db()
    username = normalize_username(username)
    osrs_account_name = clean_display_text(osrs_account_name)
    if not osrs_account_name:
        raise ValueError("OSRS/RuneLite account name cannot be blank.")
    if get_user_by_username(username) is None:
        raise ValueError(f"User not found: {username}")

    timestamp = now_utc()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE app_users
        SET osrs_account_name = ?, updated_at = ?
        WHERE username = ?
    """, (osrs_account_name, timestamp, username))
    conn.commit()
    conn.close()

    current = get_current_session()
    if current and current.get("username") == username:
        current["osrs_account_name"] = osrs_account_name
        current["updated_at"] = timestamp
        save_session(current)
    return get_safe_user(username)


def list_users():
    init_user_db()
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, osrs_account_name, created_at, updated_at, last_login_at
        FROM app_users
        ORDER BY username
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows



def prompt_optional_openai_key(user):
    print()
    print("OpenAI API Key")
    print("--------------")
    print("Each OSRSFlipper user should use their own OpenAI API key.")
    print("The key will be encrypted locally with Windows DPAPI and will not be shown again.")
    print()

    add_key = input("Add this user's OpenAI API key now? (y/N): ").strip().lower()

    if add_key not in ("y", "yes"):
        return

    while True:
        api_key = getpass.getpass("Paste OpenAI API key for this OSRSFlipper account: ").strip()
        valid, message = validate_key_shape(api_key)

        if not valid:
            print(f"Key was not saved: {message}")
            retry = input("Try again? (y/N): ").strip().lower()

            if retry not in ("y", "yes"):
                return

            continue

        try:
            result = save_api_key(
                api_key,
                app_username=user["username"],
                osrs_account_name=user["osrs_account_name"]
            )
            print(f"Saved encrypted OpenAI key: {result['key_hint']}")
            return

        except Exception as error:
            print(f"Could not save API key: {error}")
            return


def prompt_create_user():
    print("\n==============================")
    print(" Create OSRSFlipper Account")
    print("==============================")
    print()
    print("This is a local OSRSFlipper login.")
    print("Do NOT enter your real OSRS/Jagex password here.")
    print("Only link your RuneLite/OSRS account name for data collection.")
    print()

    while True:
        username = input("Create local username: ").strip()
        if not username:
            print("Username cannot be blank.")
            continue
        if get_user_by_username(username):
            print("That username already exists.")
            continue
        break

    while True:
        password = getpass.getpass("Create local password: ")
        confirm = getpass.getpass("Confirm local password: ")
        if password != confirm:
            print("Passwords do not match.")
            continue
        if len(password) < 6:
            print("Password must be at least 6 characters.")
            continue
        break

    while True:
        dashboard_pin = getpass.getpass(f"Create dashboard unlock PIN ({PIN_MIN_LENGTH}-{PIN_MAX_LENGTH} digits): ").strip()
        confirm_pin = getpass.getpass("Confirm dashboard unlock PIN: ").strip()
        if dashboard_pin != confirm_pin:
            print("PINs do not match.")
            continue
        valid_pin, pin_message = validate_dashboard_pin(dashboard_pin)
        if not valid_pin:
            print(pin_message)
            continue
        break

    while True:
        osrs_account_name = input("RuneLite/OSRS account name, for example DeadArrow98: ").strip()
        if osrs_account_name:
            break
        print("OSRS/RuneLite account name cannot be blank.")

    user = create_user(
        username=username,
        password=password,
        osrs_account_name=osrs_account_name,
        dashboard_pin=dashboard_pin
    )
    print()
    print(f"Created local account: {user['username']}")
    print(f"Linked OSRS/RuneLite account: {user['osrs_account_name']}")
    authenticated = authenticate_user(username, password)

    if authenticated:
        prompt_optional_openai_key(authenticated)

    return authenticated


def prompt_login():
    print("\n==============================")
    print(" OSRSFlipper Login")
    print("==============================")
    print()
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    user = authenticate_user(username, password)
    if user is None:
        print("Invalid username or password.")
        return None
    print()
    print(f"Logged in as: {user['username']}")
    print(f"Linked OSRS/RuneLite account: {user['osrs_account_name']}")
    return user


def interactive_login_or_create():
    init_user_db()
    users = list_users()
    if not users:
        print("No local OSRSFlipper users exist yet.")
        return prompt_create_user()

    while True:
        print("\n==============================")
        print(" OSRSFlipper Account")
        print("==============================")
        print("1. Login")
        print("2. Create account")
        print("3. Use last login")
        print()
        choice = input("Choose 1, 2, or 3: ").strip()
        if choice == "1":
            user = prompt_login()
            if user:
                return user
        elif choice == "2":
            return prompt_create_user()
        elif choice == "3":
            session = get_current_session()
            if session:
                print()
                print(f"Using last login: {session['username']}")
                print(f"Linked OSRS/RuneLite account: {session['osrs_account_name']}")
                return session
            print("No previous login session found.")
        else:
            print("Invalid choice.")


def print_users():
    users = list_users()
    if not users:
        print("No users found.")
        return
    print("\nLocal OSRSFlipper users:")
    for user in users:
        print(
            f"- {user['username']} -> OSRS/RuneLite: {user['osrs_account_name']} "
            f"(last login: {user.get('last_login_at') or 'never'})"
        )


def main():
    parser = argparse.ArgumentParser(description="Local OSRSFlipper account manager.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init")

    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--username")
    create_parser.add_argument("--osrs-account")

    login_parser = subparsers.add_parser("login")
    login_parser.add_argument("--username")

    subparsers.add_parser("list")
    subparsers.add_parser("whoami")
    subparsers.add_parser("logout")

    set_osrs_parser = subparsers.add_parser("set-osrs")
    set_osrs_parser.add_argument("username")
    set_osrs_parser.add_argument("osrs_account_name")

    args = parser.parse_args()

    if args.command == "init":
        init_user_db()
        print("User database initialized.")
    elif args.command == "create":
        if args.username and args.osrs_account:
            password = getpass.getpass("Create local password: ")
            confirm = getpass.getpass("Confirm local password: ")
            if password != confirm:
                raise RuntimeError("Passwords do not match.")
            dashboard_pin = getpass.getpass(f"Create dashboard unlock PIN ({PIN_MIN_LENGTH}-{PIN_MAX_LENGTH} digits): ").strip()
            confirm_pin = getpass.getpass("Confirm dashboard unlock PIN: ").strip()
            if dashboard_pin != confirm_pin:
                raise RuntimeError("PINs do not match.")
            valid_pin, pin_message = validate_dashboard_pin(dashboard_pin)
            if not valid_pin:
                raise RuntimeError(pin_message)
            user = create_user(args.username, password, args.osrs_account, dashboard_pin=dashboard_pin)
            print(f"Created {user['username']} -> {user['osrs_account_name']}")
        else:
            prompt_create_user()
    elif args.command == "login":
        if args.username:
            password = getpass.getpass("Password: ")
            user = authenticate_user(args.username, password)
            if user is None:
                raise RuntimeError("Invalid username or password.")
            print(f"Logged in as {user['username']} -> {user['osrs_account_name']}")
        else:
            prompt_login()
    elif args.command == "list":
        print_users()
    elif args.command == "whoami":
        session = get_current_session()
        if not session:
            print("Not logged in.")
        else:
            print(f"Logged in as {session['username']} -> {session['osrs_account_name']}")
    elif args.command == "logout":
        logout()
        print("Logged out.")
    elif args.command == "set-osrs":
        user = update_osrs_account(args.username, args.osrs_account_name)
        print(f"Updated {user['username']} -> {user['osrs_account_name']}")


if __name__ == "__main__":
    main()
