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

try:
    from capital_dashboard import build_capital_ai_panel
except Exception:
    build_capital_ai_panel = None


def _build_trade_board_tab_original_120():
    return html.Div(
        className="settings-page trade-board-page",
        children=[
            html.Details(
                className="osrs-tradeboard-settings-drawer",
                open=False,
                children=[
                    html.Summary("Trade Board settings"),
                    html.Div(
                        className="osrs-tradeboard-settings-grid",
                        children=[
                    settings_section(
                                    "Controls",
                                    children=[
                                        html.Div(
                                            className="settings-grid trade-board-control-grid osrs-tradeboard-controls-restored",
                                            children=[
                                                setting_card(
                                                    "Risk profile",
                                                    dcc.Dropdown(
                                                        id="trade-board-risk-profile",
                                                        options=[
                                                            {"label": "Low", "value": "low"},
                                                            {"label": "Medium", "value": "medium"},
                                                            {"label": "High", "value": "high"},
                                                        ],
                                                        value="medium",
                                                        clearable=False,
                                                        className="dark-dropdown",
                                                        persistence=True,
                                                        persisted_props=["value"],
                                                        persistence_type="local",
                                                    ),
                                                    "Low hides medium/high-risk items. Medium allows low/medium. High allows all."
                                                ),
                                                setting_card(
                                                    "Rows",
                                                    dcc.Input(
                                                        id="trade-board-limit",
                                                        type="number",
                                                        min=5,
                                                        max=100,
                                                        step=5,
                                                        value=25,
                                                        placeholder="25",
                                                        className="settings-input",
                                                        persistence=True,
                                                        persisted_props=["value"],
                                                        persistence_type="local",
                                                    ),
                                                    "Maximum recommendations to show."
                                                ),
                                                setting_card(
                                                    "Minimum total profit",
                                                    dcc.Input(
                                                        id="trade-board-min-profit",
                                                        type="number",
                                                        min=0,
                                                        max=1000000000,
                                                        step=10000,
                                                        value=50000,
                                                        placeholder="50000",
                                                        className="settings-input",
                                                        persistence=True,
                                                        persisted_props=["value"],
                                                        persistence_type="local",
                                                    ),
                                                    "Minimum estimated total profit for Buy Now/Test Small recommendations."
                                                ),
                    
                                                setting_card(
                                                    "Action filter",
                                                    dcc.Dropdown(
                                                        id="trade-board-action-filter",
                                                        options=[
                                                            {"label": "All actions", "value": "all"},
                                                            {"label": "Buy Now", "value": "Buy Now"},
                                                            {"label": "Overnight", "value": "Overnight"},
                                                            {"label": "Test Small", "value": "Test Small"},
                                                            {"label": "Avoid / Wait", "value": "Avoid / Wait"},
                                                        ],
                                                        value="all",
                                                        clearable=False,
                                                        className="dark-dropdown",
                                                        persistence=True,
                                                        persisted_props=["value"],
                                                        persistence_type="local",
                                                    ),
                                                    "Show only one action type."
                                                ),
                                                setting_card(
                                                    "Confidence filter",
                                                    dcc.Dropdown(
                                                        id="trade-board-confidence-filter",
                                                        options=[
                                                            {"label": "All confidence levels", "value": "all"},
                                                            {"label": "High", "value": "High"},
                                                            {"label": "Medium", "value": "Medium"},
                                                            {"label": "Low", "value": "Low"},
                                                        ],
                                                        value="all",
                                                        clearable=False,
                                                        className="dark-dropdown",
                                                        persistence=True,
                                                        persisted_props=["value"],
                                                        persistence_type="local",
                                                    ),
                                                    "Show only High, Medium, or Low confidence rows."
                                                ),
                                                setting_card(
                                                    "Fill filter",
                                                    dcc.Dropdown(
                                                        id="trade-board-fill-filter",
                                                        options=[
                                                            {"label": "All fill speeds", "value": "all"},
                                                            {"label": "Fast", "value": "Fast"},
                                                            {"label": "Moderate", "value": "Moderate"},
                                                            {"label": "Thin", "value": "Thin"},
                                                            {"label": "Slow", "value": "Slow"},
                                                        ],
                                                        value="all",
                                                        clearable=False,
                                                        className="dark-dropdown",
                                                        persistence=True,
                                                        persisted_props=["value"],
                                                        persistence_type="local",
                                                    ),
                                                    "Filter by estimated fill quality."
                                                ),
                                            ]
                                        ),
                                        html.Div(
                                            className="settings-action-row",
                                            children=[
                                                html.Button(
                                                    "Refresh Trade Board",
                                                    id="refresh-trade-board-button",
                                                    n_clicks=0,
                                                    className="primary-button"
                                                ),
                                                html.Div(
                                                    id="trade-board-status",
                                                    className="status-text settings-save-status",
                                                    children="Waiting to build Trade Board."
                                                )
                                            ]
                                        )
                                    ]
                                ),
                    settings_section(
                                    "Trade Board",
                                    "Phase 2.1: one stable ranked table from the latest scanner run. Controls persist after refresh.",
                                    children=[
                                        html.Div(
                                            "Use this as a quick local view of the strongest current trade candidates. The board refreshes when you click the button or change the controls.",
                                            className="muted-text"
                                        )
                                    ]
                                ),
                    settings_section(
                                    "Trend Filters",
                                    "Read-only filters for the trend-aware Trade Board columns.",
                                    children=[
                                        html.Div(
                                            className="settings-grid settings-grid-3",
                                            children=[
                                                setting_card(
                                                    "Trend direction",
                                                    dcc.Dropdown(
                                                        id="trade-board-trend-direction-filter",
                                                        options=[
                                                            {"label": "All trend directions", "value": "all"},
                                                            {"label": "Up", "value": "up"},
                                                            {"label": "Flat", "value": "flat"},
                                                            {"label": "Mixed", "value": "mixed"},
                                                            {"label": "Down", "value": "down"},
                                                            {"label": "Building", "value": "building"},
                                                            {"label": "Unavailable", "value": "unavailable"},
                                                        ],
                                                        value="all",
                                                        clearable=False,
                                                        persistence=True,
                                                        persistence_type="local",
                                                        className="settings-dropdown"
                                                    ),
                                                    "Filters the enriched Trend Direction column."
                                                ),
                                                setting_card(
                                                    "Trend confidence",
                                                    dcc.Dropdown(
                                                        id="trade-board-trend-confidence-filter",
                                                        options=[
                                                            {"label": "All trend confidence levels", "value": "all"},
                                                            {"label": "High", "value": "high"},
                                                            {"label": "Medium", "value": "medium"},
                                                            {"label": "Low", "value": "low"},
                                                        ],
                                                        value="all",
                                                        clearable=False,
                                                        persistence=True,
                                                        persistence_type="local",
                                                        className="settings-dropdown"
                                                    ),
                                                    "Filters the enriched Trend Confidence column."
                                                ),
                                                html.Div(
                                                    className="setting-card",
                                                    children=[
                                                        html.Label("Mode"),
                                                        html.Div("Read-only advisory", className="setting-value"),
                                                        html.Div("Trend filters do not change buy/sell/cancel behavior.", className="setting-help"),
                                                    ],
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                    settings_section(
                                    "Trend Boost",
                                    "Optional advisory scoring overlay. Original Trade Board score stays visible.",
                                    children=[
                                        html.Div(
                                            className="settings-grid settings-grid-3",
                                            children=[
                                                setting_card(
                                                    "Trend boost mode",
                                                    dcc.Dropdown(
                                                        id="trade-board-trend-boost-mode",
                                                        options=[
                                                            {"label": "Off", "value": "off"},
                                                            {"label": "Annotate only", "value": "annotate"},
                                                            {"label": "Reorder view", "value": "reorder"},
                                                        ],
                                                        value="off",
                                                        clearable=False,
                                                        persistence=True,
                                                        persistence_type="local",
                                                        className="settings-dropdown"
                                                    ),
                                                    "Annotate adds adjusted-score columns. Reorder sorts the displayed table only."
                                                ),
                                                html.Div(
                                                    className="setting-card",
                                                    children=[
                                                        html.Label("Safety"),
                                                        html.Div("Display only", className="setting-value"),
                                                        html.Div("Trend Boost does not buy, sell, cancel, or reprice.", className="setting-help"),
                                                    ],
                                                ),
                                                html.Div(
                                                    className="setting-card",
                                                    children=[
                                                        html.Label("Scoring"),
                                                        html.Div("Original score preserved", className="setting-value"),
                                                        html.Div("Trend Adjusted Score is an advisory overlay, not a replacement.", className="setting-help"),
                                                    ],
                                                ),
                                            ],
                                        ),
                                    ],
                                )
                        ],
                    ),
                ],
            ),

            html.Div(id="trade-board-kpi-cards", className="kpi-grid"),


            settings_section(
                "Open Slot Actions",
                "Read-only live GE slot guidance from RuneLite lastOffers. This does not place, cancel, or change trades.",
                children=[
                    html.Div(
                        "Use this when GE slots are full or offers look stale. It separates live slot blockers from old unmatched trade history.",
                        className="muted-text"
                    ),
                    html.Div(
                        className="settings-action-row",
                        children=[
                            html.Button(
                                "Refresh Open Slot Actions",
                                id="refresh-slot-actions-button",
                                n_clicks=0,
                                className="secondary-button"
                            ),
                            html.Div(
                                id="slot-actions-status",
                                className="status-text settings-save-status",
                                children="Waiting to build Open Slot Actions."
                            )
                        ]
                    ),
                    html.Div(id="slot-actions-kpi-cards", className="kpi-grid"),
                    build_trade_table(
                        "slot-actions-table",
                        "Open Slot Actions",
                        "Live RuneLite GE slot review. Suggested actions are read-only: Hold, Cancel, Reprice, or Controlled Loss review."
                    )
                ]
            ),

            build_trade_table(
                "trade-board-table",
                "Ranked Trade Recommendations",
                "One-table view. Controls persist after browser refresh. The refresh button updates the status line so you can confirm it fired."
            )
        ]
    )


def build_trade_board_tab(*args, **kwargs):
    """Trade Board wrapper with capital-aware RuneLite state panel."""
    try:
        panel = build_capital_ai_panel() if build_capital_ai_panel else html.Div()
    except Exception as exc:
        panel = html.Div(
            f"Capital-aware panel unavailable: {exc}",
            style={"padding": "10px", "border": "1px solid rgba(255,255,255,0.12)", "borderRadius": "10px"},
        )

    return html.Div([panel, _build_trade_board_tab_original_120(*args, **kwargs)])

