import argparse
import os
import shutil
from security_runtime import scrub_shared_openai_env
from runelite_telemetry_control import (
    build_runelite_telemetry_status,
    dashboard_startup_telemetry_message,
    import_runelite_state_now,
    open_jagex_launcher,
    start_runelite_telemetry_dev_client,
)
scrub_shared_openai_env()
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from account_context import get_account_scope, resolve_app_base_dir
from app_version import get_version_line
from capital_budget import get_effective_cash_stack
from dashboard_control_commands import close_dashboard_app_windows, consume_dashboard_command
from migration_manager import run_app_migrations
from settings_manager import (
    ensure_default_settings,
    get_setting,
    configure_core_settings,
    configure_ai_settings,
    print_settings
)

try:
    from first_run_setup import run_first_run_setup
except Exception:
    run_first_run_setup = None

try:
    from account_manager import interactive_login_or_create, init_user_db
except Exception:
    interactive_login_or_create = None
    init_user_db = None


BASE_DIR = resolve_app_base_dir()
DB_FILE = BASE_DIR / "osrs_flip_scanner.db"
LOG_DIR = BASE_DIR / "logs"
DEFAULT_ACCOUNT = "DeadArrow98"
DASHBOARD_URL = "http://127.0.0.1:8050"
DEFAULT_DASHBOARD_OPEN_MODE = "app"
DEFAULT_STATUS_MODE = "quiet"

STOP_EVENT = threading.Event()


def running_as_frozen_exe():
    return bool(getattr(sys, "frozen", False))


def get_project_python():
    """
    When this file is packaged as OSRSFlipper.exe, sys.executable points to
    the EXE itself, not python.exe. Child scripts like dashboard.py and
    collector.py still need to run through the project venv Python.

    This keeps the EXE lightweight while using the existing project folder.
    """
    venv_python = BASE_DIR / ".venv" / "Scripts" / "python.exe"

    if venv_python.exists():
        return str(venv_python)

    # Fallback for normal script mode.
    return sys.executable


def script_command(script_name, *args):
    return [get_project_python(), script_name, *[str(arg) for arg in args]]


def windows_creationflags():
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def now_text():
    return datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")


def ensure_dirs():
    LOG_DIR.mkdir(exist_ok=True)



def setup_is_complete():
    """
    Basic readiness check before launching the control center.
    """
    try:
        from account_manager import get_current_session, list_users
        from openai_key_manager import get_api_key_status
        from settings_manager import get_setting

        users = list_users()

        if not users:
            return False, "No local OSRSFlipper user exists."

        session = get_current_session()

        if not session:
            return False, "No previous login session exists."

        os.environ["OSRSFLIPPER_USERNAME"] = str(session.get("username", "")).strip().lower()
        os.environ["RUNELITE_ACCOUNT"] = str(session.get("osrs_account_name", "")).strip()
        os.environ["OSRSFLIPPER_BASE_DIR"] = str(BASE_DIR)

        key_status = get_api_key_status()

        if not key_status.get("has_key"):
            return False, "No encrypted OpenAI API key is saved for the last login."

        # Also confirms settings table exists and has defaults.
        get_setting("max_ai_requests_per_day", 20)

        return True, "Setup appears complete."

    except Exception as error:
        return False, f"Setup check failed: {error}"



def set_shared_runtime_env(account, app_username=None, user_id=None):
    """
    Makes sure dashboard.py/advisor.py/trade_tracker.py can see the same
    local user and RuneLite account selected in the control center.
    """
    os.environ["RUNELITE_ACCOUNT"] = str(account)
    os.environ["OSRSFLIPPER_BASE_DIR"] = str(BASE_DIR)

    if app_username:
        os.environ["OSRSFLIPPER_USERNAME"] = str(app_username).strip().lower()

    if user_id is not None:
        os.environ["OSRSFLIPPER_USER_ID"] = str(user_id)


def get_connection():
    return sqlite3.connect(DB_FILE)


def safe_db_value(query, params=(), default=None):
    if not DB_FILE.exists():
        return default

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
        conn.close()

        if not row:
            return default

        return row[0]

    except Exception:
        return default


def get_latest_scan_time():
    return safe_db_value(
        """
        SELECT scanned_at
        FROM scan_runs
        ORDER BY id DESC
        LIMIT 1
        """,
        default="No scan yet"
    )


def get_latest_trade_event_time():
    scope = get_account_scope()

    return safe_db_value(
        """
        SELECT imported_at
        FROM trade_events
        WHERE app_username = ?
          AND osrs_account_name = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (
            scope["app_username"],
            scope["osrs_account_name"]
        ),
        default="No trade import yet"
    )


def get_latest_completed_trade_time():
    scope = get_account_scope()

    return safe_db_value(
        """
        SELECT created_at
        FROM completed_trades
        WHERE app_username = ?
          AND osrs_account_name = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (
            scope["app_username"],
            scope["osrs_account_name"]
        ),
        default="No completed trade yet"
    )


def count_completed_trades():
    scope = get_account_scope()

    return safe_db_value(
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
    ) or 0


def count_open_buys():
    scope = get_account_scope()

    return safe_db_value(
        """
        SELECT COUNT(*)
        FROM trade_events
        WHERE app_username = ?
          AND osrs_account_name = ?
          AND side = 'BUY'
          AND remaining_quantity > 0
        """,
        (
            scope["app_username"],
            scope["osrs_account_name"]
        ),
        default=0
    ) or 0


def get_total_realized_profit():
    scope = get_account_scope()

    return safe_db_value(
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
    ) or 0


def format_gp(value):
    try:
        value = int(value)
    except Exception:
        value = 0

    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,} gp"


def process_running(process):
    return process is not None and process.poll() is None


def runelite_telemetry_startup_check(force_open_jagex=False, force_start_dev_client=False, verbose=True):
    """Print RuneLite telemetry status and optional launch guidance when the dashboard starts."""
    def emit(message=""):
        if verbose:
            print(message)

    try:
        emit()
        emit(dashboard_startup_telemetry_message())
        status = build_runelite_telemetry_status()

        try:
            auto_open_jagex = force_open_jagex or bool(get_setting("open_jagex_launcher_with_dashboard", False))
        except Exception:
            auto_open_jagex = False

        try:
            auto_start_dev_client = force_start_dev_client or bool(get_setting("auto_start_runelite_telemetry_dev_client", False))
        except Exception:
            auto_start_dev_client = False

        if auto_open_jagex:
            emit(open_jagex_launcher())

        if auto_start_dev_client:
            emit(start_runelite_telemetry_dev_client())
        else:
            emit(
                "RuneLite telemetry dev-client auto-start is off. "
                "Install OSRSFlipper Telemetry from RuneLite Plugin Hub in normal RuneLite. "
                "For local troubleshooting only, run: python runelite_telemetry_control.py start-dev"
            )

        if status.get("ready"):
            try:
                emit(import_runelite_state_now())
            except Exception as import_error:
                emit(f"RuneLite telemetry import skipped: {import_error}")
        else:
            emit(f"RuneLite telemetry import skipped: {status.get('problem') or 'not ready'}.")
            emit(
                "Open Jagex Launcher, start RuneLite, install or enable OSRSFlipper Telemetry from Plugin Hub, "
                "then log into OSRS and wait for telemetry to refresh."
            )

    except Exception as telemetry_error:
        emit(f"RuneLite telemetry startup check failed: {telemetry_error}")

def start_dashboard():
    log_path = LOG_DIR / "dashboard.log"
    err_path = LOG_DIR / "dashboard_error.log"

    stdout = open(log_path, "a", encoding="utf-8")
    stderr = open(err_path, "a", encoding="utf-8")

    process = subprocess.Popen(
        script_command("dashboard.py"),
        cwd=str(BASE_DIR),
        stdout=stdout,
        stderr=stderr,
        stdin=subprocess.DEVNULL,
        creationflags=windows_creationflags()
    )

    return process


def start_collector(cash_stack, minimum_profit, risk_profile):
    log_path = LOG_DIR / "collector.log"
    err_path = LOG_DIR / "collector_error.log"

    stdout = open(log_path, "a", encoding="utf-8")
    stderr = open(err_path, "a", encoding="utf-8")

    process = subprocess.Popen(
        script_command("collector.py"),
        cwd=str(BASE_DIR),
        stdin=subprocess.PIPE,
        stdout=stdout,
        stderr=stderr,
        text=True,
        creationflags=windows_creationflags()
    )

    # collector.py asks for these values once at startup.
    startup_input = f"{int(cash_stack)}\n{int(minimum_profit)}\n{risk_profile}\n"

    try:
        process.stdin.write(startup_input)
        process.stdin.flush()
        process.stdin.close()
    except Exception:
        pass

    return process


def run_setup(account):
    commands = [
        script_command("trade_tracker.py", "init"),
        script_command("trade_importer.py", "init"),
        script_command("trade_importer.py", "import-runelite", "--account", account),
    ]

    for command in commands:
        try:
            subprocess.run(
                command,
                cwd=str(BASE_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=windows_creationflags()
            )
        except Exception:
            pass


class TradeWatcherStatus:
    def __init__(self):
        self.running = False
        self.last_check = "Never"
        self.last_import = "Never"
        self.last_message = "Waiting to start"
        self.records_found = 0
        self.new_rows = 0
        self.duplicates = 0
        self.ignored = 0
        self.matched = 0
        self.error = ""


def trade_watcher_loop(account, seconds, status):
    status.running = True
    status.last_message = "Starting"

    try:
        from trade_importer import import_runelite_file, resolve_runelite_file

        runelite_file = resolve_runelite_file(account=account)
        status.last_message = f"Watching {runelite_file}"

        last_modified = None
        last_size = None

        while not STOP_EVENT.is_set():
            status.last_check = now_text()

            try:
                stat = os.stat(runelite_file)

                if stat.st_mtime != last_modified or stat.st_size != last_size:
                    result = import_runelite_file(account=account, force=True)

                    status.last_import = now_text()
                    status.records_found = result.get("records_found", 0)
                    status.new_rows = result.get("imported", 0)
                    status.duplicates = result.get("duplicates", 0)
                    status.ignored = result.get("ignored", 0)
                    status.matched = result.get("matched", 0)
                    status.last_message = result.get("message", "Imported")
                    status.error = ""

                    last_modified = stat.st_mtime
                    last_size = stat.st_size

            except Exception as error:
                status.error = str(error)
                status.last_message = "Watcher error"

            STOP_EVENT.wait(seconds)

    finally:
        status.running = False


def normalize_dashboard_open_mode(value):
    value = str(value or DEFAULT_DASHBOARD_OPEN_MODE).strip().lower()

    if value in {"browser", "tab"}:
        return "browser"

    return "app"


def dashboard_app_browser_command():
    if os.name != "nt":
        return None

    executable_candidates = [
        shutil.which("msedge"),
        shutil.which("chrome"),
        shutil.which("chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]

    for executable in executable_candidates:
        if executable and Path(executable).exists():
            return [executable, f"--app={DASHBOARD_URL}", "--new-window"]

    return None


def open_dashboard(open_mode=DEFAULT_DASHBOARD_OPEN_MODE):
    open_mode = normalize_dashboard_open_mode(open_mode)

    if open_mode == "app":
        command = dashboard_app_browser_command()

        if command:
            try:
                subprocess.Popen(
                    command,
                    cwd=str(BASE_DIR),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=windows_creationflags()
                )
                return "Opened dashboard in app window."
            except Exception:
                pass

    if os.name == "nt":
        subprocess.Popen(
            f'start "" "{DASHBOARD_URL}"',
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return "Opened dashboard in browser."

    return "Dashboard URL: " + DASHBOARD_URL


def read_key_nonblocking():
    if os.name != "nt":
        return None

    try:
        import msvcrt

        if msvcrt.kbhit():
            return msvcrt.getwch().lower()

    except Exception:
        return None

    return None


def handle_dashboard_command(
    command_payload,
    dashboard_process,
    collector_process,
    trade_status,
    started_at,
    dashboard_open_mode,
    status_mode,
):
    if not command_payload:
        return False

    command = command_payload.get("command")

    if command == "stop_all":
        print("Dashboard requested Stop Services.")
        STOP_EVENT.set()
        return True

    if command == "refresh_status":
        draw_screen(
            dashboard_process=dashboard_process,
            collector_process=collector_process,
            trade_status=trade_status,
            started_at=started_at,
            clear=False
        )
        return False

    if command == "open_dashboard":
        message = open_dashboard(dashboard_open_mode)
        if status_mode == "quiet":
            print(message)
        return False

    return False


def draw_screen(dashboard_process, collector_process, trade_status, started_at, clear=True):
    dashboard_status = "RUNNING" if process_running(dashboard_process) else "STOPPED"
    collector_status = "RUNNING" if process_running(collector_process) else "STOPPED"

    latest_scan = get_latest_scan_time()
    latest_trade_import = get_latest_trade_event_time()
    latest_completed_trade = get_latest_completed_trade_time()
    completed_count = count_completed_trades()
    open_buys = count_open_buys()
    total_profit = get_total_realized_profit()
    telemetry_status = build_runelite_telemetry_status()
    telemetry_state = "READY" if telemetry_status.get("ready") else "NOT READY"
    telemetry_problem = telemetry_status.get("problem") or "OK"

    if clear:
        clear_screen()

    print("==============================")
    print(" OSRSFlipper Control Center")
    print("==============================")
    print(f"Started: {started_at}")
    print(f"OSRSFlipper user: {os.environ.get('OSRSFLIPPER_USERNAME', 'not logged in')}")
    print(f"RuneLite account: {os.environ.get('RUNELITE_ACCOUNT', 'not set')}")
    print(f"Dashboard: {DASHBOARD_URL}")
    print()
    print("Processes")
    print("---------")
    print(f"Dashboard:        {dashboard_status}  (hidden background process)")
    print(f"Market collector: {collector_status}")
    print(f"Trade watcher:    {'RUNNING' if trade_status.running else 'STOPPED'}")
    print()
    print("RuneLite Telemetry")
    print("------------------")
    print(f"Capital state:    {telemetry_state}")
    print(f"Payload:          {telemetry_status.get('payload_kind', 'unknown')}")
    print(f"Account:          {telemetry_status.get('account_name', 'default')}")
    print(f"Captured:         {telemetry_status.get('captured_at') or 'n/a'}")
    print(f"Age seconds:      {telemetry_status.get('age_seconds') if telemetry_status.get('age_seconds') is not None else 'n/a'}")
    print(f"Status:           {telemetry_problem}")
    print(f"File:             {telemetry_status.get('path')}")
    print()
    print("Market Collector Status")
    print("-----------------------")
    print(f"Last scan saved:  {latest_scan}")
    print(f"Collector log:    {LOG_DIR / 'collector.log'}")
    print()
    print("Trade Watcher Status")
    print("--------------------")
    print(f"Last check:       {trade_status.last_check}")
    print(f"Last import:      {trade_status.last_import}")
    print(f"Last DB import:   {latest_trade_import}")
    print(f"Completed trade:  {latest_completed_trade}")
    print(f"New rows:         {trade_status.new_rows}")
    print(f"Duplicates:       {trade_status.duplicates}")
    print(f"Ignored/open:     {trade_status.ignored}")
    print(f"Matched flips:    {trade_status.matched}")
    print(f"Message:          {trade_status.last_message}")

    if trade_status.error:
        print(f"Watcher error:    {trade_status.error}")

    print()
    print("My Trades Snapshot")
    print("------------------")
    print(f"Completed flips:  {completed_count}")
    print(f"Open buy events:  {open_buys}")
    print(f"Realized P/L:     {format_gp(total_profit)}")
    print()
    print("Saved Settings")
    print("--------------")
    print(f"Risk profile:     {get_setting('risk_profile', 'medium')}")
    print(f"Cash stack:       {format_gp(get_setting('cash_stack', 0))}")
    try:
        budget = get_effective_cash_stack()
        print(f"Budget mode:      {budget.get('mode')} ({budget.get('source')})")
        print(f"Effective budget: {format_gp(budget.get('cash_stack', 0))}")
    except Exception as budget_error:
        print(f"Budget mode:      unavailable ({budget_error})")
    print(f"Minimum profit:   {format_gp(get_setting('minimum_profit', 0))}")
    print(f"Watcher seconds:  {get_setting('watch_seconds', 10)}")
    print()
    print("Controls")
    print("--------")
    print("Press O to open dashboard.")
    print("Press J to open Jagex Launcher.")
    print("Press D to start RuneLite telemetry dev client.")
    print("Press T to import fresh telemetry now.")
    print("Press R to refresh now.")
    print("Press Q to stop everything and exit.")
    print("Run with --configure-settings or --configure-ai-settings to change saved settings.")
    print()
    print("Note: Dashboard is running hidden. Only this control window stays visible.")


def print_quiet_startup_summary(dashboard_process, collector_process, trade_status, started_at, dashboard_open_mode):
    dashboard_status = "RUNNING" if process_running(dashboard_process) else "STOPPED"
    collector_status = "RUNNING" if process_running(collector_process) else "STOPPED"

    print()
    print("==============================")
    print(" OSRSFlipper Launcher")
    print("==============================")
    print(f"Started:          {started_at}")
    print(f"Dashboard:        {dashboard_status} at {DASHBOARD_URL}")
    print(f"Dashboard window: {normalize_dashboard_open_mode(dashboard_open_mode)}")
    print(f"Market collector: {collector_status}")
    print(f"Trade watcher:    {'RUNNING' if trade_status.running else 'STARTING'}")
    print()
    print("The dashboard is the main app surface now.")
    print("Press S for a status snapshot, O to reopen dashboard, R to refresh status, Q to stop everything.")


def stop_process(process, name):
    if not process_running(process):
        return

    print(f"Stopping {name}...")

    try:
        process.terminate()
        process.wait(timeout=8)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def ask_value(prompt, default, cast=str, allowed=None):
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()

        if raw == "":
            raw = default

        try:
            value = cast(raw)
        except Exception:
            print("Invalid value. Try again.")
            continue

        if allowed and value not in allowed:
            print(f"Use one of: {', '.join(allowed)}")
            continue

        return value


def parse_args():
    parser = argparse.ArgumentParser(
        description="Single-window OSRSFlipper control center."
    )

    parser.add_argument("--account", default=None)
    parser.add_argument("--risk", choices=["low", "medium", "high"], default=None)
    parser.add_argument("--cash", type=int, default=None)
    parser.add_argument("--min-profit", type=int, default=None)
    parser.add_argument("--watch-seconds", type=int, default=None)

    parser.add_argument("--no-dashboard", action="store_true")
    parser.add_argument("--no-collector", action="store_true")
    parser.add_argument("--no-trade-watcher", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--dashboard-open-mode", choices=["app", "browser"], default=None, help="Open dashboard as app window or normal browser tab.")
    parser.add_argument("--quiet", action="store_true", help="Start services without repainting the console status screen.")
    parser.add_argument("--status-screen", action="store_true", help="Show the continuously refreshed control-center status screen.")
    parser.add_argument("--skip-setup", action="store_true")
    parser.add_argument("--no-login", action="store_true")
    parser.add_argument("--open-jagex-launcher", action="store_true", help="Open Jagex Launcher when the dashboard starts.")
    parser.add_argument("--start-runelite-telemetry-dev", action="store_true", help="Start the RuneLite telemetry dev client when the dashboard starts.")
    parser.add_argument("--first-run", action="store_true", help="Run first-run setup wizard before launching.")
    parser.add_argument("--skip-first-run-check", action="store_true", help="Do not auto-prompt for first-run setup.")

    parser.add_argument(
        "--configure-settings",
        action="store_true",
        help="Configure startup/collector settings before launching."
    )

    parser.add_argument(
        "--configure-ai-settings",
        action="store_true",
        help="Configure AI advisor settings before launching."
    )

    parser.add_argument(
        "--show-settings",
        action="store_true",
        help="Print saved settings before launching."
    )

    return parser.parse_args()


def main():
    args = parse_args()

    ensure_dirs()

    try:
        migration_result = run_app_migrations(write_report=True)
        print(f"Database migrations checked. Report: {migration_result.get('report_path')}")
    except Exception as error:
        print(f"WARNING: Database migration check failed: {error}")

    if args.first_run:
        if run_first_run_setup is None:
            print("First-run setup wizard is not available. Make sure first_run_setup.py exists.")
            return
        run_first_run_setup(force=True)

    elif not args.skip_first_run_check:
        ready, setup_message = setup_is_complete()

        if not ready:
            print("\n==============================")
            print(" First-Run Setup Recommended")
            print("==============================")
            print(setup_message)
            print()
            if run_first_run_setup is not None:
                choice = input("Run setup wizard now? (Y/n): ").strip().lower()

                if choice in ("", "y", "yes"):
                    run_first_run_setup(force=False)
            else:
                print("first_run_setup.py was not found. Continuing without wizard.")

    print("\n==============================")
    print(" OSRSFlipper Control Center")
    print("==============================")
    print()

    app_user = None

    if not args.no_login and interactive_login_or_create is not None:
        if init_user_db is not None:
            init_user_db()

        app_user = interactive_login_or_create()
        account = app_user.get("osrs_account_name") or args.account or DEFAULT_ACCOUNT
    else:
        account = args.account or ask_value("RuneLite account name", DEFAULT_ACCOUNT, str)

    if app_user:
        set_shared_runtime_env(
            account=account,
            app_username=app_user.get("username", ""),
            user_id=app_user.get("id", "")
        )
    else:
        set_shared_runtime_env(account=account)

    ensure_default_settings()

    if args.configure_settings:
        configure_core_settings()

    if args.configure_ai_settings:
        configure_ai_settings()

    if args.show_settings:
        print_settings()

    saved_risk = get_setting("risk_profile", "medium")
    saved_cash = get_setting("cash_stack", 10000000)
    saved_min_profit = get_setting("minimum_profit", 50000)
    saved_watch_seconds = get_setting("watch_seconds", 10)
    dashboard_open_mode = normalize_dashboard_open_mode(
        args.dashboard_open_mode or get_setting("dashboard_open_mode", DEFAULT_DASHBOARD_OPEN_MODE)
    )
    status_mode = str(get_setting("control_center_status_mode", DEFAULT_STATUS_MODE) or DEFAULT_STATUS_MODE).strip().lower()

    if status_mode not in {"quiet", "status"}:
        status_mode = DEFAULT_STATUS_MODE

    if args.status_screen:
        status_mode = "status"

    if args.quiet:
        status_mode = "quiet"

    risk_profile = args.risk or saved_risk
    manual_cash_stack = args.cash if args.cash is not None else saved_cash
    budget = get_effective_cash_stack(manual_cash_stack)
    cash_stack = int(budget.get("cash_stack", manual_cash_stack))
    minimum_profit = args.min_profit if args.min_profit is not None else saved_min_profit

    if args.watch_seconds is None:
        args.watch_seconds = int(saved_watch_seconds)

    # Saved startup settings can disable services unless the user explicitly used
    # the matching command-line flags.
    if not get_setting("start_dashboard", True):
        args.no_dashboard = True

    if not get_setting("start_collector", True):
        args.no_collector = True

    if not get_setting("start_trade_watcher", True):
        args.no_trade_watcher = True

    if not get_setting("open_browser", True):
        args.no_browser = True

    if not args.skip_setup:
        print("\nRunning setup/import checks...")
        run_setup(account)

    dashboard_process = None
    collector_process = None
    trade_status = TradeWatcherStatus()
    trade_thread = None

    started_at = now_text()

    try:
        if not args.no_dashboard:
            dashboard_process = start_dashboard()
            runelite_telemetry_startup_check(
                force_open_jagex=args.open_jagex_launcher,
                force_start_dev_client=args.start_runelite_telemetry_dev,
                verbose=status_mode == "status"
            )

        if not args.no_collector:
            print(
                "Collector budget: "
                f"{format_gp(cash_stack)} "
                f"({budget.get('source')}; manual cap {format_gp(budget.get('manual_cash_stack', manual_cash_stack))})."
            )
            collector_process = start_collector(
                cash_stack=cash_stack,
                minimum_profit=minimum_profit,
                risk_profile=risk_profile
            )

        if not args.no_trade_watcher:
            trade_thread = threading.Thread(
                target=trade_watcher_loop,
                args=(account, args.watch_seconds, trade_status),
                daemon=True
            )
            trade_thread.start()

        if not args.no_dashboard and not args.no_browser:
            time.sleep(2)
            message = open_dashboard(dashboard_open_mode)
            if status_mode == "status":
                print(message)

        quiet_summary_printed = False

        while not STOP_EVENT.is_set():
            if status_mode == "status":
                draw_screen(
                    dashboard_process=dashboard_process,
                    collector_process=collector_process,
                    trade_status=trade_status,
                    started_at=started_at
                )
            elif not quiet_summary_printed:
                print_quiet_startup_summary(
                    dashboard_process=dashboard_process,
                    collector_process=collector_process,
                    trade_status=trade_status,
                    started_at=started_at,
                    dashboard_open_mode=dashboard_open_mode
                )
                quiet_summary_printed = True

            # Refresh loop with keyboard checks.
            for _ in range(10):
                if handle_dashboard_command(
                    consume_dashboard_command(),
                    dashboard_process=dashboard_process,
                    collector_process=collector_process,
                    trade_status=trade_status,
                    started_at=started_at,
                    dashboard_open_mode=dashboard_open_mode,
                    status_mode=status_mode,
                ):
                    break

                key = read_key_nonblocking()

                if key == "q":
                    STOP_EVENT.set()
                    break

                if key == "o":
                    message = open_dashboard(dashboard_open_mode)
                    if status_mode == "quiet":
                        print(message)

                if key == "j":
                    print(open_jagex_launcher())

                if key == "d":
                    print(start_runelite_telemetry_dev_client())

                if key == "t":
                    print(import_runelite_state_now())

                if key == "s":
                    draw_screen(
                        dashboard_process=dashboard_process,
                        collector_process=collector_process,
                        trade_status=trade_status,
                        started_at=started_at,
                        clear=False
                    )

                if key == "r":
                    if status_mode == "quiet":
                        draw_screen(
                            dashboard_process=dashboard_process,
                            collector_process=collector_process,
                            trade_status=trade_status,
                            started_at=started_at,
                            clear=False
                        )
                    break

                time.sleep(0.5)

    except KeyboardInterrupt:
        STOP_EVENT.set()

    finally:
        clear_screen()
        print("Stopping OSRSFlipper services...")
        STOP_EVENT.set()

        close_dashboard_app_windows()
        stop_process(collector_process, "collector")
        stop_process(dashboard_process, "dashboard")

        if trade_thread and trade_thread.is_alive():
            trade_thread.join(timeout=5)

        print("Stopped.")


if __name__ == "__main__":
    main()
