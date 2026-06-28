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


def build_ai_panel():
    return html.Div(
        className="panel ai-panel",
        children=[
            html.Div(
                className="ai-header-row",
                children=[
                    html.Div(
                        children=[
                            html.Div("AI Flip Advisor", className="section-title"),
                            html.Div(
                                "Uses the Trade Board, liquidity, fill-time estimates, history, and daily/weekly trend scores.",
                                className="muted-text"
                            )
                        ]
                    ),
                    html.Div(
                        "After pressing Ask AI, results may take up to 5 minutes to appear. The AI now reviews the Trade Board first, then scanner and trade history context.",
                        className="ai-tip"
                    )
                ]
            ),

            html.Div(
                className="ai-control-card",
                children=[
                    html.Div(
                        className="filter-row ai-controls",
                        children=[
                            html.Div(
                                children=[
                                    html.Label("AI Risk Profile"),
                                    dcc.Dropdown(
                                        id="ai-risk-profile",
                                        options=[
                                            {"label": "Low", "value": "low"},
                                            {"label": "Medium", "value": "medium"},
                                            {"label": "High", "value": "high"}
                                        ],
                                        value="medium",
                                        clearable=False
                                    )
                                ],
                                className="filter-box"
                            ),

                            html.Div(
                                children=[
                                    html.Label("Candidate source limit"),
                                    dcc.Dropdown(
                                        id="ai-limit",
                                        options=[
                                            {"label": "30", "value": 30},
                                            {"label": "60", "value": 60},
                                            {"label": "100", "value": 100},
                                            {"label": "150", "value": 150}
                                        ],
                                        value=100,
                                        clearable=False
                                    )
                                ],
                                className="filter-box-small"
                            ),

                            html.Button(
                                "Ask AI",
                                id="generate-ai-button",
                                n_clicks=0,
                                className="primary-button"
                            )
                        ]
                    ),

                    html.Div(
                        id="ai-status",
                        className="status-text",
                        children="AI advice can take up to 5 minutes after pressing Ask AI."
                    )
                ]
            ),

            html.Div(
                className="ai-output-shell",
                children=[
                    dcc.Markdown(
                        id="ai-advice-output",
                        children=read_saved_ai_advice(),
                        className="ai-advice-output"
                    )
                ]
            )
        ]
    )

