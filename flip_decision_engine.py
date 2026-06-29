"""Simple front-door flip plan built from deeper OSRSFlipper data."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from capital_dashboard import load_capital_dashboard_state
from dashboard_data import get_trade_board_recommendations
from offer_intents import get_offer_intent
from settings_manager import get_setting


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


def _build_buy_plan(board_rows: list[dict[str, Any]], usable_gp: int, max_rows: int = 8) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for row in board_rows:
        action = str(row.get("Action") or "")
        if action not in {"Buy Now", "Test Small", "Overnight"}:
            continue

        fit_qty = _safe_int(row.get("Fit Qty"))
        fit_cost = _parse_gp(row.get("Fit Cost"))
        fit_profit = _parse_gp(row.get("Fit Profit"))
        requested_cost = _parse_gp(row.get("Capital Needed"))

        if fit_qty <= 0 or fit_cost <= 0:
            continue

        if usable_gp > 0 and fit_cost > usable_gp:
            continue

        wait = _wait_label(action, row.get("Window"), row.get("Fill"))
        out.append(
            {
                "Priority": len(out) + 1,
                "Action": action,
                "Item": row.get("Item", ""),
                "Buy": row.get("Buy", ""),
                "Sell": row.get("Sell", ""),
                "Qty": fit_qty,
                "Use GP": _format_gp(fit_cost),
                "Projected Profit": _format_gp(fit_profit),
                "Wait": wait,
                "ROI": row.get("ROI", ""),
                "Confidence": row.get("Confidence", ""),
                "Why": row.get("Reason", ""),
                "Capital Note": row.get("Capital Note", ""),
                "_fit_cost": fit_cost,
                "_fit_profit": fit_profit,
                "_requested_cost": requested_cost,
            }
        )

        if len(out) >= max_rows:
            break

    return out


def _offer_action(row: dict[str, Any]) -> tuple[str, str, str]:
    intent = get_offer_intent(row)

    if intent and intent.get("intent") == "overnight":
        return (
            "Overnight hold",
            "next day",
            "Marked as an intentional overnight flip. Ignore normal stale-offer warnings until tomorrow.",
        )

    side = str(row.get("Side") or "").lower()
    projected = _parse_gp(row.get("Projected P/L"))
    age = _safe_int(row.get("Age Min"))
    sell_price = _parse_gp(row.get("Sell Price"))
    recommended = _parse_gp(row.get("Recommended Sell"))

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
            return "Lower toward 1h high", "now", "Offer is above current 1h sell reference and aging."
        if recommended and sell_price and sell_price < recommended and age < 45:
            return "Hold or raise sell", "30-90m", "Current offer is below the 1h reference."
        if age >= 180:
            return "Reprice sell", "now", "Sell offer is stale; keep profit but improve fill chance."
        return "Hold sell", "30-120m", "Sell remains profitable after tax."

    return "Review", "now", "Unknown GE offer side."


def _build_offer_plan(capital_rows: list[dict[str, Any]], max_rows: int = 10) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for row in capital_rows:
        action, wait, reason = _offer_action(row)
        out.append(
            {
                "Priority": len(out) + 1,
                "Slot": row.get("Slot", ""),
                "Action": action,
                "Item": row.get("Item", ""),
                "Side": row.get("Side", ""),
                "Qty": row.get("Qty", ""),
                "Intent": "Overnight" if wait == "next day" else "",
                "Buy Price": row.get("Buy Price", ""),
                "Sell Price": row.get("Sell Price", ""),
                "Tax Total": row.get("Tax Total", ""),
                "Projected P/L": row.get("Projected P/L", ""),
                "Wait": wait,
                "Reason": reason,
            }
        )

    out.sort(
        key=lambda item: (
            0 if item["Wait"] == "now" else 1,
            1 if item["Wait"] == "next day" else 0,
            -_parse_gp(item.get("Projected P/L")),
        )
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
    overnight_holds = [row for row in offer_plan if row.get("Wait") == "next day"]
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

    capital_data = load_capital_dashboard_state(import_live=False)
    capital = capital_data.get("capital") or {}
    raw_gp = _safe_int(capital.get("raw_gp_available"))
    usable_gp = _safe_int(capital.get("usable_gp"))
    open_slots = _safe_int(capital.get("open_slots"))
    capital_rows = capital_data.get("rows") or []

    board_df, board_summary = get_trade_board_recommendations(
        limit=60,
        risk_profile=risk_profile,
        minimum_profit=minimum_profit,
        action_filter="all",
        confidence_filter="all",
        fill_filter="all",
    )
    board_rows = board_df.to_dict("records") if hasattr(board_df, "to_dict") else []
    buy_plan = _build_buy_plan(board_rows, usable_gp, max_rows=max_buy_rows)
    offer_plan = _build_offer_plan(capital_rows, max_rows=max_offer_rows)
    notes = _build_notes(capital, buy_plan, offer_plan, board_summary or {})

    projected_offer_pl = sum(_parse_gp(row.get("Projected P/L")) for row in capital_rows)
    next_buy = buy_plan[0] if buy_plan else {}
    immediate_offer = offer_plan[0] if offer_plan and offer_plan[0].get("Wait") == "now" else {}

    if immediate_offer:
        headline = (
            f"Manage current offer first: {immediate_offer.get('Action')} "
            f"{immediate_offer.get('Item')}."
        )
    elif next_buy:
        headline = (
            f"Buy {next_buy.get('Qty')} {next_buy.get('Item')} at {next_buy.get('Buy')} "
            f"and sell around {next_buy.get('Sell')}."
        )
    elif offer_plan:
        headline = f"Manage current offer first: {offer_plan[0].get('Action')} {offer_plan[0].get('Item')}."
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
