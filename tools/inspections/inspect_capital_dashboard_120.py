from __future__ import annotations

from inspection_path import PROJECT_ROOT
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
        "buy_filled_value_gp",
        "locked_sell_value_gp",
        "sell_filled_value_gp",
        "total_ge_value_held_gp",
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
        PROJECT_ROOT / "dashboard_tabs" / "__init__.py",
        PROJECT_ROOT / "dashboard_callbacks" / "__init__.py",
        PROJECT_ROOT / "capital_dashboard.py",
    ]:
        print(f"{path.relative_to(PROJECT_ROOT)}: {'found' if path.exists() else 'missing'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
