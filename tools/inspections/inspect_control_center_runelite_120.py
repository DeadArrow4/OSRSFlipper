from __future__ import annotations

from inspection_path import PROJECT_ROOT
from runelite_telemetry_control import format_runelite_telemetry_status


def main() -> int:
    print("OSRSFlipper 1.2.0 Control Center RuneLite Telemetry Inspection")
    print("=" * 82)

    control_path = PROJECT_ROOT / "osrs_control_center.py"
    helper_path = PROJECT_ROOT / "runelite_telemetry_control.py"

    control_text = control_path.read_text(encoding="utf-8", errors="ignore")
    helper_text = helper_path.read_text(encoding="utf-8", errors="ignore")

    checks = {
        "helper file exists": helper_path.exists(),
        "control center imports helper": "dashboard_startup_telemetry_message" in control_text,
        "control center startup check function": "def runelite_telemetry_startup_check" in control_text,
        "dashboard start calls telemetry check": "runelite_telemetry_startup_check(" in control_text,
        "helper can open Jagex Launcher": "def open_jagex_launcher" in helper_text,
        "helper can start dev client": "def start_runelite_telemetry_dev_client" in helper_text,
        "helper can import telemetry": "def import_runelite_state_now" in helper_text,
    }

    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}: {name}")

    print()
    print("Current telemetry status:")
    print(format_runelite_telemetry_status())

    if not all(checks.values()):
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
