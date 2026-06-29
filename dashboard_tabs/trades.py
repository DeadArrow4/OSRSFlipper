"""Shared Dash layout dependencies for OSRSFlipper tab builders."""
from dash import html, dcc, dash_table

from account_manager import get_current_session
from app_version import get_version_info, get_version_line
from openai_key_manager import get_api_key_status
from openai_usage_manager import get_ai_usage_summary
from settings_manager import ensure_default_settings, get_setting, DEFAULT_SETTINGS

from dashboard_components import (
    build_trade_table,
    compact_flip_table,
    latest_table_conditional_styles,
    setting_card,
    setting_select,
    setting_text_box,
    settings_input,
    settings_section,
)
from dashboard_data import (
    BASE_DIR,
    DB_FILE,
    get_account_manager_rows,
    get_current_trade_scope,
    get_item_options,
    read_saved_ai_advice,
    setting_value,
)
from dashboard_theme import base_table_styles


def _build_trade_refresh_section(title="My Trades", subtitle=None):
    return settings_section(
        title,
        subtitle or "Live offers and open/unmatched trade events from local RuneLite telemetry.",
        children=[
            html.Div(
                id="trade-account-scope",
                className="settings-scope-pill"
            ),
            html.Div(
                className="settings-grid settings-grid-3 trade-control-grid",
                children=[
                    setting_card(
                        "Rows to show",
                        setting_text_box(
                            "my-trades-limit",
                            100,
                            "100"
                        ),
                        "Applies to completed and open trade tables."
                    ),
                    setting_card(
                        "Live import source",
                        html.Div("OSRSFlipper RuneLite telemetry JSON", className="trade-static-value"),
                        "The dashboard imports this local file before refreshing the tables."
                    ),
                    html.Div(
                        className="setting-card",
                        children=[
                            html.Div("Refresh", className="settings-card-label"),
                            html.Button(
                                "Import RuneLite & Refresh Trades",
                                id="refresh-trades-button",
                                n_clicks=0,
                                className="secondary-button"
                            ),
                            html.Div("Manual refresh is available here; auto-refresh still runs every minute.", className="settings-card-help"),
                        ],
                    ),
                ],
            ),
            html.Div(
                id="trade-import-status",
                className="status-text settings-save-status",
                children="Waiting for first refresh."
            )
        ]
    )


def build_current_trades_tab():
    return html.Div(
        className="settings-page trades-page",
        children=[
            _build_trade_refresh_section(
                "My Trades",
                "Current live GE offers plus open and unmatched trade events."
            ),
            html.Div(id="trade-kpi-cards", className="kpi-grid"),

            build_trade_table(
                "live-ge-offers-table",
                "Current Live GE Offers",
                "Active BUYING and SELLING offers read directly from OSRSFlipper RuneLite telemetry."
            ),
            build_trade_table(
                "open-trades-table",
                "Open / Unmatched Trade Events",
                "Trades that have not been fully matched yet. These may include live or partially matched RuneLite events."
            )
        ]
    )


def build_trade_history_tab():
    return html.Div(
        className="settings-page trades-history-page",
        children=[
            settings_section(
                "Trade History",
                "All previous RuneLite trade transactions with matched-profit charts for realized flips.",
                children=[
                    html.Div(
                        "Buy rows include the latest scanner sell target when OSRSFlipper can estimate one.",
                        className="muted-text",
                    )
                ],
            ),
            html.Div(
                className="chart-grid",
                children=[
                    html.Div(
                        dcc.Graph(id="trade-profit-chart"),
                        className="panel chart-panel"
                    ),
                    html.Div(
                        dcc.Graph(id="trade-item-profit-chart"),
                        className="panel chart-panel"
                    )
                ]
            ),
            build_trade_table(
                "completed-trades-table",
                "Transaction History",
                "All imported buy/sell trade events. Buy rows include recommended sell and estimated net where scanner data exists."
            )
        ]
    )


def build_my_trades_tab():
    """Compatibility layout for the older standalone My Trades tab."""
    return html.Div(
        className="trades-combined-page",
        children=[
            build_current_trades_tab(),
            build_trade_history_tab(),
        ],
    )

