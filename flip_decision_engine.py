"""Simple front-door flip plan built from deeper OSRSFlipper data."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from capital_dashboard import load_capital_dashboard_state
from dashboard_data import get_trade_board_recommendations
from market_suggestions import ge_tax_per_item, latest_hour_sell_suggestion
from offer_intents import list_active_offer_intents
from settings_manager import get_setting


OVERNIGHT_BUY_RECHECK_MINUTES = 8 * 60
OVERNIGHT_SELL_RECHECK_MINUTES = 10 * 60
OVERNIGHT_CRITICAL_RECHECK_MINUTES = 24 * 60


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default


def _parse_gp(value: Any) -> int:
    text = str(value or "").strip().replace(",", "").replace("gp", "").strip()

    if not text:
        return 0

    multiplier = 1
    if text[-1:].lower() == "m":
        multiplier = 1_000_000
        text = text[:-1]
    elif text[-1:].lower() == "k":
        multiplier = 1_000
        text = text[:-1]
    elif text[-1:].lower() == "b":
        multiplier = 1_000_000_000
        text = text[:-1]

    try:
        return int(float(text) * multiplier)
    except Exception:
        return 0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace(",", "").strip())
    except Exception:
        return default


def _parse_percent(value: Any) -> float:
    text = str(value or "").strip().replace("%", "").replace(",", "")
    if not text:
        return 0.0

    try:
        return float(text)
    except Exception:
        return 0.0


def _format_gp(value: Any) -> str:
    amount = _safe_int(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)

    if amount >= 1_000_000_000:
        return f"{sign}{amount / 1_000_000_000:.2f}B"
    if amount >= 1_000_000:
        return f"{sign}{amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"{sign}{amount / 1_000:.1f}K"
    return f"{sign}{amount:,}"


def _wait_label(action: str, window: str, fill: str) -> str:
    action = str(action or "").lower()
    window = str(window or "").lower()
    fill = str(fill or "").lower()

    if "overnight" in action or "overnight" in window:
        return "overnight"
    if "5m" in window and "fast" in fill:
        return "15-45m"
    if "1h" in window and "fast" in fill:
        return "30-90m"
    if "moderate" in fill:
        return "1-4h"
    if "thin" in fill:
        return "4-12h"
    if "slow" in fill:
        return "12h+"
    return window or "watch"


def _confidence_note(row: dict[str, Any]) -> str:
    warning = str(row.get("Warning") or "").strip()
    confidence = str(row.get("Confidence") or "").strip()
    fill = str(row.get("Fill") or "").strip()

    if warning and warning != "OK":
        return f"{confidence or 'Check'} confidence; warning: {warning}"

    return f"{confidence or 'Medium'} confidence; {fill.lower() or 'unknown'} fill"


def _candidate_item_key(row: dict[str, Any]) -> str:
    return str(row.get("Item") or "").strip().lower()


def _active_sell_item_keys(capital_rows: list[dict[str, Any]]) -> set[str]:
    item_keys: set[str] = set()

    for row in capital_rows or []:
        side = str(row.get("Side") or "").strip().lower()
        item_key = _candidate_item_key(row)

        if side == "sell" and item_key:
            item_keys.add(item_key)

    return item_keys


def _setting_int_clamped(key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(get_setting(key, default) or default)
    except Exception:
        value = default

    return max(minimum, min(maximum, value))


def _is_overnight_market_row(row: dict[str, Any] | None) -> bool:
    if not row:
        return False

    action = str(row.get("Action") or "").strip().lower()
    wait = str(row.get("Wait") or "").strip().lower()
    reason = str(row.get("Reason") or row.get("Why") or "").strip().lower()

    return "overnight" in action or "overnight" in wait or "overnight" in reason


def _market_rows_by_item(board_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows_by_item: dict[str, dict[str, Any]] = {}

    for row in board_rows:
        key = _candidate_item_key(row)
        if key and key not in rows_by_item:
            rows_by_item[key] = row

    return rows_by_item


def _market_row_for_offer(row: dict[str, Any], market_rows_by_item: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    if not market_rows_by_item:
        return {}

    key = str(row.get("Item") or "").strip().lower()
    return market_rows_by_item.get(key) or {}


def _offer_intent_matches(row: dict[str, Any], intent: dict[str, Any]) -> bool:
    if str(intent.get("intent") or "").lower() != "overnight":
        return False

    item_name = str(row.get("Item") or "").strip().lower()
    side = str(row.get("Side") or "").strip().lower()
    if not item_name or not side:
        return False

    if str(intent.get("normalized_item_name") or "").strip().lower() != item_name:
        return False

    if str(intent.get("side") or "").strip().lower() != side:
        return False

    intent_slot = str(intent.get("slot") or "").strip()
    row_slot = str(row.get("Slot") or "").strip()
    if intent_slot and row_slot and intent_slot != row_slot:
        return False

    intent_price = _safe_int(intent.get("price"))
    row_price = _parse_gp(row.get("Buy Price") if side == "buy" else row.get("Sell Price"))
    if intent_price > 0 and row_price > 0 and intent_price != row_price:
        return False

    return True


def _manual_overnight_intent_for_row(row: dict[str, Any], active_offer_intents: list[dict[str, Any]]) -> dict[str, Any] | None:
    for intent in active_offer_intents:
        if _offer_intent_matches(row, intent):
            return intent

    return None


def _offer_has_overnight_intent(
    row: dict[str, Any],
    market_rows_by_item: dict[str, dict[str, Any]] | None = None,
    active_offer_intents: list[dict[str, Any]] | None = None,
) -> bool:
    if _is_overnight_market_row(_market_row_for_offer(row, market_rows_by_item)):
        return True

    return bool(_manual_overnight_intent_for_row(row, active_offer_intents or []))


def _active_overnight_slot_count(
    capital_rows: list[dict[str, Any]],
    market_rows_by_item: dict[str, dict[str, Any]],
    active_offer_intents: list[dict[str, Any]],
) -> int:
    count = 0

    for row in capital_rows:
        if _offer_has_overnight_intent(row, market_rows_by_item, active_offer_intents):
            count += 1

    return count


def _buy_candidate_score(
    row: dict[str, Any],
    *,
    fit_cost: int,
    fit_profit: int,
    usable_gp: int,
    open_slots: int,
    overnight_slot_target: int,
    active_overnight_slots: int,
    source_rank: int,
) -> float:
    action = str(row.get("Action") or "")
    confidence = str(row.get("Confidence") or "")
    fill = str(row.get("Fill") or "").lower()
    warning = str(row.get("Warning") or "").strip()

    action_score = {
        "Buy Now": 120.0,
        "Test Small": 70.0,
        "Overnight": 35.0,
    }.get(action, 0.0)
    confidence_score = {
        "High": 45.0,
        "Medium": 20.0,
        "Low": -10.0,
    }.get(confidence, 0.0)

    if "fast" in fill:
        fill_score = 28.0
    elif "moderate" in fill:
        fill_score = 12.0
    elif "thin" in fill:
        fill_score = -15.0
    elif "slow" in fill:
        fill_score = -28.0
    else:
        fill_score = 0.0

    score = action_score + confidence_score + fill_score
    score += min(max(_safe_float(row.get("Score")), 0.0), 100.0) * 0.55
    score += min(max(_safe_float(row.get("Liquidity")), 0.0), 100.0) * 0.20
    score += min(max(_parse_percent(row.get("ROI")), 0.0), 20.0) * 2.0
    score += min(max(_parse_gp(row.get("Profit/1M")), 0), 80_000) / 2_500
    score += min(max(fit_profit, 0), 250_000) / 6_000

    if usable_gp > 0 and open_slots > 0:
        usage_ratio = fit_cost / usable_gp
        score += min(max(usage_ratio, 0.0), 0.35) * 90.0

        if usage_ratio < 0.025 and fit_profit < 50_000:
            score -= 18.0
        elif fit_cost >= 500_000 and fit_profit >= 25_000:
            score += 12.0

    if warning and warning.upper() != "OK":
        score -= 35.0

    if action == "Overnight":
        if overnight_slot_target > active_overnight_slots and open_slots > 0:
            score += 105.0
        else:
            score -= 85.0

    # Preserve the board's judgment as a quiet tie-breaker.
    return score - (source_rank * 0.02)


def _live_buy_exit_check(row: dict[str, Any], buy_price: int, quantity: int) -> dict[str, Any]:
    if buy_price <= 0 or quantity <= 0:
        return {"ok": True}

    try:
        suggestion = latest_hour_sell_suggestion(item_name=str(row.get("Item") or ""))
    except Exception:
        suggestion = None

    if not suggestion:
        return {"ok": True}

    live_sell = _safe_int(suggestion.get("recommended_sell"))
    if live_sell <= 0:
        return {"ok": True}

    tax_each = ge_tax_per_item(live_sell)
    profit_each = live_sell - tax_each - buy_price

    return {
        "ok": profit_each > 0,
        "sell": live_sell,
        "tax_each": tax_each,
        "profit_each": profit_each,
        "profit_total": profit_each * quantity,
        "source": suggestion.get("window_name") or "latest hour",
    }


def _build_buy_plan(
    board_rows: list[dict[str, Any]],
    usable_gp: int,
    open_slots: int,
    overnight_slot_target: int,
    active_overnight_slots: int,
    blocked_buy_item_keys: set[str] | None = None,
    max_rows: int = 8,
) -> list[dict[str, Any]]:
    candidates_by_item: dict[str, dict[str, Any]] = {}
    blocked_buy_item_keys = blocked_buy_item_keys or set()

    for source_rank, row in enumerate(board_rows):
        action = str(row.get("Action") or "")
        if action not in {"Buy Now", "Test Small", "Overnight"}:
            continue

        if _candidate_item_key(row) in blocked_buy_item_keys:
            continue

        if action == "Overnight" and (
            overnight_slot_target <= 0 or active_overnight_slots >= overnight_slot_target
        ):
            continue

        fit_qty = _safe_int(row.get("Fit Qty"))
        fit_cost = _parse_gp(row.get("Fit Cost"))
        fit_profit = _parse_gp(row.get("Fit Profit"))
        requested_cost = _parse_gp(row.get("Capital Needed"))

        if fit_qty <= 0 or fit_cost <= 0:
            continue

        if usable_gp > 0 and fit_cost > usable_gp:
            continue

        buy_price = _parse_gp(row.get("Buy"))
        live_exit = {"ok": True} if action == "Overnight" else _live_buy_exit_check(row, buy_price, fit_qty)
        if not live_exit.get("ok", True):
            continue

        live_sell = live_exit.get("sell")
        sell_price = f"{int(live_sell):,}" if live_sell else row.get("Sell", "")
        projected_profit = live_exit.get("profit_total", fit_profit)
        if live_exit.get("sell"):
            why = (
                f"{row.get('Reason', '')} Live sell check: {live_sell:,} sell, "
                f"{live_exit.get('tax_each', 0):,} tax, "
                f"{live_exit.get('profit_each', 0):,} gp/item after tax."
            ).strip()
            roi = f"{((live_exit.get('profit_each', 0) / buy_price) * 100):.2f}%" if buy_price else row.get("ROI", "")
        else:
            why = row.get("Reason", "")
            roi = row.get("ROI", "")

        wait = _wait_label(action, row.get("Window"), row.get("Fill"))
        candidate = {
            "Priority": 0,
            "Action": action,
            "Item": row.get("Item", ""),
            "Buy": row.get("Buy", ""),
            "Sell": sell_price,
            "Qty": fit_qty,
            "Use GP": _format_gp(fit_cost),
            "Projected Profit": _format_gp(projected_profit),
            "Wait": wait,
            "ROI": roi,
            "Confidence": row.get("Confidence", ""),
            "Why": why,
            "Capital Note": row.get("Capital Note", ""),
            "_fit_cost": fit_cost,
            "_fit_profit": projected_profit,
            "_requested_cost": requested_cost,
            "_score": _buy_candidate_score(
                row,
                fit_cost=fit_cost,
                fit_profit=projected_profit,
                usable_gp=usable_gp,
                open_slots=open_slots,
                overnight_slot_target=overnight_slot_target,
                active_overnight_slots=active_overnight_slots,
                source_rank=source_rank,
            ),
        }

        item_key = _candidate_item_key(candidate)
        existing = candidates_by_item.get(item_key)
        if not existing or candidate["_score"] > existing.get("_score", 0):
            candidates_by_item[item_key] = candidate

    out = sorted(candidates_by_item.values(), key=lambda item: item.get("_score", 0), reverse=True)
    out = out[:max_rows]

    for index, row in enumerate(out, start=1):
        row["Priority"] = index

    return out


def _offer_action(
    row: dict[str, Any],
    market_rows_by_item: dict[str, dict[str, Any]] | None = None,
    active_offer_intents: list[dict[str, Any]] | None = None,
) -> tuple[str, str, str]:
    market_row = _market_row_for_offer(row, market_rows_by_item)
    intent = _manual_overnight_intent_for_row(row, active_offer_intents or [])
    is_overnight = bool(intent) or _is_overnight_market_row(market_row)
    side = str(row.get("Side") or "").lower()
    projected = _parse_gp(row.get("Projected P/L"))
    age = _safe_int(row.get("Age Min"))
    buy_price = _parse_gp(row.get("Buy Price"))
    sell_price = _parse_gp(row.get("Sell Price"))
    recommended = _parse_gp(row.get("Recommended Sell")) or _parse_gp(market_row.get("Sell"))
    market_buy = _parse_gp(market_row.get("Buy"))
    state = str(row.get("State") or "").lower()
    remaining_qty = _safe_int(row.get("Remaining Qty"))
    filled_qty = _safe_int(row.get("Filled Qty"))

    if side == "buy" and ("bought" in state or (remaining_qty <= 0 and filled_qty > 0)):
        suggested = str(row.get("Recommended Sell") or row.get("Sell Price") or "").strip()
        if not suggested:
            suggested = _format_gp(recommended or sell_price)
        if is_overnight:
            return (
                "List overnight sell",
                "now",
                f"Overnight buy filled. Collect it, then list around {suggested} and keep overnight patience after listing.",
            )
        return (
            "Collect and sell",
            "now",
            f"Buy filled. Collect it, then list around {suggested} based on latest sell guidance.",
        )

    if is_overnight:
        source_text = "marked overnight" if intent and intent.get("intent") == "overnight" else "auto overnight setup"

        if side == "buy":
            if projected <= 0:
                return "Recheck overnight buy", "now", "Projected margin is no longer positive after tax."

            if age >= OVERNIGHT_BUY_RECHECK_MINUTES:
                if market_buy > 0 and buy_price > 0 and buy_price < market_buy:
                    return (
                        f"Raise overnight buy to {market_buy:,}",
                        "now",
                        f"This {source_text} buy has sat about {max(1, age // 60)}h at {buy_price:,}; latest target buy is {market_buy:,}.",
                    )

                return (
                    "Recheck overnight buy",
                    "now",
                    f"This {source_text} buy has sat about {max(1, age // 60)}h without filling; confirm the buy price still matches the market.",
                )

            return (
                "Let overnight buy sit",
                "overnight",
                f"Using an overnight slot. Recheck after about {OVERNIGHT_BUY_RECHECK_MINUTES // 60}h if it has not filled.",
            )

        if side == "sell":
            if projected < 0:
                return "Review overnight sell", "now", "Current sell price is below known cost after tax."

            if age >= OVERNIGHT_CRITICAL_RECHECK_MINUTES:
                if recommended > 0 and sell_price > recommended:
                    return (
                        f"Lower overnight sell to {recommended:,}",
                        "now",
                        f"This {source_text} sell has sat about {max(1, age // 60)}h; latest 1h sell reference is {recommended:,}.",
                    )

                return (
                    "Reprice overnight sell",
                    "now",
                    f"This {source_text} sell has sat about {max(1, age // 60)}h; refresh the sell price before using the slot again.",
                )

            if age >= OVERNIGHT_SELL_RECHECK_MINUTES and recommended > 0 and sell_price > recommended:
                return (
                    f"Lower overnight sell to {recommended:,}",
                    "now",
                    f"This {source_text} sell is above the latest 1h sell reference after about {max(1, age // 60)}h.",
                )

            return (
                "Let overnight sell sit",
                "overnight",
                f"Using an overnight slot. Recheck after about {OVERNIGHT_SELL_RECHECK_MINUTES // 60}h if it has not sold.",
            )

    if side == "buy":
        if projected <= 0:
            return "Recheck buy", "now", "Projected margin is not positive after tax."
        if age >= 120:
            return "Reprice or cancel buy", "now", "Buy has aged over 2h; free GP if it is not filling."
        if age >= 60:
            return "Watch buy closely", "30-60m", "Aged buy with positive projected margin."
        return "Let buy fill", "30-90m", "Buy price still supports positive projected P/L."

    if side == "sell":
        if projected < 0:
            return "Review sell loss", "now", "Current sell price is below known cost after tax."
        if recommended and sell_price and sell_price > recommended and age >= 60:
            target = f"{recommended:,}"
            current = f"{sell_price:,}"
            return (
                f"Lower sell to {target}",
                "now",
                f"Current sell is {current}, but the latest 1h sell reference is {target} and this offer is aging.",
            )
        if recommended and sell_price and sell_price < recommended and age < 45:
            target = f"{recommended:,}"
            current = f"{sell_price:,}"
            return (
                f"Hold or raise to {target}",
                "30-90m",
                f"Current sell is {current}, below the latest 1h sell reference of {target}.",
            )
        if age >= 180:
            return "Reprice sell", "now", "Sell offer is stale; keep profit but improve fill chance."
        return "Hold sell", "30-120m", "Sell remains profitable after tax."

    return "Review", "now", "Unknown GE offer side."


def _is_passive_overnight_offer(row: dict[str, Any]) -> bool:
    action = str(row.get("Action") or "").strip().lower()
    wait = str(row.get("Wait") or "").strip().lower()
    return action.startswith("let overnight") and wait == "overnight"


def _offer_priority_rank(row: dict[str, Any]) -> tuple[int, int]:
    action = str(row.get("Action") or "").strip().lower()
    wait = str(row.get("Wait") or "").strip().lower()
    projected_pl = _parse_gp(row.get("Projected P/L"))

    if wait == "now":
        return (0, -projected_pl)

    if "watch buy closely" in action:
        return (1, -projected_pl)

    if "hold or raise" in action:
        return (2, -projected_pl)

    if action.startswith("let buy fill"):
        return (3, -projected_pl)

    if action.startswith("hold sell"):
        return (4, -projected_pl)

    if _is_passive_overnight_offer(row):
        return (8, -projected_pl)

    if wait == "overnight":
        return (7, -projected_pl)

    return (5, -projected_pl)


def _build_offer_plan(
    capital_rows: list[dict[str, Any]],
    market_rows_by_item: dict[str, dict[str, Any]],
    active_offer_intents: list[dict[str, Any]],
    max_rows: int = 10,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for row in capital_rows:
        action, wait, reason = _offer_action(row, market_rows_by_item, active_offer_intents)
        out.append(
            {
                "Priority": len(out) + 1,
                "Slot": row.get("Slot", ""),
                "Action": action,
                "Item": row.get("Item", ""),
                "Side": row.get("Side", ""),
                "Qty": row.get("Qty", ""),
                "Buy Price": row.get("Buy Price", ""),
                "Sell Price": row.get("Sell Price", ""),
                "Recommended Sell": row.get("Recommended Sell", ""),
                "Tax Total": row.get("Tax Total", ""),
                "Projected P/L": row.get("Projected P/L", ""),
                "Wait": wait,
                "Reason": reason,
            }
        )

    out.sort(
        key=_offer_priority_rank
    )

    for index, row in enumerate(out, start=1):
        row["Priority"] = index

    return out[:max_rows]


def _build_notes(capital: dict[str, Any], buy_plan: list[dict[str, Any]], offer_plan: list[dict[str, Any]], board_summary: dict[str, Any]) -> list[dict[str, str]]:
    raw_gp = _safe_int(capital.get("raw_gp_available"))
    usable_gp = _safe_int(capital.get("usable_gp"))
    open_slots = _safe_int(capital.get("open_slots"))
    notes: list[dict[str, str]] = []

    if not buy_plan:
        notes.append(
            {
                "Topic": "No immediate buy",
                "Note": "Current raw/usable GP or filters do not support a high-confidence buy from the ranked board.",
            }
        )

    if raw_gp < 100_000:
        notes.append(
            {
                "Topic": "Low raw GP",
                "Note": f"Only {_format_gp(raw_gp)} raw GP is visible. Finish or cancel offers before opening larger flips.",
            }
        )

    if open_slots <= 1:
        notes.append(
            {
                "Topic": "Slot pressure",
                "Note": f"{open_slots}/8 GE slots are free. Prioritize stale or low-profit offers before adding new buys.",
            }
        )

    now_actions = [row for row in offer_plan if row.get("Wait") == "now"]
    overnight_holds = [row for row in offer_plan if row.get("Wait") in {"next day", "overnight"}]
    if now_actions:
        notes.append(
            {
                "Topic": "Current offers first",
                "Note": f"{len(now_actions)} active offer action(s) should be reviewed before spending more GP.",
            }
        )

    if overnight_holds:
        notes.append(
            {
                "Topic": "Overnight holds",
                "Note": f"{len(overnight_holds)} offer(s) are intentionally parked until tomorrow.",
            }
        )

    notes.append(
        {
            "Topic": "Ranked board",
            "Note": (
                f"Latest scan {board_summary.get('latest_run_id', 'n/a')} has "
                f"{board_summary.get('buy_now_count', 0)} Buy Now and "
                f"{board_summary.get('test_small_count', 0)} Test Small candidates after filters."
            ),
        }
    )

    if usable_gp != raw_gp:
        notes.append(
            {
                "Topic": "Budget mode",
                "Note": f"Usable GP is {_format_gp(usable_gp)} from {_format_gp(raw_gp)} raw GP after budget rules.",
            }
        )

    return notes


def build_flip_plan_snapshot(max_buy_rows: int = 8, max_offer_rows: int = 10) -> dict[str, Any]:
    risk_profile = str(get_setting("risk_profile", "medium") or "medium")
    minimum_profit = get_setting("minimum_profit", 50000)
    overnight_slot_target = _setting_int_clamped("overnight_slot_target", 1, 0, 2)

    capital_data = load_capital_dashboard_state(import_live=False)
    capital = capital_data.get("capital") or {}
    raw_gp = _safe_int(capital.get("raw_gp_available"))
    usable_gp = _safe_int(capital.get("usable_gp"))
    open_slots = _safe_int(capital.get("open_slots"))
    capital_rows = capital_data.get("rows") or []
    blocked_buy_item_keys = _active_sell_item_keys(capital_rows)

    board_df, board_summary = get_trade_board_recommendations(
        limit=180,
        risk_profile=risk_profile,
        minimum_profit=minimum_profit,
        action_filter="all",
        confidence_filter="all",
        fill_filter="all",
    )
    board_rows = board_df.to_dict("records") if hasattr(board_df, "to_dict") else []
    market_rows_by_item = _market_rows_by_item(board_rows)
    active_offer_intents = list_active_offer_intents()
    active_overnight_slots = _active_overnight_slot_count(
        capital_rows,
        market_rows_by_item,
        active_offer_intents,
    )
    buy_plan = _build_buy_plan(
        board_rows,
        usable_gp,
        open_slots,
        overnight_slot_target,
        active_overnight_slots,
        blocked_buy_item_keys,
        max_rows=max_buy_rows,
    )
    offer_plan = _build_offer_plan(
        capital_rows,
        market_rows_by_item,
        active_offer_intents,
        max_rows=max_offer_rows,
    )
    notes = _build_notes(capital, buy_plan, offer_plan, board_summary or {})

    projected_offer_pl = sum(_parse_gp(row.get("Projected P/L")) for row in capital_rows)
    next_buy = buy_plan[0] if buy_plan else {}
    immediate_offer = offer_plan[0] if offer_plan and offer_plan[0].get("Wait") == "now" else {}
    priority_offer = {}
    if offer_plan and not _is_passive_overnight_offer(offer_plan[0]):
        priority_offer = offer_plan[0]

    if immediate_offer:
        headline = (
            f"Manage current offer first: {immediate_offer.get('Action')} "
            f"{immediate_offer.get('Item')}."
        )
    elif next_buy:
        if next_buy.get("Action") == "Overnight":
            headline = (
                f"Set overnight buy: {next_buy.get('Qty')} {next_buy.get('Item')} "
                f"at {next_buy.get('Buy')}; sell around {next_buy.get('Sell')} tomorrow."
            )
        else:
            headline = (
                f"Buy {next_buy.get('Qty')} {next_buy.get('Item')} at {next_buy.get('Buy')} "
                f"and sell around {next_buy.get('Sell')}."
            )
    elif priority_offer:
        headline = f"Manage current offer first: {priority_offer.get('Action')} {priority_offer.get('Item')}."
    elif offer_plan:
        headline = "No urgent offer change right now; overnight holds can sit."
    else:
        headline = "No strong action right now; wait for fresh market or telemetry data."

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "status": headline,
        "capital_ready": bool(capital_data.get("ok")),
        "telemetry_ready": bool(capital_data.get("telemetry_ready")),
        "summary": {
            "Raw GP": _format_gp(raw_gp),
            "Usable GP": _format_gp(usable_gp),
            "Free Slots": f"{open_slots}/8",
            "Offer P/L": _format_gp(projected_offer_pl),
            "Next Buy": next_buy.get("Item", "none"),
            "Wait": next_buy.get("Wait", "n/a"),
        },
        "buy_plan": [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in buy_plan
        ],
        "offer_plan": offer_plan,
        "notes": notes,
    }
