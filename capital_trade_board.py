from __future__ import annotations

import sqlite3
from datetime import datetime, time, timezone
from typing import Any

import pandas as pd

from account_context import BASE_DIR, get_account_scope


DEFAULT_MAX_SINGLE_TRADE_PCT = 35
DB_FILE = BASE_DIR / "osrs_flip_scanner.db"
SQLITE_TIMEOUT_SECONDS = 3
SQLITE_BUSY_TIMEOUT_MS = 3000


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


def _normalize_item_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series([0] * len(df), index=df.index, dtype="float64")

    return pd.to_numeric(df[column], errors="coerce").fillna(0)


def _local_day_start_utc_iso() -> str:
    local_now = datetime.now().astimezone()
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=local_now.tzinfo)
    return local_start.astimezone(timezone.utc).isoformat()


def _load_today_buy_quantities() -> dict[str, int]:
    if not DB_FILE.exists():
        return {}

    scope = get_account_scope()
    start_utc = _local_day_start_utc_iso()
    totals: dict[str, int] = {}
    conn = None

    try:
        conn = sqlite3.connect(DB_FILE, timeout=SQLITE_TIMEOUT_SECONDS)
        conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        rows = conn.execute(
            """
            SELECT
                item_id,
                item_name,
                COALESCE(SUM(quantity), 0) AS bought_qty
            FROM trade_events
            WHERE app_username = ?
              AND osrs_account_name = ?
              AND side = 'BUY'
              AND traded_at >= ?
            GROUP BY item_id, LOWER(item_name)
            """,
            (scope["app_username"], scope["osrs_account_name"], start_utc),
        ).fetchall()
    except Exception:
        return {}
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

    for item_id, item_name, bought_qty in rows:
        qty = _safe_int(bought_qty)
        if qty <= 0:
            continue

        if item_id not in (None, ""):
            totals[f"id:{_safe_int(item_id)}"] = max(totals.get(f"id:{_safe_int(item_id)}", 0), qty)

        normalized = _normalize_item_name(item_name)
        if normalized:
            totals[f"name:{normalized}"] = max(totals.get(f"name:{normalized}", 0), qty)

    return totals


def _today_bought_for_row(row: pd.Series, today_buys: dict[str, int]) -> int:
    item_id = _safe_int(row.get("item_id"))
    if item_id > 0:
        value = today_buys.get(f"id:{item_id}")
        if value is not None:
            return value

    return today_buys.get(f"name:{_normalize_item_name(row.get('item_name'))}", 0)


def _active_offer_keys(item_id: Any, item_name: Any) -> list[str]:
    keys: list[str] = []
    item_id_value = _safe_int(item_id)
    if item_id_value > 0:
        keys.append(f"id:{item_id_value}")

    normalized = _normalize_item_name(item_name)
    if normalized:
        keys.append(f"name:{normalized}")

    return keys


def _active_buy_offer_lookup(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}

    for row in rows:
        if str(row.get("Side") or "").strip().lower() != "buy":
            continue

        if _safe_int(row.get("Remaining Qty")) <= 0:
            continue

        info = {
            "slot": row.get("Slot", ""),
            "item": row.get("Item", ""),
            "qty": _safe_int(row.get("Remaining Qty")),
            "price": row.get("Buy Price", ""),
            "state": row.get("State", ""),
        }

        for key in _active_offer_keys(row.get("Item ID"), row.get("Item")):
            active[key] = info

    return active


def _active_buy_for_row(row: pd.Series, active_buys: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for key in _active_offer_keys(row.get("item_id"), row.get("item_name")):
        if key in active_buys:
            return active_buys[key]

    return None


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
                "active_buy_offers": {},
            }

        capital = data.get("capital") or {}
        active_buy_offers = _active_buy_offer_lookup(data.get("rows") or [])
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
            "active_buy_offers": {},
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
        "active_buy_offers": active_buy_offers,
    }


def _fit_status_and_note(
    *,
    target_buy: float,
    original_quantity: float,
    limit_adjusted_quantity: float,
    capital_needed: float,
    affordable_quantity: int,
    fit_cost: float,
    usable_gp: int,
    single_trade_cap_gp: int,
    open_slots: int,
    buy_limit: int,
    daily_limit_used: int,
    daily_limit_remaining: int,
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

    limit_note = ""
    if buy_limit > 0:
        limit_note = (
            f" Daily buy limit: {daily_limit_used:,}/{buy_limit:,} used; "
            f"{max(0, daily_limit_remaining):,} left today."
        )

    if buy_limit > 0 and daily_limit_remaining <= 0:
        return "Limit Reached", f"Buy limit reached for today.{limit_note}"

    adjusted_capital_needed = target_buy * limit_adjusted_quantity
    if adjusted_capital_needed <= single_trade_cap_gp and adjusted_capital_needed <= usable_gp:
        if limit_adjusted_quantity < original_quantity:
            return "Limit Capped", f"Use up to {int(limit_adjusted_quantity):,} qty after today's buy-limit use.{limit_note}"
        return "Fits", f"Full scanner quantity fits within {_format_gp(single_trade_cap_gp)} per-trade cap.{limit_note}"

    if affordable_quantity > 0:
        return "Scale Down", f"Use about {affordable_quantity:,} qty for {_format_gp(fit_cost)} cost.{limit_note}"

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
        "Daily Limit Used": 0,
        "Daily Limit Remaining": 0,
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
    active_buy_offers = capital_state.get("active_buy_offers") or {}

    target_buy = _numeric_series(out, "target_buy").clip(lower=0)
    quantity = _numeric_series(out, "quantity").clip(lower=0)
    profit_per_item = _numeric_series(out, "profit_per_item")
    buy_limit_series = _numeric_series(out, "buy_limit").clip(lower=0)

    capital_needed = target_buy * quantity
    out["Capital Needed Live"] = capital_needed.round(0).astype(int)
    today_buys = _load_today_buy_quantities()

    fit_quantities: list[int] = []
    fit_costs: list[int] = []
    fit_profits: list[int] = []
    statuses: list[str] = []
    notes: list[str] = []
    daily_limit_used_values: list[int] = []
    daily_limit_remaining_values: list[int] = []

    for idx in out.index:
        row = out.loc[idx]
        buy_price = _safe_float(target_buy.loc[idx])
        original_qty = _safe_float(quantity.loc[idx])
        needed_gp = _safe_float(capital_needed.loc[idx])
        net_each = _safe_float(profit_per_item.loc[idx])
        buy_limit = _safe_int(buy_limit_series.loc[idx])
        daily_limit_used = _today_bought_for_row(row, today_buys) if buy_limit > 0 else 0
        daily_limit_remaining = max(0, buy_limit - daily_limit_used) if buy_limit > 0 else int(original_qty)
        limit_adjusted_qty = min(original_qty, daily_limit_remaining) if buy_limit > 0 else original_qty
        active_buy = _active_buy_for_row(row, active_buy_offers)

        if active_buy:
            active_qty = _safe_int(active_buy.get("qty"))
            active_price = str(active_buy.get("price") or "").strip()
            slot = str(active_buy.get("slot") or "").strip()
            slot_text = f" in slot {slot}" if slot else ""
            price_text = f" at {active_price}" if active_price else ""
            limit_text = ""
            if buy_limit > 0:
                limit_text = f" Daily buy limit: {daily_limit_used:,}/{buy_limit:,} used; {daily_limit_remaining:,} left today."

            statuses.append("Active Buy")
            notes.append(
                f"Already buying {active_qty:,} {active_buy.get('item') or row.get('item_name')}{price_text}{slot_text}. "
                f"Manage the current offer instead of opening a duplicate.{limit_text}"
            )
            fit_quantities.append(0)
            fit_costs.append(0)
            fit_profits.append(0)
            daily_limit_used_values.append(daily_limit_used)
            daily_limit_remaining_values.append(daily_limit_remaining)
            continue

        if buy_price > 0 and single_trade_cap_gp > 0 and usable_gp > 0 and open_slots > 0 and limit_adjusted_qty > 0:
            affordable_qty = int(min(limit_adjusted_qty, single_trade_cap_gp // buy_price, usable_gp // buy_price))
        else:
            affordable_qty = 0

        fit_cost = int(max(0, affordable_qty * buy_price))
        fit_profit = int(affordable_qty * net_each)

        status, note = _fit_status_and_note(
            target_buy=buy_price,
            original_quantity=original_qty,
            limit_adjusted_quantity=limit_adjusted_qty,
            capital_needed=needed_gp,
            affordable_quantity=affordable_qty,
            fit_cost=fit_cost,
            usable_gp=usable_gp,
            single_trade_cap_gp=single_trade_cap_gp,
            open_slots=open_slots,
            buy_limit=buy_limit,
            daily_limit_used=daily_limit_used,
            daily_limit_remaining=daily_limit_remaining,
            state_available=state_available,
            state_error=state_error,
        )

        statuses.append(status)
        notes.append(note)
        fit_quantities.append(affordable_qty)
        fit_costs.append(fit_cost)
        fit_profits.append(fit_profit)
        daily_limit_used_values.append(daily_limit_used)
        daily_limit_remaining_values.append(daily_limit_remaining)

    out["Capital Fit"] = statuses
    out["Capital Fit Qty"] = fit_quantities
    out["Capital Fit Cost"] = fit_costs
    out["Capital Fit Profit"] = fit_profits
    out["Capital Note"] = notes
    out["Daily Limit Used"] = daily_limit_used_values
    out["Daily Limit Remaining"] = daily_limit_remaining_values

    if "Action" in out.columns:
        out.loc[out["Capital Fit"] == "Active Buy", "Action"] = "Active Buy"

    return out, capital_state
