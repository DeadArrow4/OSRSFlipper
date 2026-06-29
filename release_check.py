import argparse
import importlib
import json
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

try:
    from account_context import BASE_DIR, get_account_scope
except Exception:
    BASE_DIR = Path(__file__).resolve().parent

    def get_account_scope():
        return {
            "app_username": os.getenv("OSRSFLIPPER_USERNAME", "default"),
            "osrs_account_name": os.getenv("RUNELITE_ACCOUNT", "default")
        }


LOG_DIR = BASE_DIR / "logs"
DB_FILE = BASE_DIR / "osrs_flip_scanner.db"
REPORT_FILE = LOG_DIR / "release_check.txt"


REQUIRED_FILES = [
    "account_context.py",
    "account_manager.py",
    "app_version.py",
    "prepare_release.py",
    "backup_manager.py",
    "ai_capital_advisor_context.py",
    "advisor.py",
    "api.py",
    "capital_ai_memory.py",
    "capital_budget.py",
    "capital_dashboard.py",
    "capital_trade_board.py",
    "collector.py",
    "dashboard.py",
    "dashboard_callbacks/__init__.py",
    "dashboard_tabs/__init__.py",
    "dashboard_tabs/admin.py",
    "dashboard_tabs/admin_about.py",
    "dashboard_tabs/admin_account.py",
    "dashboard_tabs/admin_data_health.py",
    "dashboard_tabs/admin_maintenance.py",
    "dashboard_tabs/admin_safety.py",
    "dashboard_tabs/admin_settings.py",
    "dashboard_tabs/admin_setup.py",
    "dashboard_tabs/admin_status.py",
    "dashboard_tabs/ai.py",
    "dashboard_tabs/app_layout.py",
    "dashboard_tabs/market.py",
    "dashboard_tabs/overview.py",
    "dashboard_tabs/trade_board.py",
    "dashboard_tabs/trades.py",
    "dashboard_control_commands.py",
    "dashboard_components.py",
    "dashboard_data.py",
    "dashboard_formatters.py",
    "dashboard_theme.py",
    "data_health.py",
    "data_health_modules/__init__.py",
    "data_health_modules/automation.py",
    "data_health_modules/backups.py",
    "data_health_modules/common.py",
    "data_health_modules/compaction.py",
    "data_health_modules/maintenance.py",
    "data_health_modules/metrics.py",
    "data_health_modules/retention.py",
    "data_health_modules/schema.py",
    "data_health_modules/snapshots.py",
    "data_health_modules/trends.py",
    "database.py",
    "first_run_setup.py",
    "health_check.py",
    "main.py",
    "market_features.py",
    "migration_manager.py",
    "openai_key_manager.py",
    "openai_key_tester.py",
    "openai_usage_manager.py",
    "osrs_launcher.py",
    "osrs_control_center.py",
    "recommender.py",
    "report.py",
    "runelite_plugin_packager.py",
    "runelite_paths.py",
    "runelite_state_importer.py",
    "runelite_telemetry_control.py",
    "safety_manager.py",
    "scanner.py",
    "security_runtime.py",
    "settings_manager.py",
    "trade_ai_context.py",
    "trade_importer.py",
    "trade_tracker.py",
    "trade_trends.py",
    "update_install.py",
    "trend_analyzer.py",
    "runtime/runelite_state.example.json",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "build_exe.bat"
]

OPTIONAL_FILES = [
    "assets/style.css",
    "remove_shared_openai_key.py",
    "remove_shared_openai_key.bat",
    "create_desktop_shortcut.bat",
    "build_and_create_shortcut.bat"
]

IMPORT_MODULES = [
    "account_context",
    "account_manager",
    "ai_capital_advisor_context",
    "app_version",
    "prepare_release",
    "backup_manager",
    "api",
    "capital_ai_memory",
    "capital_budget",
    "capital_dashboard",
    "capital_trade_board",
    "database",
    "dashboard_callbacks",
    "dashboard_tabs",
    "dashboard_tabs.admin",
    "dashboard_tabs.admin_about",
    "dashboard_tabs.admin_account",
    "dashboard_tabs.admin_data_health",
    "dashboard_tabs.admin_maintenance",
    "dashboard_tabs.admin_safety",
    "dashboard_tabs.admin_settings",
    "dashboard_tabs.admin_setup",
    "dashboard_tabs.admin_status",
    "dashboard_tabs.ai",
    "dashboard_tabs.app_layout",
    "dashboard_tabs.market",
    "dashboard_tabs.overview",
    "dashboard_tabs.trade_board",
    "dashboard_tabs.trades",
    "dashboard_control_commands",
    "dashboard_components",
    "dashboard_data",
    "dashboard_formatters",
    "dashboard_theme",
    "data_health",
    "data_health_modules",
    "data_health_modules.automation",
    "data_health_modules.backups",
    "data_health_modules.common",
    "data_health_modules.compaction",
    "data_health_modules.maintenance",
    "data_health_modules.metrics",
    "data_health_modules.retention",
    "data_health_modules.schema",
    "data_health_modules.snapshots",
    "data_health_modules.trends",
    "migration_manager",
    "market_features",
    "openai_key_manager",
    "openai_key_tester",
    "openai_usage_manager",
    "report",
    "runelite_plugin_packager",
    "runelite_paths",
    "runelite_state_importer",
    "runelite_telemetry_control",
    "safety_manager",
    "security_runtime",
    "settings_manager",
    "trade_importer",
    "trade_tracker",
    "trade_trends",
    "trend_analyzer",
    "update_install"
]

HEAVY_IMPORT_MODULES = [
    "advisor",
    "dashboard",
    "osrs_control_center"
]

REQUIRED_TABLES = [
    "app_users",
    "app_settings",
    "account_api_keys",
    "ai_usage_events",
    "app_schema_migrations",
    "scan_results",
    "market_price_snapshots",
    "trade_events",
    "completed_trades",
    "imported_trade_files"
]

REQUIRED_TRADE_EVENT_COLUMNS = [
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

REQUIRED_COMPLETED_TRADE_COLUMNS = [
    "app_username",
    "osrs_account_name",
    "item_name",
    "quantity",
    "buy_price_each",
    "sell_price_each",
    "total_profit",
    "roi_percent"
]

REQUIRED_SCAN_COLUMNS = [
    "quick_score",
    "overnight_score",
    "daily_trend",
    "weekly_trend",
    "trend_warning",
    "avg_low_24h",
    "volume_24h",
    "market_momentum",
    "market_context_warning"
]


class ReleaseChecker:
    def __init__(self, strict=False):
        self.strict = strict
        self.rows = []
        self.started_at = datetime.now(timezone.utc).isoformat()

    def add(self, status, check, message):
        self.rows.append({
            "status": status.upper(),
            "check": check,
            "message": str(message)
        })

    def pass_(self, check, message="OK"):
        self.add("PASS", check, message)

    def warn(self, check, message):
        self.add("WARN", check, message)

    def fail(self, check, message):
        self.add("FAIL", check, message)

    def info(self, check, message):
        self.add("INFO", check, message)

    def has_failures(self):
        return any(row["status"] == "FAIL" for row in self.rows)

    def has_warnings(self):
        return any(row["status"] == "WARN" for row in self.rows)

    def status_counts(self):
        counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "INFO": 0}

        for row in self.rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1

        return counts

    def final_status(self):
        if self.has_failures():
            return "FAIL"

        if self.strict and self.has_warnings():
            return "FAIL"

        if self.has_warnings():
            return "WARN"

        return "PASS"

    def build_report(self):
        counts = self.status_counts()
        final = self.final_status()

        lines = []
        lines.append("OSRSFLIPPER RELEASE CHECK")
        lines.append("=========================")
        lines.append(f"Generated: {self.started_at}")
        lines.append(f"Project folder: {BASE_DIR}")
        lines.append(f"Database: {DB_FILE}")
        lines.append(f"Final status: {final}")
        lines.append(f"Counts: PASS={counts.get('PASS', 0)} WARN={counts.get('WARN', 0)} FAIL={counts.get('FAIL', 0)} INFO={counts.get('INFO', 0)}")
        lines.append("")

        current_section = None

        for row in self.rows:
            check = row["check"]
            section = check.split(":", 1)[0] if ":" in check else "General"

            if section != current_section:
                current_section = section
                lines.append("")
                lines.append(section.upper())
                lines.append("-" * len(section))

            lines.append(f"[{row['status']}] {row['check']}: {row['message']}")

        lines.append("")
        lines.append("END OF RELEASE CHECK")

        return "\n".join(lines)

    def write_report(self):
        LOG_DIR.mkdir(exist_ok=True)
        report = self.build_report()
        REPORT_FILE.write_text(report, encoding="utf-8")
        return REPORT_FILE


def get_connection():
    return sqlite3.connect(DB_FILE)


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


def get_columns(cursor, table_name):
    if not table_exists(cursor, table_name):
        return []

    cursor.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cursor.fetchall()]


def safe_import(module_name):
    try:
        importlib.import_module(module_name)
        return True, "import OK"
    except Exception as error:
        return False, f"{error}\n{traceback.format_exc(limit=3)}"


def check_required_files(checker):
    for file_name in REQUIRED_FILES:
        path = BASE_DIR / file_name

        if path.exists():
            checker.pass_(f"Files:{file_name}", "found")
        else:
            checker.fail(f"Files:{file_name}", "missing")

    for file_name in OPTIONAL_FILES:
        path = BASE_DIR / file_name

        if path.exists():
            checker.pass_(f"Optional files:{file_name}", "found")
        else:
            checker.warn(f"Optional files:{file_name}", "not found")


def check_python_environment(checker):
    checker.info("Python:executable", sys.executable)
    checker.info("Python:version", sys.version.replace("\n", " "))

    venv_python = BASE_DIR / ".venv" / "Scripts" / "python.exe"

    if venv_python.exists():
        checker.pass_("Python:venv", str(venv_python))
    else:
        checker.warn("Python:venv", f"not found at {venv_python}")

    try:
        import pandas
        checker.pass_("Package:pandas", getattr(pandas, "__version__", "installed"))
    except Exception as error:
        checker.fail("Package:pandas", error)

    try:
        import dash
        checker.pass_("Package:dash", getattr(dash, "__version__", "installed"))
    except Exception as error:
        checker.fail("Package:dash", error)

    try:
        import plotly
        checker.pass_("Package:plotly", getattr(plotly, "__version__", "installed"))
    except Exception as error:
        checker.fail("Package:plotly", error)

    try:
        import requests
        checker.pass_("Package:requests", getattr(requests, "__version__", "installed"))
    except Exception as error:
        checker.fail("Package:requests", error)

    try:
        import openai
        checker.pass_("Package:openai", getattr(openai, "__version__", "installed"))
    except Exception as error:
        checker.fail("Package:openai", error)


def check_module_imports(checker):
    for module_name in IMPORT_MODULES:
        ok, message = safe_import(module_name)

        if ok:
            checker.pass_(f"Import:{module_name}", message)
        else:
            checker.fail(f"Import:{module_name}", message)

    for module_name in HEAVY_IMPORT_MODULES:
        ok, message = safe_import(module_name)

        if ok:
            checker.pass_(f"Heavy import:{module_name}", message)
        else:
            checker.fail(f"Heavy import:{module_name}", message)


def check_shared_key_safety(checker):
    try:
        from security_runtime import dotenv_contains_openai_api_key, scrub_shared_openai_env, scrub_status_text

        scrub_shared_openai_env()

        if dotenv_contains_openai_api_key(BASE_DIR / ".env"):
            checker.fail("Security:shared OPENAI_API_KEY", ".env still contains OPENAI_API_KEY")
        else:
            checker.pass_("Security:shared OPENAI_API_KEY", "not found in .env")

        if os.getenv("OPENAI_API_KEY"):
            checker.fail("Security:process OPENAI_API_KEY", "still present in current process")
        else:
            checker.pass_("Security:process OPENAI_API_KEY", scrub_status_text())

    except Exception as error:
        checker.fail("Security:shared key check", error)


def check_database_and_migrations(checker):
    if not DB_FILE.exists():
        checker.warn("Database:file", f"not found yet: {DB_FILE}")
    else:
        checker.pass_("Database:file", f"{DB_FILE} ({DB_FILE.stat().st_size:,} bytes)")

    try:
        from migration_manager import run_app_migrations

        result = run_app_migrations(write_report=True)
        checker.pass_("Database:migrations", f"completed; report {result.get('report_path')}")

    except Exception as error:
        checker.fail("Database:migrations", error)
        return

    if not DB_FILE.exists():
        checker.fail("Database:post-migration file", "database still missing after migrations")
        return

    conn = get_connection()
    cursor = conn.cursor()

    try:
        for table in REQUIRED_TABLES:
            if table_exists(cursor, table):
                checker.pass_(f"Database table:{table}", "found")
            else:
                checker.warn(f"Database table:{table}", "missing")

        for column in REQUIRED_TRADE_EVENT_COLUMNS:
            if column in get_columns(cursor, "trade_events"):
                checker.pass_(f"trade_events column:{column}", "found")
            else:
                checker.fail(f"trade_events column:{column}", "missing")

        for column in REQUIRED_COMPLETED_TRADE_COLUMNS:
            if column in get_columns(cursor, "completed_trades"):
                checker.pass_(f"completed_trades column:{column}", "found")
            else:
                checker.fail(f"completed_trades column:{column}", "missing")

        for column in REQUIRED_SCAN_COLUMNS:
            if column in get_columns(cursor, "scan_results"):
                checker.pass_(f"scan_results column:{column}", "found")
            else:
                checker.warn(f"scan_results column:{column}", "missing; scanner migration may need current database.py")

        cursor.execute("SELECT COUNT(*) FROM app_schema_migrations")
        migration_count = cursor.fetchone()[0]
        checker.pass_("Database:migration records", f"{migration_count} records")

    finally:
        conn.close()


def check_account_and_key(checker):
    try:
        from account_manager import get_current_session, list_users
        from openai_key_manager import get_api_key_status
        from openai_usage_manager import get_ai_usage_summary

        users = list_users()

        if users:
            checker.pass_("Account:users", f"{len(users)} local user(s)")
        else:
            checker.warn("Account:users", "no local users yet; first-run setup required")

        session = get_current_session()

        if session:
            checker.pass_("Account:session", f"{session.get('username')} / {session.get('osrs_account_name')}")
        else:
            checker.warn("Account:session", "no active session")

        scope = get_account_scope()
        checker.info("Account:scope", f"{scope.get('app_username')} / {scope.get('osrs_account_name')}")

        key_status = get_api_key_status()

        if key_status.get("has_key"):
            checker.pass_("OpenAI:key", f"encrypted key saved: {key_status.get('key_hint')}")
        else:
            checker.warn("OpenAI:key", "no encrypted key saved for current account")

        usage = get_ai_usage_summary()
        checker.pass_("OpenAI:usage table", f"today {usage['today'].get('total_requests', 0)}/{usage.get('daily_limit')} requests")

    except Exception as error:
        checker.fail("Account/OpenAI:check", error)


def check_runelite(checker):
    try:
        from first_run_setup import locate_runelite_file

        scope = get_account_scope()
        account = scope.get("osrs_account_name")
        runelite_file = locate_runelite_file(account)

        if runelite_file.exists():
            checker.pass_("RuneLite:telemetry file", str(runelite_file))

            try:
                payload = json.loads(runelite_file.read_text(encoding="utf-8-sig"))
                source = payload.get("source", "unknown") if isinstance(payload, dict) else "unknown"
                payload_kind = payload.get("payload_kind", "unknown") if isinstance(payload, dict) else "unknown"
                checker.pass_("RuneLite:telemetry parse", f"source={source}, payload={payload_kind}")
            except Exception as error:
                checker.warn("RuneLite:telemetry parse", error)
        else:
            checker.warn("RuneLite:telemetry file", f"not found yet: {runelite_file}")

    except Exception as error:
        checker.warn("RuneLite:check", error)


def check_tools_run(checker):
    try:
        from safety_manager import build_safety_review

        df = build_safety_review(limit=10)

        if df.empty:
            checker.warn("Tool:safety review", "ran, but no scan rows found yet")
        else:
            checker.pass_("Tool:safety review", f"ran with {len(df)} rows")

    except Exception as error:
        checker.fail("Tool:safety review", error)

    try:
        from health_check import run_health_check

        text = run_health_check(write_report=True)

        if "FAIL" in text:
            checker.warn("Tool:health check", "ran; review logs/health_check.txt for details")
        else:
            checker.pass_("Tool:health check", "ran successfully")

    except Exception as error:
        checker.fail("Tool:health check", error)


def check_exe_build_artifacts(checker):
    build_script = BASE_DIR / "build_exe.bat"
    exe_path = BASE_DIR / "dist" / "OSRSFlipper.exe"

    if build_script.exists():
        checker.pass_("EXE:build script", str(build_script))
    else:
        checker.fail("EXE:build script", "missing")

    if exe_path.exists():
        checker.pass_("EXE:file", f"{exe_path} ({exe_path.stat().st_size:,} bytes)")
    else:
        checker.warn("EXE:file", "not built yet")


def run_release_check(strict=False, write_report=True):
    try:
        from app_version import get_version_info
        version_info = get_version_info()
    except Exception:
        version_info = {}

    LOG_DIR.mkdir(exist_ok=True)
    checker = ReleaseChecker(strict=strict)

    checker.info("Release:started", checker.started_at)
    checker.info("Release:project folder", str(BASE_DIR))
    if version_info:
        checker.info("Release:version", f"{version_info.get('app_name')} {version_info.get('app_version')} ({version_info.get('build_channel')})")

    check_required_files(checker)
    check_python_environment(checker)
    check_shared_key_safety(checker)
    check_module_imports(checker)
    check_database_and_migrations(checker)
    check_account_and_key(checker)
    check_runelite(checker)
    check_tools_run(checker)
    check_exe_build_artifacts(checker)

    report = checker.build_report()

    if write_report:
        checker.write_report()

    return {
        "status": checker.final_status(),
        "counts": checker.status_counts(),
        "report": report,
        "report_path": str(REPORT_FILE)
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run OSRSFlipper release readiness checks."
    )

    parser.add_argument("--strict", action="store_true", help="Treat warnings as release failures.")
    parser.add_argument("--no-write", action="store_true", help="Do not write logs/release_check.txt.")

    args = parser.parse_args()

    result = run_release_check(
        strict=args.strict,
        write_report=not args.no_write
    )

    print(result["report"])

    if not args.no_write:
        print()
        print(f"Report saved to: {result['report_path']}")

    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
