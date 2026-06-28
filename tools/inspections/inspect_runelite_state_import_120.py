from __future__ import annotations

from inspection_path import PROJECT_ROOT
from runelite_state_importer import import_runelite_state, print_import_result
from capital_ai_memory import format_gp, score_flip_for_capital


def main() -> int:
    example_path = PROJECT_ROOT / "runtime" / "runelite_state.example.json"

    print("OSRSFlipper 1.2.0 RuneLite Telemetry Import Inspection")
    print("=" * 78)
    print(f"Example telemetry: {example_path}")
    print()

    result = import_runelite_state(example_path)
    print_import_result(result)

    print()
    print("Fire rune 5 -> 6 GP check using imported usable GP")
    print("=" * 78)

    score = score_flip_for_capital(
        item_name="Fire rune",
        buy_price=5,
        sell_price=6,
        proposed_quantity=1_000_000,
        account_name=result["account_name"],
    )

    print(f"Suggested quantity: {score['suggested_quantity']:,}")
    print(f"Required GP:        {format_gp(score['required_gp'])}")
    print(f"Usable GP:          {format_gp(score['usable_gp'])}")
    print(f"Expected profit:    {format_gp(score['expected_profit_gp'])}")
    print(f"Score:              {score['score']:.1f}/100")
    print(f"OK:                 {score['ok']}")

    if score["warnings"]:
        print()
        print("Warnings")
        print("-" * 78)
        for warning in score["warnings"]:
            print(f"- {warning}")

    print()
    print("Inspection complete.")
    print("This used runtime/runelite_state.example.json only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
