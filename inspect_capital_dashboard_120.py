from __future__ import annotations

from pathlib import Path

from capital_dashboard import build_ai_capital_context_text, load_capital_dashboard_state


def main() -> int:
    print("OSRSFlipper 1.2.0 Capital Dashboard Inspection")
    print("=" * 72)

    data = load_capital_dashboard_state(import_live=True)
    capital = data["capital"]

    print(f"Telemetry file: {data['state_path']}")
    print(f"Telemetry exists: {data['telemetry_exists']}")
    print(f"Payload kind: {data['payload_kind']}")
    print(f"Loaded at: {data['loaded_at']}")
    print()

    print("Capital summary:")
    for key in [
        "account_name",
        "captured_at",
        "raw_gp_available",
        "inventory_gp",
        "bank_gp",
        "locked_buy_gp",
        "locked_sell_value_gp",
        "safety_reserve_gp",
        "usable_gp",
        "open_offer_count",
        "open_slots",
        "stuck_offers",
    ]:
        print(f"- {key}: {capital.get(key)}")

    print()
    print(f"Open offer rows: {len(data['rows'])}")
    for row in data["rows"][:8]:
        print(f"- {row}")

    print()
    print("AI capital context:")
    print(build_ai_capital_context_text())

    print()
    for path in [
        Path("dashboard_tabs") / "__init__.py",
        Path("dashboard_callbacks") / "__init__.py",
        Path("capital_dashboard.py"),
    ]:
        print(f"{path}: {'found' if path.exists() else 'missing'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
