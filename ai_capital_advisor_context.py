from __future__ import annotations


def build_capital_aware_advisor_rules(capital_context: str = "") -> str:
    """Build advisory rules that force AI recommendations to respect live GP and GE slot state."""
    if not capital_context:
        return ""

    return f"""
## Capital-Aware Recommendation Rules

Use the RuneLite capital state below as a hard constraint, not just context.

{capital_context}

Hard rules:
- Base new BUY recommendations on usable GP, not raw bank wealth or total wealth.
- Do not recommend a buy quantity that costs more than usable GP.
- If open GE slots are 0, do not recommend new buys; prioritize hold, cancel, reprice, or sell-side recovery.
- If locked buy GP is high, warn that capital is already committed before suggesting more buys.
- If stale or stuck offers exist, mention whether a slot should be freed before starting new flips.
- For 1 GP margin flips, do not call them quick flips unless expected profit per slot is high enough to justify slow fill risk.
- Prefer smaller test quantities when usable GP is limited, slot pressure is high, or the item has low margin.
- When giving quantities, show the approximate GP required and confirm it fits inside usable GP.
""".strip()


def append_capital_context_to_trade_memory(trade_memory: str | None) -> str:
    """Append live RuneLite capital state/rules to the AI Advisor trade memory block."""
    try:
        from capital_dashboard import build_ai_capital_context_text

        capital_context = build_ai_capital_context_text()
    except Exception as exc:
        capital_context = f"Capital-aware RuneLite telemetry unavailable: {exc}"

    capital_rules = build_capital_aware_advisor_rules(capital_context)

    if not capital_rules:
        return trade_memory or ""

    if trade_memory:
        return f"{trade_memory}\n\n{capital_rules}"

    return capital_rules
