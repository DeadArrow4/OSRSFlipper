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


def build_about_tab():
    version = get_version_info()
    scope = get_current_trade_scope()

    about_rows = [
        {"Field": "Application", "Value": version.get("app_name", "OSRSFlipper")},
        {"Field": "Version", "Value": version.get("app_version", "")},
        {"Field": "Channel", "Value": version.get("build_channel", "")},
        {"Field": "Build time", "Value": version.get("build_time", "")},
        {"Field": "Project folder", "Value": str(BASE_DIR)},
        {"Field": "Database", "Value": str(DB_FILE)},
        {"Field": "Current local user", "Value": scope.get("app_username", "")},
        {"Field": "Current RuneLite/OSRS account", "Value": scope.get("osrs_account_name", "")},
    ]

    feature_rows = [
        {"Feature": "Local account login", "Status": "Enabled"},
        {"Feature": "Per-account encrypted OpenAI keys", "Status": "Enabled"},
        {"Feature": "Shared .env OpenAI key fallback", "Status": "Disabled"},
        {"Feature": "AI usage logging", "Status": "Enabled"},
        {"Feature": "Daily AI request limits", "Status": "Enabled"},
        {"Feature": "OSRSFlipper RuneLite telemetry import", "Status": "Enabled"},
        {"Feature": "Trade safety review", "Status": "Enabled"},
        {"Feature": "Health check", "Status": "Enabled"},
        {"Feature": "Database migrations", "Status": "Enabled"},
        {"Feature": "Release candidate check", "Status": "Enabled"},
    ]

    return html.Div(
        children=[
            html.Div(
                className="panel",
                children=[
                    html.Div("About OSRSFlipper", className="section-title"),
                    html.Div(
                        version.get("description", ""),
                        className="muted-text"
                    ),
                    html.Div(
                        get_version_line(),
                        className="status-text"
                    )
                ]
            ),

            html.Div(
                className="panel",
                children=[
                    html.Div("Version / Runtime", className="section-title"),
                    dash_table.DataTable(
                        columns=[
                            {"name": "Field", "id": "Field"},
                            {"name": "Value", "id": "Value"}
                        ],
                        data=about_rows,
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
                    html.Div("Security / Feature Status", className="section-title"),
                    dash_table.DataTable(
                        columns=[
                            {"name": "Feature", "id": "Feature"},
                            {"name": "Status", "id": "Status"}
                        ],
                        data=feature_rows,
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
                    html.Div("Private Data Reminder", className="section-title"),
                    html.Div(
                        "Do not publicly share release_check.txt, health_check.txt, migration_report.txt, or screenshots that show local paths, usernames, account names, or API-key hints.",
                        className="muted-text"
                    ),
                    html.Div(
                        "Never enter your Jagex/OSRS password into OSRSFlipper. The local account password is only for this app.",
                        className="muted-text"
                    )
                ]
            )
        ]
    )

