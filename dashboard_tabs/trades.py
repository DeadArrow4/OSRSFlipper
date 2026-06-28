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


def build_my_trades_tab():
    return html.Div(
        className="settings-page trades-page",
        children=[
            settings_section(
                "My Trades",
                children=[
                    html.Div(
                        id="trade-account-scope",
                        className="settings-scope-pill"
                    ),
                    html.Div(
                        "Tracks completed FIFO-matched flips and open/unmatched RuneLite trade events.",
                        className="muted-text"
                    )
                ]
            ),

            html.Div(
                className="osrs-hidden-legacy-filters",
                style={"display": "none"},
                children=[
                    html.Details(
                className="ux-collapsible-panel overview-legacy-filters",
                open=False,
                children=[
                    html.Summary("Legacy scanner filters"),
                    settings_section(
                "Trade Refresh",
                "Use this to pull the newest OSRSFlipper RuneLite telemetry JSON into the local database before viewing results.",
                children=[
                    html.Div(
                        className="settings-grid trade-control-grid",
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
                                "The dashboard imports this file before refreshing the tables."
                            ),
                            setting_card(
                                "Refresh interval",
                                html.Div("Every 60 seconds", className="trade-static-value"),
                                "Manual refresh is available below."
                            )
                        ]
                    ),
                    html.Div(
                        className="settings-action-row",
                        children=[
                            html.Button(
                                "Import RuneLite & Refresh Trades",
                                id="refresh-trades-button",
                                n_clicks=0,
                                className="primary-button"
                            ),
                            html.Div(
                                id="trade-import-status",
                                className="status-text settings-save-status",
                                children="Waiting for first refresh."
                            )
                        ]
                    )
                ]
            )
                ],
            )
                ],
            ),

            html.Div(id="trade-kpi-cards", className="kpi-grid"),

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
                "live-ge-offers-table",
                "Current Live GE Offers",
                "Active BUYING and SELLING offers read directly from OSRSFlipper RuneLite telemetry."
            ),
            build_trade_table(
                "completed-trades-table",
                "Completed Matched Flips",
                "Matched buy/sell pairs with realized profit after tax."
            ),
            build_trade_table(
                "open-trades-table",
                "Open / Unmatched Trade Events",
                "Trades that have not been fully matched yet. These may include live or partially matched RuneLite events."
            )
        ]
    )

