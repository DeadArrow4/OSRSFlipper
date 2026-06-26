import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from account_context import BASE_DIR
VENV_ACTIVATE = BASE_DIR / ".venv" / "Scripts" / "activate.bat"
RUNTIME_DIR = BASE_DIR / ".osrs_runtime"

DEFAULT_ACCOUNT = "DeadArrow98"
DEFAULT_DASHBOARD_URL = "http://127.0.0.1:8050"


def run_command(command, check=False):
    print(f"> {command}")
    return subprocess.run(
        command,
        cwd=str(BASE_DIR),
        shell=True,
        check=check
    )


def quote_cmd(value):
    text = str(value)
    return text.replace('"', '\\"')


def make_common_bat_header(title):
    lines = [
        "@echo off",
        f"title {title}",
        "color 0A",
        f'cd /d "{BASE_DIR}"',
    ]

    if VENV_ACTIVATE.exists():
        lines.append(f'call "{VENV_ACTIVATE}"')

    lines.append("")

    return "\n".join(lines)


def write_bat_file(file_name, title, commands):
    RUNTIME_DIR.mkdir(exist_ok=True)

    path = RUNTIME_DIR / file_name

    content = make_common_bat_header(title)
    content += "\n".join(commands)
    content += "\n\necho.\necho Process ended. Press any key to close this window.\npause >nul\n"

    path.write_text(content, encoding="utf-8")

    return path


def start_bat_window(path):
    # Windows-only start command. This project is running on Windows.
    subprocess.Popen(
        f'start "" "{path}"',
        cwd=str(BASE_DIR),
        shell=True
    )


def ensure_core_setup(account):
    print("\n==============================")
    print(" OSRSFlipper Setup")
    print("==============================")

    if not (BASE_DIR / "trade_tracker.py").exists():
        print("WARNING: trade_tracker.py was not found.")

    if not (BASE_DIR / "trade_importer.py").exists():
        print("WARNING: trade_importer.py was not found.")

    if not (BASE_DIR / "dashboard.py").exists():
        print("WARNING: dashboard.py was not found.")

    if not (BASE_DIR / "collector.py").exists():
        print("WARNING: collector.py was not found.")

    # These commands are safe to run repeatedly.
    if (BASE_DIR / "trade_tracker.py").exists():
        run_command("python trade_tracker.py init", check=False)

    if (BASE_DIR / "trade_importer.py").exists():
        run_command("python trade_importer.py init", check=False)

        # One-time import before watcher starts. Safe because duplicate UUIDs are skipped.
        run_command(
            f"python trade_importer.py import-runelite --account {account}",
            check=False
        )


def create_trade_watcher_bat(account, seconds):
    return write_bat_file(
        file_name="runelite_trade_watcher.bat",
        title="OSRS Trade Watcher",
        commands=[
            f"python trade_importer.py watch-runelite --account {quote_cmd(account)} --seconds {int(seconds)}"
        ]
    )


def create_dashboard_bat():
    return write_bat_file(
        file_name="dashboard.bat",
        title="OSRS Dashboard",
        commands=[
            "python dashboard.py"
        ]
    )


def create_collector_bat(cash_stack, minimum_profit, risk_profile):
    # collector.py prompts for cash stack, minimum profit, and risk profile.
    # This pipes answers into the collector so it can run unattended.
    return write_bat_file(
        file_name="collector.bat",
        title="OSRS Market Collector",
        commands=[
            "(",
            f"echo {int(cash_stack)}",
            f"echo {int(minimum_profit)}",
            f"echo {quote_cmd(risk_profile)}",
            ") | python collector.py"
        ]
    )


def create_ai_advisor_bat(risk_profile):
    return write_bat_file(
        file_name="ai_advisor_once.bat",
        title="OSRS AI Advisor",
        commands=[
            "(",
            f"echo {quote_cmd(risk_profile)}",
            ") | python advisor.py"
        ]
    )


def open_dashboard_url():
    try:
        subprocess.Popen(
            f'start "" "{DEFAULT_DASHBOARD_URL}"',
            shell=True
        )
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
        description="One-command launcher for OSRSFlipper."
    )

    parser.add_argument("--account", default=None, help="RuneLite account name, for example DeadArrow98.")
    parser.add_argument("--cash", type=int, default=None, help="Cash stack for collector.py.")
    parser.add_argument("--min-profit", type=int, default=None, help="Minimum profit for collector.py.")
    parser.add_argument("--risk", default=None, choices=["low", "medium", "high"], help="Risk profile.")
    parser.add_argument("--watch-seconds", type=int, default=10, help="RuneLite file watch interval.")

    parser.add_argument("--no-collector", action="store_true", help="Do not start collector.py.")
    parser.add_argument("--no-dashboard", action="store_true", help="Do not start dashboard.py.")
    parser.add_argument("--no-trade-watcher", action="store_true", help="Do not start RuneLite trade watcher.")
    parser.add_argument("--run-ai-once", action="store_true", help="Also run advisor.py once in its own window.")

    parser.add_argument("--no-browser", action="store_true", help="Do not open dashboard URL.")
    parser.add_argument("--skip-setup", action="store_true", help="Skip init/import setup commands.")

    return parser.parse_args()


def main():
    args = parse_args()

    print("\n==============================")
    print(" OSRSFlipper One-Command Start")
    print("==============================")
    print(f"Project folder: {BASE_DIR}")
    print()

    account = args.account or ask_value(
        "RuneLite account name",
        DEFAULT_ACCOUNT,
        str
    )

    risk_profile = args.risk or ask_value(
        "Risk profile",
        "medium",
        str,
        allowed=["low", "medium", "high"]
    )

    cash_stack = args.cash

    if cash_stack is None and not args.no_collector:
        cash_stack = ask_value(
            "Cash stack",
            "10000000",
            int
        )

    minimum_profit = args.min_profit

    if minimum_profit is None and not args.no_collector:
        minimum_profit = ask_value(
            "Minimum profit",
            "50000",
            int
        )

    if not args.skip_setup:
        ensure_core_setup(account=account)

    windows = []

    if not args.no_trade_watcher:
        watcher_bat = create_trade_watcher_bat(
            account=account,
            seconds=args.watch_seconds
        )
        windows.append(("Trade watcher", watcher_bat))

    if not args.no_collector:
        collector_bat = create_collector_bat(
            cash_stack=cash_stack,
            minimum_profit=minimum_profit,
            risk_profile=risk_profile
        )
        windows.append(("Collector", collector_bat))

    if not args.no_dashboard:
        dashboard_bat = create_dashboard_bat()
        windows.append(("Dashboard", dashboard_bat))

    if args.run_ai_once:
        advisor_bat = create_ai_advisor_bat(
            risk_profile=risk_profile
        )
        windows.append(("AI advisor", advisor_bat))

    print("\n==============================")
    print(" Starting Windows")
    print("==============================")

    for name, bat_path in windows:
        print(f"Starting {name}: {bat_path}")
        start_bat_window(bat_path)
        time.sleep(1)

    if not args.no_dashboard and not args.no_browser:
        time.sleep(3)
        open_dashboard_url()

    print("\nAll requested OSRSFlipper processes were started.")
    print()
    print("Open dashboard:")
    print(DEFAULT_DASHBOARD_URL)
    print()
    print("Runtime helper BAT files were generated here:")
    print(RUNTIME_DIR)
    print()
    print("Close each opened command window to stop that process.")


if __name__ == "__main__":
    main()
