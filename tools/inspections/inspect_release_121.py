from __future__ import annotations

from inspection_path import PROJECT_ROOT


def main() -> int:
    print("OSRSFlipper 1.2.1 Release Metadata Inspection")
    print("=" * 72)

    checks = {}

    app_version = PROJECT_ROOT / "app_version.py"
    if app_version.exists():
        text = app_version.read_text(encoding="utf-8", errors="ignore")
        checks["app_version.py has 1.2.1"] = 'APP_VERSION = "1.2.1"' in text
    else:
        checks["app_version.py exists"] = False

    release_notes = PROJECT_ROOT / "RELEASE_NOTES.txt"
    if release_notes.exists():
        text = release_notes.read_text(encoding="utf-8", errors="ignore")
        checks["release notes have 1.2.1"] = "OSRSFlipper 1.2.1 - Release Package Patch" in text
        checks["release notes retain 1.2.0 feature notes"] = "OSRSFlipper 1.2.0 - Capital-Aware AI and RuneLite Telemetry" in text
        checks["release notes mention read-only RuneLite"] = "RuneLite integration is read-only" in text
        checks["release notes mention capital-fit columns"] = "Capital Fit" in text and "Fit Qty" in text
    else:
        checks["RELEASE_NOTES.txt exists"] = False

    feature_files = [
        "capital_ai_memory.py",
        "runelite_state_importer.py",
        "capital_dashboard.py",
        "ai_capital_advisor_context.py",
        "capital_trade_board.py",
        "runtime/runelite_state.example.json",
    ]

    for rel in feature_files:
        checks[f"feature file: {rel}"] = (PROJECT_ROOT / rel).exists()

    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}: {name}")

    if not all(checks.values()):
        return 1

    print()
    print("Release metadata looks ready for 1.2.1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
