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

from .overview import build_latest_table, build_recurring_table


def build_market_item_history_tab():
    return html.Div(
        className="settings-page item-history-panel",
        children=[
            settings_section(
                "Item History",
                "Search for an item to view its raw margin history over time.",
                children=[
                    html.Div(
                        className="item-history-dropdown-card",
                        children=[
                            html.Label("Search item"),
                            dcc.Dropdown(
                                id="market-item-dropdown",
                                options=get_item_options(),
                                placeholder="Search or select an item",
                                clearable=True,
                                searchable=True,
                                className="item-history-dropdown dark-dropdown",
                                persistence=True,
                                persisted_props=["value"],
                                persistence_type="session",
                            ),
                            html.Div(
                                "Start typing an item name, then select it to draw the history graph.",
                                className="item-history-dropdown-help",
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                dcc.Graph(id="item-history-chart"),
                className="panel chart-panel"
            ),
        ],
    )


def build_item_trend_explorer_tab():
    return html.Div(
        className="settings-page item-trend-explorer-page",
        children=[
            settings_section(
                "Item Trend Explorer",
                "Search an item and inspect daily margin, score, volume, and volatility from daily_item_metrics.",
                children=[
                    html.Div(
                        className="settings-grid settings-grid-3",
                        children=[
                            setting_card(
                                "Item search",
                                dcc.Input(
                                    id="item-trend-search-input",
                                    type="text",
                                    placeholder="Example: Abyssal whip",
                                    value="",
                                    className="settings-input",
                                    persistence=True,
                                    persisted_props=["value"],
                                    persistence_type="local",
                                ),
                                "Partial names are accepted. Blank search loads a high-scoring item."
                            ),
                            setting_card(
                                "Days",
                                dcc.Input(
                                    id="item-trend-days-input",
                                    type="number",
                                    min=1,
                                    max=3650,
                                    step=1,
                                    value=90,
                                    className="settings-input",
                                    persistence=True,
                                    persisted_props=["value"],
                                    persistence_type="local",
                                ),
                                "Look back this many days from the newest aggregate date for the item."
                            ),
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Load"),
                                    html.Button(
                                        "Load Item Trend",
                                        id="load-item-trend-button",
                                        n_clicks=0,
                                        className="primary-button"
                                    ),
                                    html.Div("Uses daily_item_metrics, not raw scan_results.", className="setting-help"),
                                ],
                            ),
                        ],
                    ),
                    html.Div(
                        id="item-trend-status",
                        className="status-text settings-save-status",
                        children="Enter an item name and click Load Item Trend."
                    ),
                ],
            ),
            html.Div(id="item-trend-summary-cards", className="kpi-grid"),
            settings_section(
                "Margin Trend",
                "Daily average margin, profit per item, and margin volatility.",
                children=[
                    dcc.Graph(
                        id="item-trend-margin-graph",
                        config={"displayModeBar": True},
                    )
                ],
            ),
            settings_section(
                "Score Trend",
                "Daily recommendation, quick, and overnight score movement.",
                children=[
                    dcc.Graph(
                        id="item-trend-score-graph",
                        config={"displayModeBar": True},
                    )
                ],
            ),
            settings_section(
                "Matched Items",
                "Closest item matches from daily_item_metrics.",
                children=[
                    dash_table.DataTable(
                        id="item-trend-matches-table",
                        data=[],
                        columns=[],
                        page_size=10,
                        sort_action="native",
                        filter_action="native",
                        style_table={"overflowX": "auto"},
                    )
                ],
            ),
            settings_section(
                "Daily Metric Rows",
                "Aggregated daily rows for the selected item.",
                children=[
                    dash_table.DataTable(
                        id="item-trend-history-table",
                        data=[],
                        columns=[],
                        page_size=15,
                        sort_action="native",
                        filter_action="native",
                        style_table={"overflowX": "auto"},
                    )
                ],
            ),
        ],
    )


def build_market_data_tab():
    return html.Div(
        className="settings-page market-data-page",
        children=[
            html.Div(
                className="panel settings-panel",
                children=[
                    html.Div("Market Data", className="section-title"),
                    html.Div(
                        "Scanner result views are grouped here to keep the main dashboard tab row focused on daily workflow.",
                        className="muted-text settings-section-subtitle"
                    ),
                ],
            ),
            dcc.Tabs(
                id="market-data-tabs",
                value="market-latest-flips",
                className="custom-tabs market-data-tabs",
                children=[
                    dcc.Tab(
                        label="Latest Flips",
                        value="market-latest-flips",
                        className="custom-tab",
                        selected_className="custom-tab--selected",
                        children=[build_latest_table()]
                    ),

                    dcc.Tab(
                        label="Item History",
                        value="market-item-history",
                        className="custom-tab",
                        selected_className="custom-tab--selected",
                        children=[build_market_item_history_tab()]
                    ),

                    dcc.Tab(
                        label="Item Trends",
                        value="market-item-trends",
                        className="custom-tab",
                        selected_className="custom-tab--selected",
                        children=[build_item_trend_explorer_tab()]
                    ),
dcc.Tab(
                        label="Recurring Flips",
                        value="market-recurring-flips",
                        className="custom-tab",
                        selected_className="custom-tab--selected",
                        children=[build_recurring_table()]
                    ),
                ],
            ),
        ],
    )

