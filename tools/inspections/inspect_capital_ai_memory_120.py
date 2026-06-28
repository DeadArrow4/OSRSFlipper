from __future__ import annotations

from inspection_path import PROJECT_ROOT
from capital_ai_memory import (
    ensure_capital_ai_tables,
    format_gp,
    get_recent_ai_suggestions,
    print_capital_summary,
    record_ai_suggestion,
    record_ai_suggestion_outcome,
    record_capital_snapshot,
    record_open_trade_lock,
    score_flip_for_capital,
)


def main() -> int:
    db_path = ensure_capital_ai_tables()
    print("OSRSFlipper 1.2.0 Capital/AI Memory Inspection")
    print("=" * 72)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Database: {db_path}\n")

    account = "inspection_demo"
    record_capital_snapshot(10_000_000, account, 500_000, "Inspection demo snapshot")
    record_open_trade_lock("Example locked buy offer", "buy", 1_000, 2_000, account_name=account, notes="Inspection demo lock")
    print_capital_summary(account)

    score = score_flip_for_capital("Fire rune", 5, 6, 1_000_000, account)
    print("\nFire rune 5 -> 6 GP candidate check")
    print("-" * 72)
    print(f"Suggested quantity: {score['suggested_quantity']:,}")
    print(f"Required GP:        {format_gp(score['required_gp'])}")
    print(f"Usable GP:          {format_gp(score['usable_gp'])}")
    print(f"Score:              {score['score']:.1f}/100")
    print(f"OK:                 {score['ok']}")
    for warning in score["warnings"]:
        print(f"- {warning}")

    sid = record_ai_suggestion(
        "Fire rune", 5, 6, score["suggested_quantity"], 1, recommendation_type="quick_flip",
        confidence="low", account_name=account, reason="Inspection demo: low-margin candidate should be penalized.",
        source_context=score,
    )
    record_ai_suggestion_outcome(sid, "stuck", notes="Inspection demo outcome: sat too long at 6 GP.")

    print("\nRecent inspection_demo AI suggestions")
    print("-" * 72)
    for row in get_recent_ai_suggestions(account_name=account, limit=5):
        print(f"#{row['id']} {row['item_name']} {row['suggested_buy_price']} -> {row['suggested_sell_price']} status={row['latest_outcome_status'] or row['status']}")

    print("\nInspection complete. Demo rows use account_name='inspection_demo'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
