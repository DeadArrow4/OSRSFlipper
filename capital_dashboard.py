from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from dash import Input, Output, callback_context, dcc, html, dash_table
except Exception:
    import dash_core_components as dcc
    import dash_html_components as html
    import dash_table
    from dash.dependencies import Input, Output
    from dash import callback_context


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


def _offer_rows_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for offer in state.get("active_ge_offers") or []:
        if not isinstance(offer, dict):
            continue

        side = str(offer.get("side") or offer.get("type") or "unknown").lower()
        price = _safe_int(offer.get("price") or offer.get("unit_price"))
        remaining = _offer_remaining(offer)

        rows.append(
            {
                "Slot": offer.get("slot", ""),
                "Item": offer.get("item_name") or offer.get("name") or f"Item {offer.get('item_id', '')}",
                "Side": side.title(),
                "Price": f"{price:,}",
                "Remaining": f"{remaining:,}",
                "Locked GP": f"{price * remaining:,}" if side == "buy" else "",
                "Sell Value": f"{price * remaining:,}" if side == "sell" else "",
                "Age Min": offer.get("offer_age_minutes", ""),
                "State": offer.get("state", ""),
            }
        )

    return rows


def _capital_from_state(state: dict[str, Any]) -> dict[str, Any]:
    inventory_gp = _safe_int(state.get("inventory_gp"))
    include_bank = bool(state.get("include_bank_gp", True))
    bank_gp = _safe_int(state.get("bank_gp")) if include_bank else 0

    locked_buy_gp = 0
    locked_sell_value_gp = 0
    stuck_offers = 0
    offers = [o for o in (state.get("active_ge_offers") or []) if isinstance(o, dict)]

    for offer in offers:
        side = str(offer.get("side") or "unknown").lower()
        price = _safe_int(offer.get("price") or offer.get("unit_price"))
        remaining = _offer_remaining(offer)
        value = price * remaining

        if side == "buy":
            locked_buy_gp += value
            if _safe_int(offer.get("offer_age_minutes")) >= 60:
                stuck_offers += 1
        elif side == "sell":
            locked_sell_value_gp += value
            if _safe_int(offer.get("offer_age_minutes")) >= 180:
                stuck_offers += 1

    raw_gp = _safe_int(state.get("raw_gp_available"), inventory_gp + bank_gp)
    safety_reserve_gp = _safe_int(state.get("safety_reserve_gp"))
    usable_gp = max(0, raw_gp - locked_buy_gp - safety_reserve_gp)
    open_offer_count = len(offers)

    return {
        "account_name": state.get("account_name") or "default",
        "captured_at": state.get("captured_at") or "",
        "payload_kind": state.get("payload_kind") or "",
        "raw_gp_available": raw_gp,
        "inventory_gp": inventory_gp,
        "bank_gp": bank_gp,
        "locked_buy_gp": locked_buy_gp,
        "locked_sell_value_gp": locked_sell_value_gp,
        "safety_reserve_gp": safety_reserve_gp,
        "usable_gp": usable_gp,
        "open_offer_count": open_offer_count,
        "open_slots": max(0, 8 - open_offer_count),
        "stuck_offers": stuck_offers,
    }


def _try_import_runelite_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {"ok": False, "message": f"Telemetry file not found: {state_path}"}

    try:
        from runelite_state_importer import import_runelite_state

        result = import_runelite_state(state_path)
        return {"ok": True, "message": "Imported live RuneLite telemetry.", "result": result}
    except Exception as exc:
        return {"ok": False, "message": f"Import failed: {exc}"}


def load_capital_dashboard_state(import_live: bool = False, state_path: str | Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    path = Path(state_path)
    import_result = _try_import_runelite_state(path) if import_live else {"ok": None, "message": "Live import not requested."}

    state_json = _read_json(path)
    capital = _capital_from_state(state_json)
    rows = _offer_rows_from_state(state_json)

    telemetry_exists = path.exists()
    payload_kind = state_json.get("payload_kind") or capital.get("payload_kind") or "unknown"

    return {
        "ok": telemetry_exists,
        "state_path": str(path),
        "telemetry_exists": telemetry_exists,
        "payload_kind": payload_kind,
        "capital": capital,
        "rows": rows,
        "import_result": import_result,
        "state_json": state_json,
        "loaded_at": _now_text(),
    }


def build_ai_capital_context_text() -> str:
    data = load_capital_dashboard_state(import_live=True)
    capital = data["capital"]

    return "\n".join(
        [
            "Capital-aware RuneLite telemetry:",
            f"- Account: {capital.get('account_name', 'default')}",
            f"- Captured at: {capital.get('captured_at', '')}",
            f"- Raw GP available: {_format_gp(capital.get('raw_gp_available'))}",
            f"- Locked buy GP: {_format_gp(capital.get('locked_buy_gp'))}",
            f"- Locked sell-side value: {_format_gp(capital.get('locked_sell_value_gp'))}",
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
    import_msg = import_result.get("message", "")

    return html.Div(
        [
            html.Div("RuneLite Capital Telemetry", style={"fontWeight": "700"}),
            html.Div(
                f"Telemetry file: {telemetry} | Payload: {data.get('payload_kind')} | Loaded: {data.get('loaded_at')}",
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

    return html.Div(
        [
            _kpi_card("Raw GP", _format_gp(capital.get("raw_gp_available")), "inventory + included bank"),
            _kpi_card("Usable GP", _format_gp(capital.get("usable_gp")), "after locked buys/reserve"),
            _kpi_card("Locked Buy GP", _format_gp(capital.get("locked_buy_gp")), "open buy offers"),
            _kpi_card("Sell-side Value", _format_gp(capital.get("locked_sell_value_gp")), "open sell offers"),
            _kpi_card("Open Slots", str(capital.get("open_slots", 0)), f"{capital.get('open_offer_count', 0)} active offers"),
            _kpi_card("Stuck Offers", str(capital.get("stuck_offers", 0)), "age threshold check"),
        ],
        style={"display": "flex", "flexWrap": "wrap", "gap": "10px", "marginTop": "10px"},
    )


def _table_columns(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    default = ["Slot", "Item", "Side", "Price", "Remaining", "Locked GP", "Sell Value", "Age Min", "State"]
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

        return _status_block(data), _kpi_cards(data), data["rows"], _table_columns(data["rows"])
