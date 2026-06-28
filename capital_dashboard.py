from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from account_context import get_current_osrs_account

try:
    from dash import Input, Output, callback_context, dcc, html, dash_table
except Exception:
    import dash_core_components as dcc
    import dash_html_components as html
    import dash_table
    from dash.dependencies import Input, Output
    from dash import callback_context

from runelite_telemetry_control import build_runelite_telemetry_status


DEFAULT_STATE_PATH = Path("runtime") / "runelite_state.json"


def _now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _format_gp(value: Any) -> str:
    try:
        amount = int(float(value or 0))
    except Exception:
        amount = 0

    if abs(amount) >= 1_000_000_000:
        return f"{amount / 1_000_000_000:.2f}B"
    if abs(amount) >= 1_000_000:
        return f"{amount / 1_000_000:.2f}M"
    if abs(amount) >= 1_000:
        return f"{amount / 1_000:.1f}K"
    return f"{amount:,}"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return default


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    return data if isinstance(data, dict) else {}


def _offer_remaining(offer: dict[str, Any]) -> int:
    direct = offer.get("quantity_remaining") or offer.get("remaining")
    if direct is not None:
        return _safe_int(direct)

    total = _safe_int(offer.get("quantity_total") or offer.get("quantity"))
    filled = _safe_int(offer.get("quantity_filled") or offer.get("filled"))
    return max(0, total - filled)


def _buy_filled_value_gp(offer: dict[str, Any], price: int, filled: int) -> int:
    filled_value = (
        offer.get("filled_buy_value")
        or offer.get("filledBuyValue")
        or offer.get("filled_ge_value")
        or offer.get("filled_market_value")
        or offer.get("filledGeValue")
    )
    if filled_value is not None:
        return _safe_int(filled_value)

    ge_price = _safe_int(offer.get("ge_price") or offer.get("gePrice"))
    if ge_price > 0:
        return ge_price * filled

    spent = offer.get("spent")
    if spent is not None:
        return _safe_int(spent)

    return price * filled


def _sell_filled_value_gp(offer: dict[str, Any], price: int, filled: int) -> int:
    filled_value = offer.get("filled_sell_gp") or offer.get("filled_sell_value") or offer.get("filledSellGp")
    if filled_value is not None:
        return _safe_int(filled_value)

    spent = offer.get("spent")
    if spent is not None:
        return _safe_int(spent)

    ge_price = _safe_int(offer.get("ge_price") or offer.get("gePrice"))
    return (ge_price or price) * filled


def _offer_rows_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for offer in state.get("active_ge_offers") or []:
        if not isinstance(offer, dict):
            continue

        side = str(offer.get("side") or offer.get("type") or "unknown").lower()
        price = _safe_int(offer.get("price") or offer.get("unit_price"))
        remaining = _offer_remaining(offer)
        filled = _safe_int(offer.get("quantity_filled") or offer.get("filled"))
        if side == "buy":
            filled_value_gp = _buy_filled_value_gp(offer, price, filled)
        elif side == "sell":
            filled_value_gp = _sell_filled_value_gp(offer, price, filled)
        else:
            filled_value_gp = 0

        rows.append(
            {
                "Slot": offer.get("slot", ""),
                "Item": offer.get("item_name") or offer.get("name") or f"Item {offer.get('item_id', '')}",
                "Side": side.title(),
                "Price": f"{price:,}",
                "Remaining": f"{remaining:,}",
                "Locked GP": f"{price * remaining:,}" if side == "buy" else "",
                "Filled Value": f"{filled_value_gp:,}" if filled > 0 else "",
                "Sell Value": f"{price * remaining:,}" if side == "sell" else "",
                "Age Min": offer.get("offer_age_minutes", ""),
                "State": offer.get("state", ""),
            }
        )

    return rows


def _offer_rows_from_locks(locks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for lock in locks:
        price = _safe_int(lock.get("offer_price"))
        remaining = _safe_int(lock.get("quantity_remaining"))
        filled = _safe_int(lock.get("quantity_filled"))
        side = str(lock.get("side") or "unknown").lower()
        filled_value_gp = price * filled

        rows.append(
            {
                "Slot": lock.get("slot", ""),
                "Item": lock.get("item_name") or f"Item {lock.get('item_id', '')}",
                "Side": side.title(),
                "Price": f"{price:,}",
                "Remaining": f"{remaining:,}",
                "Locked GP": f"{price * remaining:,}" if side == "buy" else "",
                "Filled Value": f"{filled_value_gp:,}" if filled > 0 else "",
                "Sell Value": f"{price * remaining:,}" if side == "sell" else "",
                "Age Min": lock.get("offer_age_minutes", ""),
                "State": lock.get("status", ""),
            }
        )

    return rows


def _capital_from_state(state: dict[str, Any]) -> dict[str, Any]:
    inventory_gp = _safe_int(state.get("inventory_gp"))
    include_bank = bool(state.get("include_bank_gp", True))
    bank_gp = _safe_int(state.get("bank_gp")) if include_bank else 0

    locked_buy_gp = 0
    locked_sell_value_gp = 0
    buy_filled_value_gp = 0
    sell_filled_value_gp = 0
    stuck_offers = 0
    offers = [o for o in (state.get("active_ge_offers") or []) if isinstance(o, dict)]

    for offer in offers:
        side = str(offer.get("side") or "unknown").lower()
        price = _safe_int(offer.get("price") or offer.get("unit_price"))
        filled = _safe_int(offer.get("quantity_filled") or offer.get("filled"))
        remaining = _offer_remaining(offer)
        value = price * remaining

        if side == "buy":
            locked_buy_gp += value
            buy_filled_value_gp += _buy_filled_value_gp(offer, price, filled)
            if _safe_int(offer.get("offer_age_minutes")) >= 60:
                stuck_offers += 1
        elif side == "sell":
            locked_sell_value_gp += value
            sell_filled_value_gp += _sell_filled_value_gp(offer, price, filled)
            if _safe_int(offer.get("offer_age_minutes")) >= 180:
                stuck_offers += 1

    raw_gp = _safe_int(state.get("raw_gp_available"), inventory_gp + bank_gp)
    safety_reserve_gp = _safe_int(state.get("safety_reserve_gp"))
    usable_gp = max(0, raw_gp - safety_reserve_gp)
    total_ge_value_held_gp = locked_buy_gp + buy_filled_value_gp + locked_sell_value_gp + sell_filled_value_gp
    open_offer_count = len(offers)

    return {
        "account_name": state.get("account_name") or "default",
        "captured_at": state.get("captured_at") or "",
        "payload_kind": state.get("payload_kind") or "",
        "raw_gp_available": raw_gp,
        "inventory_gp": inventory_gp,
        "bank_gp": bank_gp,
        "locked_buy_gp": locked_buy_gp,
        "buy_filled_value_gp": buy_filled_value_gp,
        "locked_sell_value_gp": locked_sell_value_gp,
        "sell_filled_value_gp": sell_filled_value_gp,
        "total_ge_value_held_gp": total_ge_value_held_gp,
        "safety_reserve_gp": safety_reserve_gp,
        "usable_gp": usable_gp,
        "open_offer_count": open_offer_count,
        "open_slots": max(0, 8 - open_offer_count),
        "stuck_offers": stuck_offers,
    }


def _capital_from_memory_state(memory: dict[str, Any]) -> dict[str, Any]:
    snapshot = memory.get("snapshot") or {}

    return {
        "account_name": memory.get("account_name") or snapshot.get("account_name") or "default",
        "captured_at": snapshot.get("created_at") or "",
        "payload_kind": "last_known",
        "raw_gp_available": _safe_int(memory.get("raw_gp_available")),
        "inventory_gp": _safe_int(memory.get("inventory_gp")),
        "bank_gp": _safe_int(memory.get("bank_gp")),
        "locked_buy_gp": _safe_int(memory.get("locked_buy_gp")),
        "buy_filled_value_gp": _safe_int(memory.get("buy_filled_value_gp")),
        "locked_sell_value_gp": _safe_int(memory.get("locked_sell_value_gp")),
        "sell_filled_value_gp": _safe_int(memory.get("sell_filled_value_gp")),
        "total_ge_value_held_gp": _safe_int(memory.get("total_tracked_locked_value_gp")),
        "safety_reserve_gp": _safe_int(memory.get("safety_reserve_gp")),
        "usable_gp": _safe_int(memory.get("usable_gp")),
        "open_offer_count": _safe_int(memory.get("open_lock_count")),
        "open_slots": max(0, 8 - _safe_int(memory.get("open_lock_count"))),
        "stuck_offers": sum(
            1
            for lock in memory.get("open_locks", [])
            if str(lock.get("status") or "").lower() == "stuck"
        ),
    }


def _preserve_last_nonzero_gp(capital: dict[str, Any], account_name: str) -> tuple[dict[str, Any], bool, dict[str, Any] | None]:
    if _safe_int(capital.get("raw_gp_available")) > 0:
        return capital, False, None

    try:
        from capital_ai_memory import latest_nonzero_capital_snapshot

        snapshot = latest_nonzero_capital_snapshot(account_name)
    except Exception:
        snapshot = None

    if not snapshot:
        return capital, False, None

    out = dict(capital)
    out["raw_gp_available"] = _safe_int(snapshot.get("raw_gp_available"))
    out["inventory_gp"] = _safe_int(snapshot.get("inventory_gp"))
    out["bank_gp"] = _safe_int(snapshot.get("bank_gp"))
    out["usable_gp"] = max(0, _safe_int(snapshot.get("raw_gp_available")) - _safe_int(out.get("safety_reserve_gp")))
    out["captured_at"] = out.get("captured_at") or snapshot.get("created_at") or ""

    return out, True, snapshot


def _try_import_runelite_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {"ok": False, "message": f"Telemetry file not found: {state_path}"}

    status = build_runelite_telemetry_status(state_path)
    if not status.get("ready"):
        return {"ok": False, "message": f"Import skipped: {status.get('problem') or 'telemetry is not ready'}."}

    try:
        from runelite_state_importer import import_runelite_state

        result = import_runelite_state(state_path)
        return {"ok": True, "message": "Imported live RuneLite telemetry.", "result": result}
    except Exception as exc:
        return {"ok": False, "message": f"Import failed: {exc}"}


def load_capital_dashboard_state(import_live: bool = False, state_path: str | Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    path = Path(state_path)
    import_result = _try_import_runelite_state(path) if import_live else {"ok": None, "message": "Live import not requested."}
    telemetry_status = build_runelite_telemetry_status(path)
    telemetry_ready = bool(telemetry_status.get("ready"))

    state_json = _read_json(path)
    capital_source = "live_telemetry" if telemetry_ready else "unavailable"
    using_last_known = False

    if telemetry_ready:
        capital = _capital_from_state(state_json)
        capital, using_preserved_gp, preserved_snapshot = _preserve_last_nonzero_gp(
            capital,
            str(capital.get("account_name") or get_current_osrs_account() or "default"),
        )
        rows = _offer_rows_from_state(state_json)
        if using_preserved_gp:
            capital_source = "live_telemetry_preserved_gp"
    else:
        using_preserved_gp = False
        preserved_snapshot = None
        telemetry_account = state_json.get("account_name") or telemetry_status.get("account_name")
        account_name = telemetry_account if telemetry_account and telemetry_account != "default" else get_current_osrs_account()
        account_name = account_name or "default"
        try:
            from capital_ai_memory import summarize_capital_state

            memory_state = summarize_capital_state(str(account_name))
            if memory_state.get("snapshot"):
                capital = _capital_from_memory_state(memory_state)
                rows = _offer_rows_from_locks(memory_state.get("open_locks", []))
                capital_source = "last_known"
                using_last_known = True
            else:
                capital = _capital_from_state({})
                rows = []
        except Exception:
            capital = _capital_from_state({})
            rows = []

    telemetry_exists = path.exists()
    payload_kind = telemetry_status.get("payload_kind") or state_json.get("payload_kind") or capital.get("payload_kind") or "unknown"

    return {
        "ok": telemetry_ready or using_last_known,
        "state_path": str(path),
        "telemetry_exists": telemetry_exists,
        "telemetry_ready": telemetry_ready,
        "using_last_known": using_last_known,
        "using_preserved_gp": using_preserved_gp,
        "preserved_snapshot": preserved_snapshot,
        "capital_source": capital_source,
        "telemetry_status": telemetry_status,
        "telemetry_problem": telemetry_status.get("problem", ""),
        "payload_kind": payload_kind,
        "capital": capital,
        "rows": rows,
        "import_result": import_result,
        "state_json": state_json,
        "loaded_at": _now_text(),
    }


def build_ai_capital_context_text() -> str:
    data = load_capital_dashboard_state(import_live=True)
    if not data.get("ok"):
        status = data.get("telemetry_status") or {}
        return "\n".join(
            [
                "Capital-aware RuneLite telemetry not ready:",
                f"- Status: {data.get('telemetry_problem') or 'unknown'}",
                f"- Payload: {data.get('payload_kind', 'unknown')}",
                f"- File: {data.get('state_path', '')}",
                f"- Age seconds: {status.get('age_seconds') if status.get('age_seconds') is not None else 'n/a'}",
                "- Do not treat GP, open slots, or open offers as live capital constraints until a fresh full payload is available.",
            ]
        )

    capital = data["capital"]
    if data.get("using_preserved_gp"):
        source_note = "live telemetry with last nonzero GP preserved"
    else:
        source_note = "live telemetry" if data.get("telemetry_ready") else "last known imported telemetry"

    return "\n".join(
        [
            "Capital-aware RuneLite telemetry:",
            f"- Source: {source_note}",
            f"- Account: {capital.get('account_name', 'default')}",
            f"- Captured at: {capital.get('captured_at', '')}",
            f"- Raw GP available: {_format_gp(capital.get('raw_gp_available'))}",
            f"- Locked buy GP still waiting in GE: {_format_gp(capital.get('locked_buy_gp'))}",
            f"- Filled buy item value held in GE: {_format_gp(capital.get('buy_filled_value_gp'))}",
            f"- Locked sell-side value: {_format_gp(capital.get('locked_sell_value_gp'))}",
            f"- Filled sell GP waiting in GE: {_format_gp(capital.get('sell_filled_value_gp'))}",
            f"- Total GE value held: {_format_gp(capital.get('total_ge_value_held_gp'))}",
            f"- Safety reserve: {_format_gp(capital.get('safety_reserve_gp'))}",
            f"- Usable GP for new buys: {_format_gp(capital.get('usable_gp'))}",
            f"- Open GE offers: {capital.get('open_offer_count', 0)}",
            f"- Open GE slots: {capital.get('open_slots', 0)}",
            f"- Stuck offers: {capital.get('stuck_offers', 0)}",
        ]
    )


def _kpi_card(label: str, value: str, note: str = ""):
    return html.Div(
        [
            html.Div(label, style={"opacity": "0.72", "fontSize": "0.8rem"}),
            html.Div(value, style={"fontSize": "1.35rem", "fontWeight": "700"}),
            html.Div(note, style={"opacity": "0.62", "fontSize": "0.74rem"}) if note else html.Div(),
        ],
        className="capital-ai-kpi-card",
        style={
            "padding": "10px 12px",
            "border": "1px solid rgba(255,255,255,0.12)",
            "borderRadius": "10px",
            "background": "rgba(255,255,255,0.04)",
            "minWidth": "145px",
        },
    )


def _status_block(data: dict[str, Any]):
    capital = data["capital"]
    import_result = data.get("import_result") or {}
    telemetry = "found" if data.get("telemetry_exists") else "missing"
    if data.get("telemetry_ready"):
        readiness = "ready"
        if data.get("using_preserved_gp"):
            readiness += "; preserving last nonzero GP"
    elif data.get("using_last_known"):
        readiness = f"using last known values; live telemetry not ready: {data.get('telemetry_problem') or 'unknown'}"
    else:
        readiness = f"not ready: {data.get('telemetry_problem') or 'unknown'}"
    import_msg = import_result.get("message", "")

    return html.Div(
        [
            html.Div("RuneLite Capital Telemetry", style={"fontWeight": "700"}),
            html.Div(
                f"Telemetry file: {telemetry} | Readiness: {readiness} | Payload: {data.get('payload_kind')} | Loaded: {data.get('loaded_at')}",
                style={"opacity": "0.8", "fontSize": "0.9rem"},
            ),
            html.Div(
                f"Account: {capital.get('account_name', 'default')} | Captured: {capital.get('captured_at', '')}",
                style={"opacity": "0.8", "fontSize": "0.9rem"},
            ),
            html.Div(import_msg, style={"opacity": "0.8", "fontSize": "0.9rem"}) if import_msg else html.Div(),
        ]
    )


def _kpi_cards(data: dict[str, Any]):
    capital = data["capital"]

    if not data.get("ok"):
        note = "waiting for fresh full telemetry"
        return html.Div(
            [
                _kpi_card("Raw GP", "n/a", note),
                _kpi_card("Usable GP", "n/a", note),
                _kpi_card("Locked Buy GP", "n/a", note),
                _kpi_card("Filled Buy Value", "n/a", note),
                _kpi_card("Sell-side Value", "n/a", note),
                _kpi_card("Filled Sell GP", "n/a", note),
                _kpi_card("Total GE Held", "n/a", note),
                _kpi_card("Open Slots", "n/a", note),
                _kpi_card("Stuck Offers", "n/a", note),
            ],
            style={"display": "flex", "flexWrap": "wrap", "gap": "10px", "marginTop": "10px"},
        )

    if data.get("using_preserved_gp"):
        source_note = "preserved last nonzero GP"
    else:
        source_note = "live telemetry" if data.get("telemetry_ready") else "last known import"

    return html.Div(
        [
            _kpi_card("Raw GP", _format_gp(capital.get("raw_gp_available")), f"cash seen by telemetry; {source_note}"),
            _kpi_card("Usable GP", _format_gp(capital.get("usable_gp")), "cash available for new buys after reserve"),
            _kpi_card("Locked Buy GP", _format_gp(capital.get("locked_buy_gp")), "remaining GP waiting in active buy offers"),
            _kpi_card("Filled Buy Value", _format_gp(capital.get("buy_filled_value_gp")), "bought items still held in GE offers"),
            _kpi_card("Sell-side Value", _format_gp(capital.get("locked_sell_value_gp")), "items listed for sale; not spendable GP yet"),
            _kpi_card("Filled Sell GP", _format_gp(capital.get("sell_filled_value_gp")), "sold GP waiting in GE collection"),
            _kpi_card("Total GE Held", _format_gp(capital.get("total_ge_value_held_gp")), "remaining buys + filled buys + sell offers + filled sells"),
            _kpi_card("Open Slots", str(capital.get("open_slots", 0)), f"{capital.get('open_offer_count', 0)} active offers"),
            _kpi_card("Stuck Offers", str(capital.get("stuck_offers", 0)), "age threshold check"),
        ],
        style={"display": "flex", "flexWrap": "wrap", "gap": "10px", "marginTop": "10px"},
    )


def _budget_cards():
    try:
        from capital_budget import BUDGET_MODES, get_effective_cash_stack

        budget = get_effective_cash_stack()
        mode_label = BUDGET_MODES.get(budget.get("mode"), str(budget.get("mode", "unknown")))
        note = budget.get("note", "")

        return html.Div(
            [
                _kpi_card("Budget Mode", mode_label, str(budget.get("source", ""))),
                _kpi_card("Manual Cap", _format_gp(budget.get("manual_cash_stack")), "Cash stack setting"),
                _kpi_card("Live Usable GP", _format_gp(budget.get("live_usable_gp")), "usable capital state"),
                _kpi_card("Effective Scanner Budget", _format_gp(budget.get("cash_stack")), note[:70]),
            ],
            style={"display": "flex", "flexWrap": "wrap", "gap": "10px", "marginTop": "10px"},
        )
    except Exception as exc:
        return html.Div(
            f"Budget source unavailable: {exc}",
            style={"opacity": "0.75", "fontSize": "0.9rem", "marginTop": "10px"},
        )


def _table_columns(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    default = ["Slot", "Item", "Side", "Price", "Remaining", "Locked GP", "Filled Value", "Sell Value", "Age Min", "State"]
    columns = list(rows[0].keys()) if rows else default
    return [{"name": col, "id": col} for col in columns]


def build_capital_ai_panel():
    initial = load_capital_dashboard_state(import_live=False)

    return html.Div(
        [
            dcc.Interval(id="capital-ai-refresh-interval", interval=30_000, n_intervals=0),
            html.Div(
                [
                    html.Div(
                        [
                            html.H3("Capital-Aware RuneLite State", style={"margin": "0"}),
                            html.Div(
                                "Live GP, locked GE offers, usable capital, and open slots for AI recommendations.",
                                style={"opacity": "0.75", "fontSize": "0.92rem"},
                            ),
                        ],
                        style={"flex": "1"},
                    ),
                    html.Div(
                        [
                            html.Button("Import RuneLite Now", id="capital-ai-import-btn", n_clicks=0),
                            html.Button("Refresh View", id="capital-ai-refresh-btn", n_clicks=0, style={"marginLeft": "8px"}),
                        ],
                        style={"whiteSpace": "nowrap"},
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "gap": "12px", "marginBottom": "10px"},
            ),
            html.Div(id="capital-ai-status", children=_status_block(initial)),
            html.Div(id="capital-ai-kpi-cards", children=_kpi_cards(initial)),
            html.Div(id="capital-ai-budget-cards", children=_budget_cards()),
            html.Div(
                [
                    html.H4("Open GE Offers / Capital Locks", style={"marginBottom": "8px"}),
                    dash_table.DataTable(
                        id="capital-ai-locks-table",
                        data=initial["rows"],
                        columns=_table_columns(initial["rows"]),
                        page_size=8,
                        sort_action="native",
                        style_table={"overflowX": "auto"},
                        style_cell={
                            "textAlign": "left",
                            "padding": "6px",
                            "fontFamily": "Arial, sans-serif",
                            "fontSize": "13px",
                        },
                    ),
                ],
                style={"marginTop": "14px"},
            ),
        ],
        className="capital-ai-panel",
        style={
            "padding": "14px",
            "margin": "10px 0 14px 0",
            "border": "1px solid rgba(255,255,255,0.14)",
            "borderRadius": "14px",
            "background": "rgba(0,0,0,0.18)",
        },
    )


def register_capital_ai_callbacks(app):
    if app is None:
        return

    @app.callback(
        Output("capital-ai-status", "children"),
        Output("capital-ai-kpi-cards", "children"),
        Output("capital-ai-budget-cards", "children"),
        Output("capital-ai-locks-table", "data"),
        Output("capital-ai-locks-table", "columns"),
        Input("capital-ai-refresh-btn", "n_clicks"),
        Input("capital-ai-import-btn", "n_clicks"),
        Input("capital-ai-refresh-interval", "n_intervals"),
    )
    def _update_capital_ai_panel(refresh_clicks, import_clicks, interval_ticks):
        triggered = ""
        try:
            triggered = callback_context.triggered[0]["prop_id"].split(".")[0]
        except Exception:
            triggered = ""

        import_live = triggered in {"capital-ai-import-btn", "capital-ai-refresh-interval"}
        data = load_capital_dashboard_state(import_live=import_live)

        return _status_block(data), _kpi_cards(data), _budget_cards(), data["rows"], _table_columns(data["rows"])
