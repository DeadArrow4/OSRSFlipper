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


def build_setup_tab():
    return html.Div(
        children=[
            html.Div(
                className="panel",
                children=[
                    html.Div("Setup Wizard", className="section-title"),
                    html.Div(
                        "Use this page to confirm whether this OSRSFlipper account is ready. Full account creation still runs through the control center setup wizard.",
                        className="muted-text"
                    ),
                    html.Div(
                        "To run the full wizard manually: python first_run_setup.py",
                        className="muted-text"
                    )
                ]
            ),

            html.Div(
                className="panel",
                children=[
                    html.Div("Setup Checklist", className="section-title"),
                    dash_table.DataTable(
                        id="setup-checklist-table",
                        columns=[
                            {"name": "Step", "id": "Step"},
                            {"name": "Status", "id": "Status"},
                            {"name": "Details", "id": "Details"}
                        ],
                        data=[],
                        page_size=20,
                        style_table={"overflowX": "auto"},
                        style_cell={
                            "textAlign": "left",
                            "padding": "8px",
                            "whiteSpace": "normal",
                            "height": "auto"
                        }
                    )
                ]
            ),

            html.Div(
                className="panel",
                children=[
                    html.Div("OpenAI API Key Quick Setup", className="section-title"),
                    html.Div(
                        "Paste the current user's OpenAI API key here to save it encrypted for this account.",
                        className="muted-text"
                    ),
                    html.Div(
                        className="filter-row",
                        children=[
                            html.Div(
                                className="filter-box",
                                children=[
                                    html.Label("OpenAI API key"),
                                    dcc.Input(
                                        id="setup-openai-api-key",
                                        type="password",
                                        placeholder="sk-...",
                                        value=""
                                    )
                                ]
                            )
                        ]
                    ),
                    html.Button(
                        "Save Encrypted OpenAI Key",
                        id="setup-save-openai-key-button",
                        n_clicks=0,
                        className="primary-button"
                    ),
                    html.Button(
                        "Test OpenAI API Key",
                        id="setup-test-openai-key-button",
                        n_clicks=0,
                        className="secondary-button"
                    ),
                    html.Div(
                        id="setup-api-key-status",
                        className="status-text"
                    ),
                    html.Div(
                        id="setup-api-key-test-status",
                        className="status-text"
                    )
                ]
            ),

            html.Div(
                className="panel",
                children=[
                    html.Div("Quick Settings", className="section-title"),
                    html.Div(
                        className="filter-row",
                        children=[
                            settings_input(
                                "Cash stack",
                                dcc.Input(
                                    id="setup-cash-stack",
                                    type="number",
                                    value=setting_value("cash_stack", 10000000),
                                    min=0,
                                    step=100000
                                )
                            ),
                            settings_input(
                                "Minimum profit",
                                dcc.Input(
                                    id="setup-minimum-profit",
                                    type="number",
                                    value=setting_value("minimum_profit", 50000),
                                    min=0,
                                    step=1000
                                )
                            ),
                            settings_input(
                                "Risk profile",
                                dcc.Dropdown(
                                    id="setup-risk-profile",
                                    options=[
                                        {"label": "Low", "value": "low"},
                                        {"label": "Medium", "value": "medium"},
                                        {"label": "High", "value": "high"}
                                    ],
                                    value=setting_value("risk_profile", "medium"),
                                    clearable=False
                                )
                            ),
                            settings_input(
                                "Max AI requests/day",
                                dcc.Input(
                                    id="setup-max-ai-requests",
                                    type="number",
                                    value=setting_value("max_ai_requests_per_day", 20),
                                    min=0,
                                    step=1
                                )
                            )
                        ]
                    ),
                    html.Button(
                        "Save Quick Settings",
                        id="setup-save-settings-button",
                        n_clicks=0,
                        className="primary-button"
                    ),
                    html.Div(
                        id="setup-settings-status",
                        className="status-text"
                    )
                ]
            )
        ]
    )

