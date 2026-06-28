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


def build_status_cards(summary):
    items = []

    for label, value in summary.items():
        items.append(
            html.Div(
                className="kpi-card",
                children=[
                    html.Div(label, className="kpi-label"),
                    html.Div(str(value), className="kpi-value")
                ]
            )
        )

    return items


def build_log_dropdown_options():
    log_files = [
        "dashboard.log",
        "dashboard_error.log",
        "collector.log",
        "collector_error.log",
        "trade_watcher.log",
        "trade_watcher_error.log",
        "control_center.log",
        "control_center_error.log"
    ]

    existing_options = []

    for name in log_files:
        existing_options.append({
            "label": name,
            "value": name
        })

    return existing_options


def build_status_logs_tab():
    return html.Div(
        children=[
            html.Div(
                className="panel",
                children=[
                    html.Div("Status / Logs", className="section-title"),
                    html.Div(
                        "Account-aware app status, last run timestamps, watched RuneLite file, and recent log output.",
                        className="muted-text"
                    )
                ]
            ),

            html.Div(id="status-log-cards", className="kpi-grid"),

            html.Div(
                className="panel",
                children=[
                    html.Div("Log Viewer", className="section-title"),
                    html.Div(
                        className="filter-row",
                        children=[
                            html.Div(
                                className="filter-box",
                                children=[
                                    html.Label("Log file"),
                                    dcc.Dropdown(
                                        id="log-file-select",
                                        options=build_log_dropdown_options(),
                                        value="collector_error.log",
                                        clearable=False
                                    )
                                ]
                            ),
                            html.Div(
                                className="filter-box",
                                children=[
                                    html.Label("Lines"),
                                    dcc.Dropdown(
                                        id="log-line-count",
                                        options=[
                                            {"label": "40", "value": 40},
                                            {"label": "80", "value": 80},
                                            {"label": "150", "value": 150},
                                            {"label": "300", "value": 300}
                                        ],
                                        value=80,
                                        clearable=False
                                    )
                                ]
                            )
                        ]
                    ),
                    html.Pre(
                        id="log-file-output",
                        className="log-output",
                        children="Select a log file."
                    )
                ]
            )
        ]
    )

