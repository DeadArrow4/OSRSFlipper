from __future__ import annotations

from inspection_path import PROJECT_ROOT
from ai_capital_advisor_context import append_capital_context_to_trade_memory


def main() -> int:
    print("OSRSFlipper 1.2.0 AI Capital Context Inspection")
    print("=" * 72)

    advisor_path = PROJECT_ROOT / "advisor.py"
    helper_path = PROJECT_ROOT / "ai_capital_advisor_context.py"

    advisor_text = advisor_path.read_text(encoding="utf-8", errors="ignore")
    helper_text = helper_path.read_text(encoding="utf-8", errors="ignore")

    checks = {
        "advisor import": "from ai_capital_advisor_context import append_capital_context_to_trade_memory" in advisor_text,
        "generate_ai_advice injection": "trade_memory = append_capital_context_to_trade_memory(trade_memory)" in advisor_text,
        "helper exists": helper_path.exists(),
        "usable GP rule": "Base new BUY recommendations on usable GP" in helper_text,
        "open slot rule": "If open GE slots are 0" in helper_text,
    }

    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}: {name}")

    print()
    print("Preview appended memory:")
    print(append_capital_context_to_trade_memory("Existing trade memory placeholder."))

    if not all(checks.values()):
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
