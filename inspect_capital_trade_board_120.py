from __future__ import annotations

from pathlib import Path

import pandas as pd

from capital_trade_board import apply_capital_limits_to_trade_board, load_trade_board_capital_state


def main() -> int:
    print("OSRSFlipper 1.2.0 Trade Board Capital Fit Inspection")
    print("=" * 76)

    dashboard_data_path = Path("dashboard_data.py")
    text = dashboard_data_path.read_text(encoding="utf-8", errors="ignore")

    checks = {
        "helper import/call": "apply_capital_limits_to_trade_board" in text,
        "capital fit column": '"Capital Fit"' in text,
        "fit qty column": '"Fit Qty"' in text,
        "fit cost column": '"Fit Cost"' in text,
        "fit profit column": '"Fit Profit"' in text,
        "capital note column": '"Capital Note"' in text,
    }

    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}: {name}")

    print()
    print("Live capital state:")
    print(load_trade_board_capital_state())

    sample = pd.DataFrame(
        [
            {
                "item_name": "Example item",
                "target_buy": 100,
                "target_sell": 125,
                "quantity": 10000,
                "profit_per_item": 24,
                "total_profit": 240000,
            }
        ]
    )

    enriched, summary = apply_capital_limits_to_trade_board(sample)

    print()
    print("Synthetic row preview:")
    for column in [
        "Capital Needed Live",
        "Capital Fit",
        "Capital Fit Qty",
        "Capital Fit Cost",
        "Capital Fit Profit",
        "Capital Note",
    ]:
        print(f"- {column}: {enriched.iloc[0].get(column)}")

    if not all(checks.values()):
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
