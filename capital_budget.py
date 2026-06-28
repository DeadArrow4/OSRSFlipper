from __future__ import annotations

from typing import Any

from settings_manager import get_setting


DEFAULT_BUDGET_MODE = "live_capped"
BUDGET_MODES = {
    "manual": "Manual cash stack only",
    "live": "Live usable GP when available",
    "live_capped": "Live usable GP capped by manual cash stack",
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return default


def normalize_budget_mode(value: Any) -> str:
    mode = str(value or DEFAULT_BUDGET_MODE).strip().lower()
    if mode not in BUDGET_MODES:
        return DEFAULT_BUDGET_MODE
    return mode


def load_capital_budget_state() -> dict[str, Any]:
    try:
        from capital_trade_board import load_trade_board_capital_state

        state = load_trade_board_capital_state()
        if not isinstance(state, dict):
            return {"available": False, "error": "Capital state returned no data."}
        return state
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def get_effective_cash_stack(manual_cash_stack: int | float | str | None = None) -> dict[str, Any]:
    """Return the collector/scanner budget after applying live capital policy.

    The manual cash stack remains a safety cap. Live capital is only used when
    a recent or last-known capital state is available.
    """
    if manual_cash_stack is None:
        manual_cash_stack = get_setting("cash_stack", 10_000_000)

    manual_budget = max(0, _safe_int(manual_cash_stack, 10_000_000))
    mode = normalize_budget_mode(get_setting("capital_budget_mode", DEFAULT_BUDGET_MODE))
    state = load_capital_budget_state()

    if mode == "manual":
        return {
            "cash_stack": manual_budget,
            "manual_cash_stack": manual_budget,
            "mode": mode,
            "source": "manual",
            "capital_available": bool(state.get("available")),
            "capital_state": state,
            "note": "Using manual Cash stack setting.",
        }

    if not state.get("available"):
        return {
            "cash_stack": manual_budget,
            "manual_cash_stack": manual_budget,
            "mode": mode,
            "source": "manual_fallback",
            "capital_available": False,
            "capital_state": state,
            "note": f"Capital unavailable; using manual Cash stack. {state.get('error', '')}".strip(),
        }

    live_usable_gp = max(0, _safe_int(state.get("usable_gp")))

    if mode == "live":
        effective = live_usable_gp
        source = "live_usable_gp"
        note = "Using live/last-known usable GP."
    elif live_usable_gp <= 0 and manual_budget > 0:
        effective = manual_budget
        source = "manual_discovery_live_zero"
        note = (
            "Live/last-known usable GP is 0, so scanner uses manual Cash stack for market discovery. "
            "Trade Board Capital Fit will still block or scale unaffordable buys."
        )
    else:
        effective = min(manual_budget, live_usable_gp)
        source = "live_usable_gp_capped"
        note = "Using live/last-known usable GP capped by manual Cash stack."

    return {
        "cash_stack": max(0, int(effective)),
        "manual_cash_stack": manual_budget,
        "mode": mode,
        "source": source,
        "capital_available": True,
        "capital_state": state,
        "live_usable_gp": live_usable_gp,
        "raw_gp_available": _safe_int(state.get("raw_gp_available")),
        "locked_buy_gp": _safe_int(state.get("locked_buy_gp")),
        "buy_filled_value_gp": _safe_int(state.get("buy_filled_value_gp")),
        "sell_filled_value_gp": _safe_int(state.get("sell_filled_value_gp")),
        "total_ge_value_held_gp": _safe_int(state.get("total_ge_value_held_gp")),
        "open_slots": _safe_int(state.get("open_slots")),
        "note": note,
    }
