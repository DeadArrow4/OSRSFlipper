import argparse
import os
import sqlite3
import traceback
from datetime import datetime, timezone
from pathlib import Path

from account_context import BASE_DIR


DB_FILE = BASE_DIR / "osrs_flip_scanner.db"
LOG_DIR = BASE_DIR / "logs"
BACKUP_DIR = BASE_DIR / "backups"
EXPORT_DIR = BASE_DIR / "exports"


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    return sqlite3.connect(DB_FILE)


def ensure_dirs():
    LOG_DIR.mkdir(exist_ok=True)
    BACKUP_DIR.mkdir(exist_ok=True)
    EXPORT_DIR.mkdir(exist_ok=True)


def table_exists(cursor, table_name):
    cursor.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,)
    )
    return cursor.fetchone() is not None


def column_exists(cursor, table_name, column_name):
    if not table_exists(cursor, table_name):
        return False

    cursor.execute(f"PRAGMA table_info({table_name})")
    return column_name in [row[1] for row in cursor.fetchall()]


def add_column_if_missing(cursor, table_name, column_name, definition):
    if not table_exists(cursor, table_name):
        return f"Skipped {table_name}.{column_name}; table does not exist."

    if column_exists(cursor, table_name, column_name):
        return f"{table_name}.{column_name} already exists."

    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
    return f"Added {table_name}.{column_name}."


def create_migration_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_id TEXT UNIQUE NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT,
            applied_at TEXT NOT NULL
        )
    """)


def migration_has_run(cursor, migration_id):
    cursor.execute(
        """
        SELECT status
        FROM app_schema_migrations
        WHERE migration_id = ?
        """,
        (migration_id,)
    )

    row = cursor.fetchone()

    return row is not None and row[0] == "success"


def record_migration(cursor, migration_id, description, status, message):
    cursor.execute(
        """
        INSERT INTO app_schema_migrations (
            migration_id,
            description,
            status,
            message,
            applied_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(migration_id)
        DO UPDATE SET
            status = excluded.status,
            message = excluded.message,
            applied_at = excluded.applied_at
        """,
        (
            migration_id,
            description,
            status,
            str(message or "")[:4000],
            now_utc()
        )
    )


def bootstrap_module_initializers():
    """
    Runs existing module init functions every time.
    These are expected to be idempotent and keep legacy tables alive.
    """
    results = []

    initializers = []

    try:
        from database import init_db
        initializers.append(("database.init_db", init_db))
    except Exception as error:
        results.append(("database.init_db", "warning", f"Not available: {error}"))

    try:
        from trade_tracker import init_trade_db
        initializers.append(("trade_tracker.init_trade_db", init_trade_db))
    except Exception as error:
        results.append(("trade_tracker.init_trade_db", "warning", f"Not available: {error}"))

    try:
        from trade_importer import init_import_db
        initializers.append(("trade_importer.init_import_db", init_import_db))
    except Exception as error:
        results.append(("trade_importer.init_import_db", "warning", f"Not available: {error}"))

    try:
        from account_manager import init_user_db
        initializers.append(("account_manager.init_user_db", init_user_db))
    except Exception as error:
        results.append(("account_manager.init_user_db", "warning", f"Not available: {error}"))

    try:
        from settings_manager import ensure_default_settings
        initializers.append(("settings_manager.ensure_default_settings", ensure_default_settings))
    except Exception as error:
        results.append(("settings_manager.ensure_default_settings", "warning", f"Not available: {error}"))

    try:
        from openai_key_manager import init_api_key_db
        initializers.append(("openai_key_manager.init_api_key_db", init_api_key_db))
    except Exception as error:
        results.append(("openai_key_manager.init_api_key_db", "warning", f"Not available: {error}"))

    try:
        from openai_usage_manager import init_ai_usage_db
        initializers.append(("openai_usage_manager.init_ai_usage_db", init_ai_usage_db))
    except Exception as error:
        results.append(("openai_usage_manager.init_ai_usage_db", "warning", f"Not available: {error}"))

    try:
        from omitted_items import init_omitted_items_db
        initializers.append(("omitted_items.init_omitted_items_db", init_omitted_items_db))
    except Exception as error:
        results.append(("omitted_items.init_omitted_items_db", "warning", f"Not available: {error}"))

    try:
        from offer_intents import init_offer_intents_db
        initializers.append(("offer_intents.init_offer_intents_db", init_offer_intents_db))
    except Exception as error:
        results.append(("offer_intents.init_offer_intents_db", "warning", f"Not available: {error}"))

    for name, func in initializers:
        try:
            func()
            results.append((name, "success", "OK"))
        except Exception as error:
            results.append((name, "error", str(error)))

    return results


def migration_001_core_scan_columns(cursor):
    messages = []

    scan_columns = {
        "daily_trend": "TEXT",
        "weekly_trend": "TEXT",
        "long_term_trend": "TEXT",
        "daily_change_percent": "REAL",
        "weekly_change_percent": "REAL",
        "long_term_change_percent": "REAL",
        "daily_volatility_percent": "REAL",
        "weekly_volatility_percent": "REAL",
        "seven_day_high": "INTEGER",
        "seven_day_low": "INTEGER",
        "price_position_7d_percent": "REAL",
        "trend_confidence": "TEXT",
        "trend_warning": "TEXT",
        "quick_score": "REAL",
        "overnight_score": "REAL"
    }

    for column_name, definition in scan_columns.items():
        messages.append(
            add_column_if_missing(cursor, "scan_results", column_name, definition)
        )

    return "\n".join(messages)


def migration_002_trade_account_columns(cursor):
    messages = []

    trade_columns = {
        "app_username": "TEXT NOT NULL DEFAULT 'default'",
        "osrs_account_name": "TEXT NOT NULL DEFAULT 'default'",
        "external_id": "TEXT",
        "source": "TEXT",
        "status": "TEXT",
        "raw_payload": "TEXT"
    }

    for column_name, definition in trade_columns.items():
        messages.append(
            add_column_if_missing(cursor, "trade_events", column_name, definition)
        )

    completed_columns = {
        "app_username": "TEXT NOT NULL DEFAULT 'default'",
        "osrs_account_name": "TEXT NOT NULL DEFAULT 'default'",
        "source": "TEXT",
        "notes": "TEXT"
    }

    for column_name, definition in completed_columns.items():
        messages.append(
            add_column_if_missing(cursor, "completed_trades", column_name, definition)
        )

    if table_exists(cursor, "trade_events"):
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_trade_events_account_item
            ON trade_events(app_username, osrs_account_name, item_id, item_name, side)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_trade_events_account_time
            ON trade_events(app_username, osrs_account_name, traded_at)
        """)

    if table_exists(cursor, "completed_trades"):
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_completed_trades_account_item
            ON completed_trades(app_username, osrs_account_name, item_id, item_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_completed_trades_account_time
            ON completed_trades(app_username, osrs_account_name, sell_time)
        """)

    return "\n".join(messages)


def migration_003_imported_files_account_columns(cursor):
    messages = []

    imported_columns = {
        "app_username": "TEXT NOT NULL DEFAULT 'default'",
        "osrs_account_name": "TEXT NOT NULL DEFAULT 'default'"
    }

    for column_name, definition in imported_columns.items():
        messages.append(
            add_column_if_missing(cursor, "imported_trade_files", column_name, definition)
        )

    if table_exists(cursor, "imported_trade_files"):
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_imported_trade_files_account
            ON imported_trade_files(app_username, osrs_account_name, file_path)
        """)

    return "\n".join(messages)


def migration_004_settings_and_ai_usage(cursor):
    messages = []

    # These tables are normally created by their modules; this migration gives
    # health check a stable schema even when modules were not initialized yet.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_username TEXT NOT NULL,
            osrs_account_name TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'openai',
            model TEXT,
            request_type TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            success INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_ai_usage_events_account_date
        ON ai_usage_events(app_username, osrs_account_name, created_at)
    """)

    messages.append("Ensured ai_usage_events table and index.")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_username TEXT NOT NULL,
            osrs_account_name TEXT NOT NULL,
            setting_key TEXT NOT NULL,
            setting_value TEXT,
            value_type TEXT NOT NULL DEFAULT 'str',
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(app_username, osrs_account_name, setting_key)
        )
    """)

    messages.append("Ensured app_settings table.")

    return "\n".join(messages)


def migration_005_ai_notes_account_columns(cursor):
    messages = []

    if table_exists(cursor, "ai_trade_notes"):
        messages.append(add_column_if_missing(cursor, "ai_trade_notes", "app_username", "TEXT NOT NULL DEFAULT 'default'"))
        messages.append(add_column_if_missing(cursor, "ai_trade_notes", "osrs_account_name", "TEXT NOT NULL DEFAULT 'default'"))

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_trade_notes_account
            ON ai_trade_notes(app_username, osrs_account_name, created_at)
        """)
    else:
        messages.append("Skipped ai_trade_notes account migration; table does not exist yet.")

    return "\n".join(messages)


MIGRATIONS = [
    ("001_core_scan_columns", "Ensure scanner trend/score columns exist.", migration_001_core_scan_columns),
    ("002_trade_account_columns", "Ensure trade tables are account-scoped.", migration_002_trade_account_columns),
    ("003_imported_files_account_columns", "Ensure import log table is account-scoped.", migration_003_imported_files_account_columns),
    ("004_settings_and_ai_usage", "Ensure settings and AI usage tables exist.", migration_004_settings_and_ai_usage),
    ("005_ai_notes_account_columns", "Ensure AI note table is account-scoped if present.", migration_005_ai_notes_account_columns),
]


def run_app_migrations(force=False, write_report=True):
    ensure_dirs()

    bootstrap_results = bootstrap_module_initializers()

    conn = get_connection()
    cursor = conn.cursor()

    create_migration_table(cursor)
    conn.commit()

    migration_results = []

    for migration_id, description, func in MIGRATIONS:
        if migration_has_run(cursor, migration_id) and not force:
            migration_results.append({
                "migration_id": migration_id,
                "description": description,
                "status": "skipped",
                "message": "Already applied."
            })
            continue

        try:
            message = func(cursor)
            record_migration(cursor, migration_id, description, "success", message)
            conn.commit()

            migration_results.append({
                "migration_id": migration_id,
                "description": description,
                "status": "success",
                "message": message
            })

        except Exception as error:
            conn.rollback()
            message = f"{error}\n{traceback.format_exc()}"
            record_migration(cursor, migration_id, description, "error", message)
            conn.commit()

            migration_results.append({
                "migration_id": migration_id,
                "description": description,
                "status": "error",
                "message": str(error)
            })

    conn.close()

    report = build_migration_report(bootstrap_results, migration_results)

    if write_report:
        report_path = LOG_DIR / "migration_report.txt"
        report_path.write_text(report, encoding="utf-8")

    return {
        "bootstrap_results": bootstrap_results,
        "migration_results": migration_results,
        "report": report,
        "report_path": str(LOG_DIR / "migration_report.txt")
    }


def build_migration_report(bootstrap_results, migration_results):
    lines = []
    lines.append("OSRSFLIPPER DATABASE MIGRATION REPORT")
    lines.append("=====================================")
    lines.append(f"Generated: {now_utc()}")
    lines.append(f"Database: {DB_FILE}")
    lines.append("")

    lines.append("BOOTSTRAP INITIALIZERS")
    lines.append("----------------------")

    for name, status, message in bootstrap_results:
        lines.append(f"[{status.upper()}] {name}: {message}")

    lines.append("")
    lines.append("MIGRATIONS")
    lines.append("----------")

    for result in migration_results:
        lines.append(f"[{result['status'].upper()}] {result['migration_id']} - {result['description']}")
        message = str(result.get("message") or "").strip()

        if message:
            for line in message.splitlines():
                lines.append(f"    {line}")

    lines.append("")
    lines.append("END OF REPORT")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Run OSRSFlipper database migrations and repair checks."
    )

    parser.add_argument("--force", action="store_true", help="Re-run migrations even if marked as applied.")
    parser.add_argument("--no-write", action="store_true", help="Do not write migration_report.txt.")

    args = parser.parse_args()

    result = run_app_migrations(
        force=args.force,
        write_report=not args.no_write
    )

    print(result["report"])

    if not args.no_write:
        print()
        print(f"Report saved to: {result['report_path']}")


if __name__ == "__main__":
    main()
