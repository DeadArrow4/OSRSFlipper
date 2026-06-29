import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from account_context import get_account_scope, BASE_DIR


DB_FILE = BASE_DIR / "osrs_flip_scanner.db"
SQLITE_TIMEOUT_SECONDS = 3
SQLITE_BUSY_TIMEOUT_MS = 3000
_SETTINGS_DB_INITIALIZED = False


DEFAULT_SETTINGS = {
    # Control center / collector
    "cash_stack": {"value": 10_000_000, "type": "int", "description": "Default cash stack used by collector.py."},
    "minimum_profit": {"value": 50_000, "type": "int", "description": "Default minimum profit used by collector.py."},
    "risk_profile": {"value": "medium", "type": "str", "description": "Default risk profile: low, medium, or high."},
    "watch_seconds": {"value": 10, "type": "int", "description": "RuneLite trade watcher polling interval in seconds."},
    "capital_budget_mode": {"value": "live_capped", "type": "str", "description": "Collector budget mode: manual, live, or live_capped."},

    # Startup behavior
    "start_dashboard": {"value": True, "type": "bool", "description": "Start dashboard automatically."},
    "start_collector": {"value": True, "type": "bool", "description": "Start market collector automatically."},
    "start_trade_watcher": {"value": True, "type": "bool", "description": "Start RuneLite trade watcher automatically."},
    "open_browser": {"value": True, "type": "bool", "description": "Open dashboard in browser when control center starts."},
    "dashboard_open_mode": {"value": "app", "type": "str", "description": "Open dashboard as app-style window or normal browser tab."},
    "control_center_status_mode": {"value": "quiet", "type": "str", "description": "Control center console mode: quiet or status."},
    "open_jagex_launcher_with_dashboard": {"value": False, "type": "bool", "description": "Open Jagex Launcher when the dashboard starts."},
    "auto_start_runelite_telemetry_dev_client": {"value": False, "type": "bool", "description": "Start the RuneLite telemetry dev client when the dashboard starts."},

    # AI advisor behavior
    "ai_source_row_limit": {"value": 350, "type": "int", "description": "How many scanner rows advisor.py can consider."},
    "ai_quick_choices": {"value": 10, "type": "int", "description": "Maximum quick flips the AI should suggest."},
    "ai_overnight_choices": {"value": 10, "type": "int", "description": "Maximum overnight flips the AI should suggest."},
    "ai_value_choices": {"value": 10, "type": "int", "description": "Maximum additional valuable flips the AI should suggest."},
    "exclude_items_traded_today": {"value": True, "type": "bool", "description": "Prevent AI from recommending items already traded today."},
    "max_ai_requests_per_day": {"value": 20, "type": "int", "description": "Maximum AI requests allowed per account per UTC day. Set to 0 to disable AI for the account."},
    "ai_input_cost_per_1m_tokens": {"value": 0.0, "type": "float", "description": "Input token cost in dollars per 1M tokens for AI cost estimates."},
    "ai_output_cost_per_1m_tokens": {"value": 0.0, "type": "float", "description": "Output token cost in dollars per 1M tokens for AI cost estimates."},

    # Overnight / loss-cut rules
    "overnight_slot_target": {"value": 1, "type": "int", "description": "Target GE slots to reserve for longer overnight flips. Use 0, 1, or 2."},
    "min_overnight_raw_margin": {"value": 10_000, "type": "int", "description": "Minimum raw margin per item for overnight recommendations."},
    "min_overnight_roi_percent": {"value": 5.0, "type": "float", "description": "Minimum ROI percent for overnight recommendations."},
    "max_small_loss_percent": {"value": 2.0, "type": "float", "description": "Small controlled-loss threshold for slot recovery."},
    "max_medium_loss_percent": {"value": 5.0, "type": "float", "description": "Medium controlled-loss threshold for stale slot recovery."},

    # Trade safety controls
    "max_single_item_cash_percent": {"value": 10.0, "type": "float", "description": "Maximum percent of cash stack to risk on one item test."},
    "max_test_quantity": {"value": 25, "type": "int", "description": "Maximum suggested first-test quantity for a single item."},
}


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    conn = sqlite3.connect(DB_FILE, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    return conn


def is_database_locked_error(error):
    text = str(error).lower()
    return "database is locked" in text or "database table is locked" in text


def default_for_setting(key, default=None):
    normalized = normalize_key(key)

    if normalized in DEFAULT_SETTINGS:
        return DEFAULT_SETTINGS[normalized]["value"]

    return default


def normalize_key(key):
    return str(key or "").strip()


def serialize_value(value, value_type):
    if value_type == "bool":
        return "true" if bool(value) else "false"

    if value_type == "json":
        return json.dumps(value)

    return str(value)


def deserialize_value(value, value_type):
    if value is None:
        return None

    if value_type == "int":
        return int(float(value))

    if value_type == "float":
        return float(value)

    if value_type == "bool":
        return str(value).strip().lower() in ("1", "true", "yes", "y", "on")

    if value_type == "json":
        return json.loads(value)

    return str(value)


def infer_type(value):
    if isinstance(value, bool):
        return "bool"

    if isinstance(value, int) and not isinstance(value, bool):
        return "int"

    if isinstance(value, float):
        return "float"

    if isinstance(value, (dict, list)):
        return "json"

    return "str"


def parse_input_value(raw_value, value_type):
    raw_value = str(raw_value).strip()

    if value_type == "bool":
        if raw_value.lower() in ("1", "true", "yes", "y", "on"):
            return True

        if raw_value.lower() in ("0", "false", "no", "n", "off"):
            return False

        raise ValueError("Use true/false, yes/no, or on/off.")

    if value_type == "int":
        return int(float(raw_value.replace(",", "")))

    if value_type == "float":
        return float(raw_value.replace(",", ""))

    if value_type == "json":
        return json.loads(raw_value)

    return raw_value


def init_settings_db(force=False):
    global _SETTINGS_DB_INITIALIZED

    if _SETTINGS_DB_INITIALIZED and not force:
        return

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_username TEXT NOT NULL,
                osrs_account_name TEXT NOT NULL,
                setting_key TEXT NOT NULL,
                setting_value TEXT NOT NULL,
                value_type TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(app_username, osrs_account_name, setting_key)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_app_settings_account
            ON app_settings(app_username, osrs_account_name)
        """)

        conn.commit()
        _SETTINGS_DB_INITIALIZED = True
    finally:
        conn.close()


def set_setting(key, value, value_type=None, description=None, app_username=None, osrs_account_name=None):
    init_settings_db()

    key = normalize_key(key)

    if not key:
        raise ValueError("Setting key cannot be blank.")

    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)

    if value_type is None:
        value_type = infer_type(value)

    serialized = serialize_value(value, value_type)

    if description is None and key in DEFAULT_SETTINGS:
        description = DEFAULT_SETTINGS[key].get("description")

    timestamp = now_utc()

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO app_settings (
                app_username,
                osrs_account_name,
                setting_key,
                setting_value,
                value_type,
                description,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(app_username, osrs_account_name, setting_key)
            DO UPDATE SET
                setting_value = excluded.setting_value,
                value_type = excluded.value_type,
                description = excluded.description,
                updated_at = excluded.updated_at
        """, (
            scope["app_username"],
            scope["osrs_account_name"],
            key,
            serialized,
            value_type,
            description,
            timestamp,
            timestamp
        ))

        conn.commit()
    finally:
        conn.close()


def get_setting(key, default=None, app_username=None, osrs_account_name=None):
    key = normalize_key(key)

    try:
        init_settings_db()
    except sqlite3.OperationalError as error:
        if is_database_locked_error(error):
            return default_for_setting(key, default)
        raise

    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT setting_value, value_type
            FROM app_settings
            WHERE app_username = ?
              AND osrs_account_name = ?
              AND setting_key = ?
        """, (
            scope["app_username"],
            scope["osrs_account_name"],
            key
        ))

        row = cursor.fetchone()
    except sqlite3.OperationalError as error:
        if is_database_locked_error(error):
            return default_for_setting(key, default)
        raise
    finally:
        conn.close()

    if row is None:
        return default_for_setting(key, default)

    value, value_type = row

    try:
        return deserialize_value(value, value_type)
    except Exception:
        return default


def get_all_settings(app_username=None, osrs_account_name=None, include_defaults=True):
    settings = {}

    if include_defaults:
        for key, meta in DEFAULT_SETTINGS.items():
            settings[key] = {
                "key": key,
                "value": meta["value"],
                "type": meta["type"],
                "description": meta.get("description", ""),
                "source": "default"
            }

    try:
        init_settings_db()
    except sqlite3.OperationalError as error:
        if is_database_locked_error(error):
            return settings
        raise

    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT setting_key, setting_value, value_type, description, updated_at
            FROM app_settings
            WHERE app_username = ?
              AND osrs_account_name = ?
            ORDER BY setting_key
        """, (
            scope["app_username"],
            scope["osrs_account_name"]
        ))

        for key, value, value_type, description, updated_at in cursor.fetchall():
            settings[key] = {
                "key": key,
                "value": deserialize_value(value, value_type),
                "type": value_type,
                "description": description or "",
                "updated_at": updated_at,
                "source": "saved"
            }
    except sqlite3.OperationalError as error:
        if not is_database_locked_error(error):
            raise
    finally:
        conn.close()

    return settings


def ensure_default_settings(app_username=None, osrs_account_name=None):
    try:
        init_settings_db()
    except sqlite3.OperationalError as error:
        if is_database_locked_error(error):
            return
        raise

    for key, meta in DEFAULT_SETTINGS.items():
        existing = get_setting(
            key,
            default=None,
            app_username=app_username,
            osrs_account_name=osrs_account_name
        )

        # get_setting returns default even when not saved, so check DB directly.
        scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)

        conn = get_connection()

        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT 1
                FROM app_settings
                WHERE app_username = ?
                  AND osrs_account_name = ?
                  AND setting_key = ?
            """, (
                scope["app_username"],
                scope["osrs_account_name"],
                key
            ))

            exists = cursor.fetchone() is not None
        except sqlite3.OperationalError as error:
            if is_database_locked_error(error):
                return
            raise
        finally:
            conn.close()

        if not exists:
            try:
                set_setting(
                    key=key,
                    value=meta["value"],
                    value_type=meta["type"],
                    description=meta.get("description"),
                    app_username=app_username,
                    osrs_account_name=osrs_account_name
                )
            except sqlite3.OperationalError as error:
                if is_database_locked_error(error):
                    return
                raise


def prompt_bool(prompt, default):
    default_text = "Y/n" if default else "y/N"

    while True:
        raw = input(f"{prompt} [{default_text}]: ").strip()

        if not raw:
            return bool(default)

        if raw.lower() in ("y", "yes", "true", "1", "on"):
            return True

        if raw.lower() in ("n", "no", "false", "0", "off"):
            return False

        print("Use yes or no.")


def prompt_value(prompt, default, value_type, allowed=None):
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()

        if raw == "":
            return default

        try:
            value = parse_input_value(raw, value_type)
        except Exception as error:
            print(f"Invalid value: {error}")
            continue

        if allowed and value not in allowed:
            print(f"Use one of: {', '.join(str(x) for x in allowed)}")
            continue

        return value


def configure_core_settings(app_username=None, osrs_account_name=None):
    init_settings_db()

    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)

    print("\n==============================")
    print(" OSRSFlipper Settings")
    print("==============================")
    print(f"Local user: {scope['app_username']}")
    print(f"OSRS/RuneLite account: {scope['osrs_account_name']}")
    print()

    current_cash = get_setting("cash_stack", app_username=app_username, osrs_account_name=osrs_account_name)
    current_min_profit = get_setting("minimum_profit", app_username=app_username, osrs_account_name=osrs_account_name)
    current_risk = get_setting("risk_profile", app_username=app_username, osrs_account_name=osrs_account_name)
    current_watch_seconds = get_setting("watch_seconds", app_username=app_username, osrs_account_name=osrs_account_name)
    current_budget_mode = get_setting("capital_budget_mode", app_username=app_username, osrs_account_name=osrs_account_name)

    cash_stack = prompt_value("Cash stack", current_cash, "int")
    minimum_profit = prompt_value("Minimum profit", current_min_profit, "int")
    risk_profile = prompt_value("Risk profile", current_risk, "str", allowed=["low", "medium", "high"])
    watch_seconds = prompt_value("Trade watcher seconds", current_watch_seconds, "int")
    capital_budget_mode = prompt_value(
        "Capital budget mode",
        current_budget_mode,
        "str",
        allowed=["manual", "live", "live_capped"]
    )

    start_dashboard = prompt_bool(
        "Start dashboard automatically",
        get_setting("start_dashboard", app_username=app_username, osrs_account_name=osrs_account_name)
    )

    start_collector = prompt_bool(
        "Start market collector automatically",
        get_setting("start_collector", app_username=app_username, osrs_account_name=osrs_account_name)
    )

    start_trade_watcher = prompt_bool(
        "Start RuneLite trade watcher automatically",
        get_setting("start_trade_watcher", app_username=app_username, osrs_account_name=osrs_account_name)
    )

    open_browser = prompt_bool(
        "Open dashboard in browser automatically",
        get_setting("open_browser", app_username=app_username, osrs_account_name=osrs_account_name)
    )

    open_jagex_launcher_with_dashboard = prompt_bool(
        "Open Jagex Launcher with dashboard",
        get_setting("open_jagex_launcher_with_dashboard", app_username=app_username, osrs_account_name=osrs_account_name)
    )

    auto_start_runelite_telemetry_dev_client = prompt_bool(
        "Start RuneLite telemetry dev client with dashboard",
        get_setting("auto_start_runelite_telemetry_dev_client", app_username=app_username, osrs_account_name=osrs_account_name)
    )

    values = {
        "cash_stack": cash_stack,
        "minimum_profit": minimum_profit,
        "risk_profile": risk_profile,
        "watch_seconds": watch_seconds,
        "capital_budget_mode": capital_budget_mode,
        "start_dashboard": start_dashboard,
        "start_collector": start_collector,
        "start_trade_watcher": start_trade_watcher,
        "open_browser": open_browser,
        "open_jagex_launcher_with_dashboard": open_jagex_launcher_with_dashboard,
        "auto_start_runelite_telemetry_dev_client": auto_start_runelite_telemetry_dev_client
    }

    for key, value in values.items():
        meta = DEFAULT_SETTINGS[key]
        set_setting(
            key=key,
            value=value,
            value_type=meta["type"],
            description=meta.get("description"),
            app_username=app_username,
            osrs_account_name=osrs_account_name
        )

    print()
    print("Settings saved.")
    return values


def configure_ai_settings(app_username=None, osrs_account_name=None):
    init_settings_db()
    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)

    print("\n==============================")
    print(" OSRSFlipper AI Settings")
    print("==============================")
    print(f"Local user: {scope['app_username']}")
    print(f"OSRS/RuneLite account: {scope['osrs_account_name']}")
    print()

    keys = [
        "ai_source_row_limit",
        "ai_quick_choices",
        "ai_overnight_choices",
        "ai_value_choices",
        "exclude_items_traded_today",
        "min_overnight_raw_margin",
        "min_overnight_roi_percent",
        "max_small_loss_percent",
        "max_medium_loss_percent"
    ]

    saved = {}

    for key in keys:
        meta = DEFAULT_SETTINGS[key]
        current = get_setting(key, app_username=app_username, osrs_account_name=osrs_account_name)

        if meta["type"] == "bool":
            value = prompt_bool(meta["description"], current)
        else:
            value = prompt_value(meta["description"], current, meta["type"])

        set_setting(
            key=key,
            value=value,
            value_type=meta["type"],
            description=meta.get("description"),
            app_username=app_username,
            osrs_account_name=osrs_account_name
        )
        saved[key] = value

    print()
    print("AI settings saved.")
    return saved


def print_settings(app_username=None, osrs_account_name=None):
    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)
    settings = get_all_settings(app_username=app_username, osrs_account_name=osrs_account_name)

    print("\n==============================")
    print(" OSRSFlipper Settings")
    print("==============================")
    print(f"Local user: {scope['app_username']}")
    print(f"OSRS/RuneLite account: {scope['osrs_account_name']}")
    print()

    for key in sorted(settings):
        item = settings[key]
        print(f"{key}: {item['value']} ({item['source']})")


def export_settings(file_path, app_username=None, osrs_account_name=None):
    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)
    settings = get_all_settings(app_username=app_username, osrs_account_name=osrs_account_name)

    payload = {
        "app_username": scope["app_username"],
        "osrs_account_name": scope["osrs_account_name"],
        "exported_at": now_utc(),
        "settings": {
            key: value["value"]
            for key, value in settings.items()
        }
    }

    path = Path(file_path)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return path


def main():
    parser = argparse.ArgumentParser(
        description="OSRSFlipper account-scoped settings manager."
    )

    parser.add_argument("--user", default=None)
    parser.add_argument("--account", default=None)

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")
    subparsers.add_parser("list")
    subparsers.add_parser("configure")
    subparsers.add_parser("configure-ai")

    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("key")

    set_parser = subparsers.add_parser("set")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    set_parser.add_argument("--type", default=None, choices=["str", "int", "float", "bool", "json"])

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("file", nargs="?", default="osrsflipper_settings_export.json")

    args = parser.parse_args()

    if args.command == "init":
        init_settings_db()
        ensure_default_settings(args.user, args.account)
        print("Settings database initialized.")
        return

    if args.command == "list":
        print_settings(args.user, args.account)
        return

    if args.command == "configure":
        ensure_default_settings(args.user, args.account)
        configure_core_settings(args.user, args.account)
        return

    if args.command == "configure-ai":
        ensure_default_settings(args.user, args.account)
        configure_ai_settings(args.user, args.account)
        return

    if args.command == "get":
        print(get_setting(args.key, app_username=args.user, osrs_account_name=args.account))
        return

    if args.command == "set":
        value_type = args.type

        if value_type is None and args.key in DEFAULT_SETTINGS:
            value_type = DEFAULT_SETTINGS[args.key]["type"]

        if value_type is None:
            value_type = "str"

        value = parse_input_value(args.value, value_type)

        set_setting(
            key=args.key,
            value=value,
            value_type=value_type,
            app_username=args.user,
            osrs_account_name=args.account
        )

        print(f"Saved {args.key} = {value}")
        return

    if args.command == "export":
        path = export_settings(args.file, args.user, args.account)
        print(f"Exported settings to: {path}")
        return


if __name__ == "__main__":
    main()
