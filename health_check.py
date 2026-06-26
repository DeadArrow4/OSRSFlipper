import argparse
import importlib
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from security_runtime import scrub_shared_openai_env, scrub_status_text, dotenv_contains_openai_api_key, get_non_secret_env_value

try:
    from account_context import get_account_scope
except Exception:
    def get_account_scope():
        return {
            "app_username": os.getenv("OSRSFLIPPER_USERNAME", "default"),
            "osrs_account_name": os.getenv("RUNELITE_ACCOUNT", "default")
        }


# Health checks should inspect the real installed project folder, not a test
# install folder, current working directory, or environment override.
NORMAL_PROJECT_DIR = Path(r"C:\OSRSFlipper")

if NORMAL_PROJECT_DIR.exists():
    BASE_DIR = NORMAL_PROJECT_DIR.resolve()
else:
    BASE_DIR = Path(__file__).resolve().parent


DB_FILE = BASE_DIR / "osrs_flip_scanner.db"
LOG_DIR = BASE_DIR / "logs"
ASSETS_DIR = BASE_DIR / "assets"
RUNTIME_DIR = BASE_DIR / ".osrs_runtime"
REPORT_FILE = LOG_DIR / "health_check.txt"

scrub_shared_openai_env()


REQUIRED_PROJECT_FILES = [
    "api.py",
    "scanner.py",
    "main.py",
    "collector.py",
    "database.py",
    "recommender.py",
    "advisor.py",
    "dashboard.py",
    "dashboard_callbacks/__init__.py",
    "dashboard_tabs/__init__.py",
    "dashboard_components.py",
    "dashboard_data.py",
    "dashboard_formatters.py",
    "dashboard_theme.py",
    "trend_analyzer.py",
    "trade_tracker.py",
    "trade_importer.py",
    "trade_ai_context.py",
    "account_context.py",
    "account_manager.py",
    "settings_manager.py",
    "osrs_control_center.py"
]

REQUIRED_PACKAGES = [
    "dash",
    "plotly",
    "pandas",
    "requests",
    "openai",
    "dotenv"
]

CORE_TABLES = [
    "scan_results",
    "scan_runs",
    "trade_events",
    "completed_trades",
    "app_users",
    "app_settings",
    "ai_trade_notes",
    "imported_trade_files",
    "ai_usage_events",
    "app_schema_migrations"
]

TRADE_EVENTS_ACCOUNT_COLUMNS = [
    "app_username",
    "osrs_account_name",
    "item_name",
    "side",
    "price_each",
    "quantity",
    "remaining_quantity",
    "traded_at",
    "imported_at"
]

COMPLETED_TRADES_ACCOUNT_COLUMNS = [
    "app_username",
    "osrs_account_name",
    "item_name",
    "quantity",
    "buy_price_each",
    "sell_price_each",
    "total_profit",
    "roi_percent"
]

SCAN_RESULT_IMPORTANT_COLUMNS = [
    "quick_score",
    "overnight_score",
    "daily_trend",
    "weekly_trend",
    "trend_warning"
]


def now_text():
    return datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")


def ok_line(message):
    return f"[OK] {message}"


def warn_line(message):
    return f"[WARN] {message}"


def fail_line(message):
    return f"[FAIL] {message}"


def info_line(message):
    return f"[INFO] {message}"


def file_mtime(path):
    try:
        path = Path(path)

        if not path.exists():
            return "not found"

        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %I:%M:%S %p")
    except Exception:
        return "unknown"


def read_env_file():
    env_path = BASE_DIR / ".env"

    if not env_path.exists():
        return {}

    values = {}

    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    except Exception:
        return {}

    return values


def get_db_connection():
    if not DB_FILE.exists():
        return None

    return sqlite3.connect(DB_FILE)


def get_tables(cursor):
    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        ORDER BY name
    """)

    return [row[0] for row in cursor.fetchall()]


def get_columns(cursor, table):
    cursor.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


def get_scalar(cursor, query, params=(), default=None):
    try:
        cursor.execute(query, params)
        row = cursor.fetchone()

        if row is None:
            return default

        return row[0]
    except Exception:
        return default


def check_project_files(lines):
    lines.append("")
    lines.append("PROJECT FILES")
    lines.append("-------------")

    for file_name in REQUIRED_PROJECT_FILES:
        path = BASE_DIR / file_name

        if path.exists():
            lines.append(ok_line(f"{file_name} found"))
        else:
            lines.append(fail_line(f"{file_name} missing"))

    style_path = ASSETS_DIR / "style.css"

    if style_path.exists():
        lines.append(ok_line("assets/style.css found"))
    else:
        lines.append(warn_line("assets/style.css missing or assets folder missing"))


def check_python_environment(lines):
    lines.append("")
    lines.append("PYTHON / PACKAGE CHECK")
    lines.append("----------------------")
    lines.append(info_line(f"Running Python executable: {sys.executable}"))
    lines.append(info_line(f"Python version: {sys.version.split()[0]}"))

    venv_python = BASE_DIR / ".venv" / "Scripts" / "python.exe"

    if venv_python.exists():
        lines.append(ok_line(f"Project venv Python found: {venv_python}"))
    else:
        lines.append(warn_line(f"Project venv Python not found: {venv_python}"))

    for package in REQUIRED_PACKAGES:
        try:
            module = importlib.import_module(package)
            version = getattr(module, "__version__", "installed")
            lines.append(ok_line(f"{package} import OK ({version})"))
        except Exception as error:
            lines.append(fail_line(f"{package} import failed: {error}"))


def check_env(lines):
    lines.append("")
    lines.append("ENVIRONMENT / OPENAI")
    lines.append("--------------------")

    env_path = BASE_DIR / ".env"

    if env_path.exists():
        lines.append(ok_line(f".env found: {env_path}"))
    else:
        lines.append(warn_line(f".env file not found at expected path: {env_path}"))

    if dotenv_contains_openai_api_key(env_path):
        lines.append(warn_line("Shared OPENAI_API_KEY still exists inside .env. Remove it before sharing the app."))
    else:
        lines.append(ok_line("No OPENAI_API_KEY assignment found inside .env"))

    # The health check scrubs any stale process-level key before reporting.
    lines.append(ok_line(scrub_status_text()))

    model = get_non_secret_env_value("OPENAI_MODEL", None)

    if model:
        lines.append(ok_line(f"OPENAI_MODEL set to {model}"))
    else:
        lines.append(warn_line("OPENAI_MODEL not set; advisor.py may use its default"))


def check_account(lines):
    lines.append("")
    lines.append("ACCOUNT / SESSION")
    lines.append("-----------------")

    scope = get_account_scope()

    lines.append(info_line(f"Current local user: {scope.get('app_username')}"))
    lines.append(info_line(f"Current OSRS/RuneLite account: {scope.get('osrs_account_name')}"))

    session_file = RUNTIME_DIR / "current_user.json"

    if session_file.exists():
        lines.append(ok_line(f"Session file found: {session_file}"))

        try:
            payload = json.loads(session_file.read_text(encoding="utf-8"))
            lines.append(info_line(f"Session user: {payload.get('username')}"))
            lines.append(info_line(f"Session OSRS account: {payload.get('osrs_account_name')}"))
        except Exception as error:
            lines.append(warn_line(f"Could not read session file: {error}"))
    else:
        lines.append(warn_line(f"Session file not found: {session_file}"))


def check_runelite(lines):
    lines.append("")
    lines.append("RUNELITE / FLIPPING UTILITIES")
    lines.append("-----------------------------")

    scope = get_account_scope()
    account = scope.get("osrs_account_name")
    flipping_dir = Path.home() / ".runelite" / "flipping"
    runelite_file = flipping_dir / f"{account}.json"

    if flipping_dir.exists():
        lines.append(ok_line(f"RuneLite flipping folder found: {flipping_dir}"))
    else:
        lines.append(warn_line(f"RuneLite flipping folder not found: {flipping_dir}"))

    if runelite_file.exists():
        lines.append(ok_line(f"RuneLite account JSON found: {runelite_file}"))
        lines.append(info_line(f"RuneLite JSON modified: {file_mtime(runelite_file)}"))

        try:
            data = json.loads(runelite_file.read_text(encoding="utf-8-sig"))

            trades = data.get("trades", [])
            last_offers = data.get("lastOffers", {})

            lines.append(info_line(f"Flipping Utilities trade item entries: {len(trades) if isinstance(trades, list) else 'unknown'}"))
            lines.append(info_line(f"Last offers entries: {len(last_offers) if isinstance(last_offers, dict) else 'unknown'}"))

            active_slots = 0

            if isinstance(last_offers, dict):
                for offer in last_offers.values():
                    if isinstance(offer, dict) and str(offer.get("st", "")).upper() in ("BUYING", "SELLING"):
                        active_slots += 1

            lines.append(info_line(f"Active live GE slots from lastOffers: {active_slots}"))

        except Exception as error:
            lines.append(warn_line(f"Could not parse RuneLite JSON: {error}"))
    else:
        lines.append(warn_line(f"RuneLite account JSON not found: {runelite_file}"))


def check_database(lines):
    lines.append("")
    lines.append("DATABASE")
    lines.append("--------")

    if not DB_FILE.exists():
        lines.append(fail_line(f"Database not found: {DB_FILE}"))
        return

    lines.append(ok_line(f"Database found: {DB_FILE}"))
    lines.append(info_line(f"Database modified: {file_mtime(DB_FILE)}"))
    lines.append(info_line(f"Database size: {DB_FILE.stat().st_size:,} bytes"))

    conn = get_db_connection()

    if conn is None:
        lines.append(fail_line("Could not connect to database"))
        return

    cursor = conn.cursor()

    try:
        tables = get_tables(cursor)

        for table in CORE_TABLES:
            if table in tables:
                lines.append(ok_line(f"Table found: {table}"))
            else:
                lines.append(warn_line(f"Table missing: {table}"))

        if "trade_events" in tables:
            columns = get_columns(cursor, "trade_events")

            for column in TRADE_EVENTS_ACCOUNT_COLUMNS:
                if column not in columns:
                    lines.append(fail_line(f"trade_events missing column: {column}"))

        if "completed_trades" in tables:
            columns = get_columns(cursor, "completed_trades")

            for column in COMPLETED_TRADES_ACCOUNT_COLUMNS:
                if column not in columns:
                    lines.append(fail_line(f"completed_trades missing column: {column}"))

        if "scan_results" in tables:
            columns = get_columns(cursor, "scan_results")

            for column in SCAN_RESULT_IMPORTANT_COLUMNS:
                if column in columns:
                    lines.append(ok_line(f"scan_results column found: {column}"))
                else:
                    lines.append(warn_line(f"scan_results missing trend column: {column}"))

            latest_scan = get_scalar(cursor, "SELECT MAX(scanned_at) FROM scan_results")
            latest_run_id = get_scalar(cursor, "SELECT MAX(run_id) FROM scan_results")
            lines.append(info_line(f"Latest scan run ID: {latest_run_id}"))
            lines.append(info_line(f"Latest scan time: {latest_scan}"))

        scope = get_account_scope()

        if "trade_events" in tables:
            trade_events = get_scalar(
                cursor,
                """
                SELECT COUNT(*)
                FROM trade_events
                WHERE app_username = ?
                  AND osrs_account_name = ?
                """,
                (
                    scope["app_username"],
                    scope["osrs_account_name"]
                ),
                default=0
            )
            lines.append(info_line(f"Current account trade_events rows: {trade_events}"))

        if "completed_trades" in tables:
            completed = get_scalar(
                cursor,
                """
                SELECT COUNT(*)
                FROM completed_trades
                WHERE app_username = ?
                  AND osrs_account_name = ?
                """,
                (
                    scope["app_username"],
                    scope["osrs_account_name"]
                ),
                default=0
            )

            profit = get_scalar(
                cursor,
                """
                SELECT COALESCE(SUM(total_profit), 0)
                FROM completed_trades
                WHERE app_username = ?
                  AND osrs_account_name = ?
                """,
                (
                    scope["app_username"],
                    scope["osrs_account_name"]
                ),
                default=0
            )

            lines.append(info_line(f"Current account completed_trades rows: {completed}"))
            lines.append(info_line(f"Current account realized P/L: {int(profit or 0):,} gp"))

    finally:
        conn.close()


def check_logs_and_exe(lines):
    lines.append("")
    lines.append("LOGS / EXE")
    lines.append("----------")

    if LOG_DIR.exists():
        lines.append(ok_line(f"Logs folder found: {LOG_DIR}"))
    else:
        lines.append(warn_line(f"Logs folder not found: {LOG_DIR}"))

    for name in [
        "dashboard.log",
        "dashboard_error.log",
        "collector.log",
        "collector_error.log",
        "trade_watcher.log",
        "trade_watcher_error.log"
    ]:
        path = LOG_DIR / name

        if path.exists():
            lines.append(info_line(f"{name}: {path.stat().st_size:,} bytes, modified {file_mtime(path)}"))

    exe_path = BASE_DIR / "dist" / "OSRSFlipper.exe"

    if exe_path.exists():
        lines.append(ok_line(f"EXE found: {exe_path}"))
        lines.append(info_line(f"EXE modified: {file_mtime(exe_path)}"))
    else:
        lines.append(warn_line(f"EXE not found yet: {exe_path}"))


def run_health_check(write_report=True):
    LOG_DIR.mkdir(exist_ok=True)

    lines = []
    lines.append("OSRSFLIPPER HEALTH CHECK")
    lines.append("========================")
    lines.append(f"Generated: {now_text()}")
    lines.append(f"Project folder: {BASE_DIR}")

    check_project_files(lines)
    check_python_environment(lines)
    check_env(lines)
    check_account(lines)
    check_runelite(lines)
    check_database(lines)
    check_logs_and_exe(lines)

    lines.append("")
    lines.append("END OF HEALTH CHECK")

    text = "\n".join(lines)

    if write_report:
        REPORT_FILE.write_text(text, encoding="utf-8")

    return text


def main():
    parser = argparse.ArgumentParser(
        description="Run OSRSFlipper diagnostics."
    )

    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--output", default=None)

    args = parser.parse_args()

    text = run_health_check(write_report=not args.no_write)

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")

    print(text)

    if not args.no_write:
        print()
        print(f"Report saved to: {REPORT_FILE}")


if __name__ == "__main__":
    main()
