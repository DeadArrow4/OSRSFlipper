from __future__ import annotations

from typing import Any

import pandas as pd


DEFAULT_MAX_SINGLE_TRADE_PCT = 35


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except Exception:
        return default


def _format_gp(value: Any) -> str:
    amount = _safe_int(value)

    if abs(amount) >= 1_000_000_000:
        return f"{amount / 1_000_000_000:.2f}B gp"
    if abs(amount) >= 1_000_000:
        return f"{amount / 1_000_000:.2f}M gp"
    if abs(amount) >= 1_000:
        return f"{amount / 1_000:.1f}K gp"

    return f"{amount:,} gp"


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series([0] * len(df), index=df.index, dtype="float64")

    return pd.to_numeric(df[column], errors="coerce").fillna(0)


def load_trade_board_capital_state() -> dict[str, Any]:
    """Read current RuneLite-backed capital state without forcing a DB write."""
    try:
        from capital_dashboard import load_capital_dashboard_state

        data = load_capital_dashboard_state(import_live=False)
        if not data.get("ok"):
            return {
                "available": False,
                "error": data.get("telemetry_problem") or "RuneLite telemetry is not ready.",
                "usable_gp": 0,
                "raw_gp_available": 0,
                "locked_buy_gp": 0,
                "buy_filled_value_gp": 0,
                "locked_sell_value_gp": 0,
                "sell_filled_value_gp": 0,
                "total_ge_value_held_gp": 0,
                "open_slots": 0,
                "stuck_offers": 0,
                "max_single_trade_pct": DEFAULT_MAX_SINGLE_TRADE_PCT,
                "single_trade_cap_gp": 0,
            }

        capital = data.get("capital") or {}
    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
            "usable_gp": 0,
            "raw_gp_available": 0,
            "locked_buy_gp": 0,
            "buy_filled_value_gp": 0,
            "locked_sell_value_gp": 0,
            "sell_filled_value_gp": 0,
            "total_ge_value_held_gp": 0,
            "open_slots": 0,
            "stuck_offers": 0,
            "max_single_trade_pct": DEFAULT_MAX_SINGLE_TRADE_PCT,
            "single_trade_cap_gp": 0,
        }

    try:
        from capital_ai_memory import get_setting

        max_pct = _safe_int(get_setting("max_single_trade_pct_usable_gp", DEFAULT_MAX_SINGLE_TRADE_PCT), DEFAULT_MAX_SINGLE_TRADE_PCT)
    except Exception:
        max_pct = DEFAULT_MAX_SINGLE_TRADE_PCT

    max_pct = max(1, min(max_pct, 100))
    usable_gp = max(0, _safe_int(capital.get("usable_gp")))
    single_trade_cap_gp = max(0, int(usable_gp * (max_pct / 100)))

    return {
        "available": True,
        "account_name": capital.get("account_name", "default"),
        "source": data.get("capital_source", "live_telemetry"),
        "telemetry_ready": bool(data.get("telemetry_ready")),
        "using_last_known": bool(data.get("using_last_known")),
        "usable_gp": usable_gp,
        "raw_gp_available": _safe_int(capital.get("raw_gp_available")),
        "locked_buy_gp": _safe_int(capital.get("locked_buy_gp")),
        "buy_filled_value_gp": _safe_int(capital.get("buy_filled_value_gp")),
        "locked_sell_value_gp": _safe_int(capital.get("locked_sell_value_gp")),
        "sell_filled_value_gp": _safe_int(capital.get("sell_filled_value_gp")),
        "total_ge_value_held_gp": _safe_int(capital.get("total_ge_value_held_gp")),
        "open_slots": _safe_int(capital.get("open_slots")),
        "stuck_offers": _safe_int(capital.get("stuck_offers")),
        "max_single_trade_pct": max_pct,
        "single_trade_cap_gp": single_trade_cap_gp,
    }


def _fit_status_and_note(
    *,
    target_buy: float,
    original_quantity: float,
    capital_needed: float,
    affordable_quantity: int,
    fit_cost: float,
    usable_gp: int,
    single_trade_cap_gp: int,
    open_slots: int,
    state_available: bool,
    state_error: str = "",
) -> tuple[str, str]:
    if not state_available:
        return "Unknown", f"Capital state unavailable: {state_error}" if state_error else "Capital state unavailable."

    if open_slots <= 0:
        return "No Slot", "Open GE slots are 0; free or finish a slot before starting a new buy."

    if usable_gp <= 0:
        return "No GP", "Usable GP is 0 after locked buys and reserve."

    if target_buy <= 0 or original_quantity <= 0:
        return "No Data", "Missing target buy or quantity data."

    if capital_needed <= single_trade_cap_gp and capital_needed <= usable_gp:
        return "Fits", f"Full scanner quantity fits within {_format_gp(single_trade_cap_gp)} per-trade cap."

    if affordable_quantity > 0:
        return "Scale Down", f"Use about {affordable_quantity:,} qty for {_format_gp(fit_cost)} cost."

    return "Too Expensive", f"Needs {_format_gp(capital_needed)}; per-trade cap is {_format_gp(single_trade_cap_gp)}."


def apply_capital_limits_to_trade_board(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Add capital-fit quantity/cost/profit columns to Trade Board candidates.

    This is advisory only. It does not place, cancel, reprice, or automate any OSRS trade.
    """
    out = df.copy()

    default_columns = {
        "Capital Needed Live": 0,
        "Capital Fit": "Unknown",
        "Capital Fit Qty": 0,
        "Capital Fit Cost": 0,
        "Capital Fit Profit": 0,
        "Capital Note": "Capital state not checked.",
    }

    for column, default in default_columns.items():
        if column not in out.columns:
            out[column] = default

    capital_state = load_trade_board_capital_state()

    if out.empty:
        return out, capital_state

    usable_gp = max(0, _safe_int(capital_state.get("usable_gp")))
    single_trade_cap_gp = max(0, _safe_int(capital_state.get("single_trade_cap_gp")))
    open_slots = _safe_int(capital_state.get("open_slots"))
    state_available = bool(capital_state.get("available"))
    state_error = str(capital_state.get("error") or "")

    target_buy = _numeric_series(out, "target_buy").clip(lower=0)
    quantity = _numeric_series(out, "quantity").clip(lower=0)
    profit_per_item = _numeric_series(out, "profit_per_item")

    capital_needed = target_buy * quantity
    out["Capital Needed Live"] = capital_needed.round(0).astype(int)

    fit_quantities: list[int] = []
    fit_costs: list[int] = []
    fit_profits: list[int] = []
    statuses: list[str] = []
    notes: list[str] = []

    for idx in out.index:
        buy_price = _safe_float(target_buy.loc[idx])
        original_qty = _safe_float(quantity.loc[idx])
        needed_gp = _safe_float(capital_needed.loc[idx])
        net_each = _safe_float(profit_per_item.loc[idx])

        if buy_price > 0 and single_trade_cap_gp > 0 and usable_gp > 0 and open_slots > 0:
            affordable_qty = int(min(original_qty, single_trade_cap_gp // buy_price, usable_gp // buy_price))
        else:
            affordable_qty = 0

        fit_cost = int(max(0, affordable_qty * buy_price))
        fit_profit = int(affordable_qty * net_each)

        status, note = _fit_status_and_note(
            target_buy=buy_price,
            original_quantity=original_qty,
            capital_needed=needed_gp,
            affordable_quantity=affordable_qty,
            fit_cost=fit_cost,
            usable_gp=usable_gp,
            single_trade_cap_gp=single_trade_cap_gp,
            open_slots=open_slots,
            state_available=state_available,
            state_error=state_error,
        )

        statuses.append(status)
        notes.append(note)
        fit_quantities.append(affordable_qty)
        fit_costs.append(fit_cost)
        fit_profits.append(fit_profit)

    out["Capital Fit"] = statuses
    out["Capital Fit Qty"] = fit_quantities
    out["Capital Fit Cost"] = fit_costs
    out["Capital Fit Profit"] = fit_profits
    out["Capital Note"] = notes

    return out, capital_state
