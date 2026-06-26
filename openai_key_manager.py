import argparse
import base64
import ctypes
import getpass
import os
import sqlite3
import sys
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

from account_context import BASE_DIR, get_account_scope


DB_FILE = BASE_DIR / "osrs_flip_scanner.db"
PROVIDER = "openai"


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char))
    ]


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    return sqlite3.connect(DB_FILE)


def is_windows():
    return os.name == "nt"


def _blob_from_bytes(data):
    buffer = ctypes.create_string_buffer(data)
    blob = DATA_BLOB()
    blob.cbData = len(data)
    blob.pbData = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))
    return blob, buffer


def _bytes_from_blob(blob):
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def protect_secret(secret_text, purpose="OSRSFlipper OpenAI API key"):
    """
    Encrypts a secret for the current Windows user using DPAPI.

    On Windows this means the encrypted value can only be decrypted by the
    same Windows profile. This avoids storing API keys in plain text.
    """
    secret_text = str(secret_text or "")

    if not secret_text:
        raise ValueError("Secret cannot be blank.")

    secret_bytes = secret_text.encode("utf-8")

    if not is_windows():
        # Fallback for non-Windows development only.
        # Your production app target is Windows, where DPAPI is used.
        return "plain-dev:" + base64.b64encode(secret_bytes).decode("ascii")

    in_blob, in_buffer = _blob_from_bytes(secret_bytes)
    out_blob = DATA_BLOB()

    description = ctypes.c_wchar_p(purpose)

    result = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        description,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob)
    )

    if not result:
        raise ctypes.WinError()

    encrypted = _bytes_from_blob(out_blob)

    return "dpapi:" + base64.b64encode(encrypted).decode("ascii")


def unprotect_secret(encrypted_text):
    encrypted_text = str(encrypted_text or "")

    if not encrypted_text:
        return None

    if encrypted_text.startswith("plain-dev:"):
        return base64.b64decode(encrypted_text.split(":", 1)[1]).decode("utf-8")

    if not encrypted_text.startswith("dpapi:"):
        raise ValueError("Unknown encrypted secret format.")

    if not is_windows():
        raise RuntimeError("DPAPI encrypted secrets can only be decrypted on Windows.")

    encrypted = base64.b64decode(encrypted_text.split(":", 1)[1])

    in_blob, in_buffer = _blob_from_bytes(encrypted)
    out_blob = DATA_BLOB()

    result = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob)
    )

    if not result:
        raise ctypes.WinError()

    decrypted = _bytes_from_blob(out_blob)

    return decrypted.decode("utf-8")


def mask_key(api_key):
    api_key = str(api_key or "").strip()

    if not api_key:
        return "not set"

    if len(api_key) <= 12:
        return "***"

    return api_key[:7] + "..." + api_key[-4:]


def validate_key_shape(api_key):
    api_key = str(api_key or "").strip()

    if not api_key:
        return False, "API key is blank."

    # OpenAI key prefixes can vary by key type/project, so keep this broad.
    if not api_key.startswith("sk-"):
        return False, "OpenAI API keys usually start with sk-."

    if len(api_key) < 30:
        return False, "API key looks too short."

    if any(char.isspace() for char in api_key):
        return False, "API key should not contain spaces or line breaks."

    return True, "API key format looks valid."


def init_api_key_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS account_api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_username TEXT NOT NULL,
            osrs_account_name TEXT NOT NULL,
            provider TEXT NOT NULL,
            encrypted_api_key TEXT NOT NULL,
            key_hint TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_used_at TEXT,
            UNIQUE(app_username, osrs_account_name, provider)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_account_api_keys_account
        ON account_api_keys(app_username, osrs_account_name, provider)
    """)

    conn.commit()
    conn.close()


def save_api_key(api_key, app_username=None, osrs_account_name=None, provider=PROVIDER):
    init_api_key_db()

    api_key = str(api_key or "").strip()

    valid, message = validate_key_shape(api_key)

    if not valid:
        raise ValueError(message)

    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)
    encrypted = protect_secret(api_key)
    timestamp = now_utc()
    hint = mask_key(api_key)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO account_api_keys (
            app_username,
            osrs_account_name,
            provider,
            encrypted_api_key,
            key_hint,
            created_at,
            updated_at,
            last_used_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(app_username, osrs_account_name, provider)
        DO UPDATE SET
            encrypted_api_key = excluded.encrypted_api_key,
            key_hint = excluded.key_hint,
            updated_at = excluded.updated_at
    """, (
        scope["app_username"],
        scope["osrs_account_name"],
        provider,
        encrypted,
        hint,
        timestamp,
        timestamp
    ))

    conn.commit()
    conn.close()

    return {
        "app_username": scope["app_username"],
        "osrs_account_name": scope["osrs_account_name"],
        "provider": provider,
        "key_hint": hint,
        "updated_at": timestamp
    }


def get_api_key_record(app_username=None, osrs_account_name=None, provider=PROVIDER):
    init_api_key_db()

    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            app_username,
            osrs_account_name,
            provider,
            encrypted_api_key,
            key_hint,
            created_at,
            updated_at,
            last_used_at
        FROM account_api_keys
        WHERE app_username = ?
          AND osrs_account_name = ?
          AND provider = ?
    """, (
        scope["app_username"],
        scope["osrs_account_name"],
        provider
    ))

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    return dict(row)


def get_api_key(app_username=None, osrs_account_name=None, provider=PROVIDER, mark_used=True):
    record = get_api_key_record(app_username, osrs_account_name, provider)

    if record is None:
        return None

    api_key = unprotect_secret(record["encrypted_api_key"])

    if mark_used:
        mark_api_key_used(app_username, osrs_account_name, provider)

    return api_key


def mark_api_key_used(app_username=None, osrs_account_name=None, provider=PROVIDER):
    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE account_api_keys
        SET last_used_at = ?
        WHERE app_username = ?
          AND osrs_account_name = ?
          AND provider = ?
    """, (
        now_utc(),
        scope["app_username"],
        scope["osrs_account_name"],
        provider
    ))

    conn.commit()
    conn.close()


def delete_api_key(app_username=None, osrs_account_name=None, provider=PROVIDER):
    init_api_key_db()

    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM account_api_keys
        WHERE app_username = ?
          AND osrs_account_name = ?
          AND provider = ?
    """, (
        scope["app_username"],
        scope["osrs_account_name"],
        provider
    ))

    deleted = cursor.rowcount

    conn.commit()
    conn.close()

    return deleted


def get_api_key_status(app_username=None, osrs_account_name=None, provider=PROVIDER):
    record = get_api_key_record(app_username, osrs_account_name, provider)
    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)

    if record is None:
        return {
            "app_username": scope["app_username"],
            "osrs_account_name": scope["osrs_account_name"],
            "provider": provider,
            "has_key": False,
            "key_hint": "not set",
            "created_at": None,
            "updated_at": None,
            "last_used_at": None
        }

    return {
        "app_username": record["app_username"],
        "osrs_account_name": record["osrs_account_name"],
        "provider": record["provider"],
        "has_key": True,
        "key_hint": record["key_hint"] or "set",
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "last_used_at": record["last_used_at"]
    }


def print_status():
    status = get_api_key_status()

    print("\n==============================")
    print(" OpenAI API Key Status")
    print("==============================")
    print(f"Local user: {status['app_username']}")
    print(f"OSRS/RuneLite account: {status['osrs_account_name']}")
    print(f"Provider: {status['provider']}")
    print(f"Has key: {status['has_key']}")
    print(f"Key hint: {status['key_hint']}")
    print(f"Created: {status['created_at'] or 'n/a'}")
    print(f"Updated: {status['updated_at'] or 'n/a'}")
    print(f"Last used: {status['last_used_at'] or 'n/a'}")


def prompt_save_key():
    print("\n==============================")
    print(" Save OpenAI API Key")
    print("==============================")
    print("This key will be encrypted with Windows DPAPI and linked to the current OSRSFlipper account.")
    print("The full key will not be displayed again.")
    print()

    api_key = getpass.getpass("Paste OpenAI API key: ").strip()

    result = save_api_key(api_key)

    print()
    print(f"Saved key for {result['app_username']} / {result['osrs_account_name']}")
    print(f"Key hint: {result['key_hint']}")


def main():
    parser = argparse.ArgumentParser(
        description="Encrypted per-account OpenAI API key manager."
    )

    parser.add_argument("--user", default=None)
    parser.add_argument("--account", default=None)

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")
    subparsers.add_parser("status")
    subparsers.add_parser("set")
    subparsers.add_parser("delete")

    args = parser.parse_args()

    if args.command == "init":
        init_api_key_db()
        print("API key database initialized.")
        return

    if args.command == "status":
        print_status()
        return

    if args.command == "set":
        prompt_save_key()
        return

    if args.command == "delete":
        confirm = input("Type DELETE API KEY to remove the current account API key: ").strip()

        if confirm != "DELETE API KEY":
            print("Cancelled.")
            return

        deleted = delete_api_key(
            app_username=args.user,
            osrs_account_name=args.account
        )

        print(f"Deleted rows: {deleted}")
        return


if __name__ == "__main__":
    main()
