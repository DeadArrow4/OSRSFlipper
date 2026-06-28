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


def build_filters():
    return html.Div(
        className="panel sticky-panel",
        children=[
            html.Div("Filters", className="section-title"),

            html.Div(
                className="osrs-hidden-legacy-top-filters",
                style={"display": "none"},
                children=[
                    html.Div(
                className="osrs-hidden-legacy-filters",
                style={"display": "none"},
                children=[
                    html.Div(
                className="filter-row",
                children=[
                    html.Div(
                        children=[
                            html.Label("Window"),
                            dcc.Dropdown(
                                id="window-filter",
                                options=[
                                    {"label": "All", "value": "all"},
                                    {"label": "5 minute", "value": "5m"},
                                    {"label": "1 hour", "value": "1h"}
                                ],
                                value="all",
                                clearable=False
                            )
                        ],
                        className="filter-box"
                    ),

                    html.Div(
                        children=[
                            html.Label("Result Type"),
                            dcc.Dropdown(
                                id="result-type-filter",
                                options=[
                                    {"label": "Profitable only", "value": "profitable"},
                                    {"label": "Watchlist only", "value": "watchlist"},
                                    {"label": "All saved rows", "value": "all"}
                                ],
                                value="all",
                                clearable=False
                            )
                        ],
                        className="filter-box"
                    ),

                    html.Div(
                        children=[
                            html.Label("Flip Category"),
                            dcc.Dropdown(
                                id="category-filter",
                                options=[
                                    {"label": "Balanced view", "value": "all"},
                                    {"label": "Quick Flip", "value": "Quick Flip"},
                                    {"label": "Overnight qualified", "value": "overnight_qualified"},
                                    {"label": "Watch / Test First", "value": "Watch / Test First"},
                                    {"label": "Avoid", "value": "Avoid"}
                                ],
                                value="all",
                                clearable=False
                            )
                        ],
                        className="filter-box"
                    ),

                    html.Div(
                        children=[
                            html.Label("Signal"),
                            dcc.Dropdown(
                                id="signal-filter",
                                options=[
                                    {"label": "All", "value": "all"},
                                    {"label": "Strong margin spike", "value": "Strong margin spike"},
                                    {"label": "Above average", "value": "Above average"},
                                    {"label": "Normal", "value": "Normal"},
                                    {"label": "Below average", "value": "Below average"},
                                    {"label": "New / Not enough history", "value": "New / Not enough history"},
                                    {"label": "Watch only", "value": "Watch only"}
                                ],
                                value="all",
                                clearable=False
                            )
                        ],
                        className="filter-box"
                    ),

                    html.Div(
                        children=[
                            html.Label("Trend"),
                            dcc.Dropdown(
                                id="trend-filter",
                                options=[
                                    {"label": "All", "value": "all"},
                                    {"label": "Trend OK", "value": "ok"},
                                    {"label": "Warnings only", "value": "warnings"}
                                ],
                                value="all",
                                clearable=False
                            )
                        ],
                        className="filter-box"
                    ),

                    html.Div(
                        children=[
                            html.Label("Top rows"),
                            dcc.Dropdown(
                                id="limit-filter",
                                options=[
                                    {"label": "10", "value": 10},
                                    {"label": "25", "value": 25},
                                    {"label": "50", "value": 50},
                                    {"label": "100", "value": 100},
                                    {"label": "150", "value": 150}
                                ],
                                value=50,
                                clearable=False
                            )
                        ],
                        className="filter-box-small"
                    ),                ]
            )
                ],
            )
                ],
            )
        ]
    )


def build_latest_table():
    return html.Div(
        className="panel flip-table-panel latest-flips-panel",
        children=[
            html.Div("Latest Flip Candidates", className="section-title"),
            html.Div(
                "Condensed scanner results with the most useful decision columns only. Use the top filters above to narrow by category, trend, result type, and row limit.",
                className="muted-text settings-section-subtitle"
            ),
            compact_flip_table(
                "latest-table",
                page_size=12,
                max_height="620px",
                conditionals=latest_table_conditional_styles()
            )
        ]
    )


def build_item_history_tab():
    return html.Div(
        children=[
            html.Div(
                className="panel item-history-panel",
                children=[
                    html.Div("Item History", className="section-title"),
                    html.Div(
                        "Search for an item and view its historical raw margin, scan windows, ROI, trend behavior, and scanner context.",
                        className="muted-text settings-section-subtitle"
                    ),
                    html.Div(
                        className="item-history-dropdown-card",
                        children=[
                            html.Label("Search item history"),
                            dcc.Dropdown(
                                id="item-dropdown",
                                options=get_item_options(),
                                placeholder="Type to search for an item...",
                                clearable=True,
                                searchable=True,
                                className="item-history-dropdown"
                            ),
                            html.Div(
                                "Select an item to load its margin history chart.",
                                className="muted-text item-history-dropdown-help"
                            )
                        ]
                    )
                ]
            ),
            html.Div(
                dcc.Graph(id="item-history-chart"),
                className="panel chart-panel"
            )
        ]
    )


def build_recurring_table():
    recurring_conditionals = [
        {"if": {"column_id": "Item"}, "fontWeight": "900", "minWidth": "180px"},
        {"if": {"column_id": "Appearances"}, "fontWeight": "900"},
        {"if": {"column_id": "Avg Score"}, "fontWeight": "900"},
        {"if": {"column_id": "Avg Profit"}, "fontWeight": "900"},
        {"if": {"column_id": "Avg ROI %"}, "fontWeight": "900"},
    ]

    return html.Div(
        className="panel flip-table-panel recurring-flips-panel",
        children=[
            html.Div("Recurring Flip Candidates", className="section-title"),
            html.Div(
                "Items that repeatedly appear as profitable candidates across scan history. Shows 2+ appearances first, then falls back to best historical candidates if your database is still small.",
                className="muted-text settings-section-subtitle"
            ),
            compact_flip_table(
                "recurring-table",
                page_size=12,
                max_height="560px",
                conditionals=recurring_conditionals
            )
        ]
    )

