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


def build_maintenance_tab():
    return html.Div(
        children=[
            dcc.Download(id="maintenance-download"),

            html.Div(
                className="panel",
                children=[
                    html.Div("Maintenance", className="section-title"),
                    html.Div(
                        "Back up the SQLite database, export account-scoped trade data, import RuneLite now, and safely clean app data.",
                        className="muted-text"
                    ),
                    html.Div(
                        "Exports are saved in C:\\OSRSFlipper\\exports. Database backups are saved in C:\\OSRSFlipper\\backups.",
                        className="muted-text"
                    )
                ]
            ),

            html.Div(
                className="panel",
                children=[
                    html.Div("Health Check", className="section-title"),
                    html.Div(
                        "Runs diagnostics for project files, Python packages, .env/OpenAI setup, account/session, RuneLite file, database tables, logs, and EXE build.",
                        className="muted-text"
                    ),
                    html.Button(
                        "Run Health Check",
                        id="run-health-check-button",
                        n_clicks=0,
                        className="primary-button"
                    ),
                    html.Pre(
                        id="health-check-output",
                        className="log-output",
                        children="No health check has been run yet."
                    )
                ]
            ),

            html.Div(
                className="panel",
                children=[
                    html.Div("Database Tools", className="section-title"),
                    html.Div(
                        "Back up or optimize the SQLite database. Optimize creates a backup first, then runs PRAGMA optimize and VACUUM.",
                        className="muted-text"
                    ),
                    html.Div(
                        className="button-row",
                        children=[
                            html.Button(
                                "Back Up Database",
                                id="backup-database-button",
                                n_clicks=0,
                                className="primary-button"
                            ),
                            html.Button(
                                "Optimize Database",
                                id="optimize-database-button",
                                n_clicks=0,
                                className="secondary-button"
                            )
                            ,
                            html.Button(
                                "Run Database Repair / Migrations",
                                id="run-migrations-button",
                                n_clicks=0,
                                className="secondary-button"
                            )
                        ]
                    )
                ]
            ),

            html.Div(
                className="panel",
                children=[
                    html.Div("RuneLite Import", className="section-title"),
                    html.Div(
                        "Immediately imports the linked OSRSFlipper RuneLite telemetry JSON for the current account. Duplicate trades should be skipped.",
                        className="muted-text"
                    ),
                    html.Button(
                        "Import RuneLite Now",
                        id="import-runelite-now-button",
                        n_clicks=0,
                        className="primary-button"
                    )
                ]
            ),

            html.Div(
                className="panel",
                children=[
                    html.Div("CSV Exports", className="section-title"),
                    html.Div(
                        "Exports completed trades, raw trade events, AI notes, or the latest public scan.",
                        className="muted-text"
                    ),
                    html.Div(
                        className="button-row",
                        children=[
                            html.Button(
                                "Export Completed Trades",
                                id="export-completed-trades-button",
                                n_clicks=0,
                                className="secondary-button"
                            ),
                            html.Button(
                                "Export Trade Events",
                                id="export-trade-events-button",
                                n_clicks=0,
                                className="secondary-button"
                            ),
                            html.Button(
                                "Export AI Notes",
                                id="export-ai-notes-button",
                                n_clicks=0,
                                className="secondary-button"
                            ),
                            html.Button(
                                "Export Latest Scan",
                                id="export-latest-scan-button",
                                n_clicks=0,
                                className="secondary-button"
                            )
                        ]
                    )
                ]
            ),

            html.Div(
                className="panel",
                children=[
                    html.Div("Danger Zone", className="section-title"),
                    html.Div(
                        "These actions are safer than deleting trade history, but they still remove or reset local app data. Type the required confirmation before clicking.",
                        className="muted-text"
                    ),
                    html.Div(
                        className="filter-row",
                        children=[
                            html.Div(
                                className="filter-box",
                                children=[
                                    html.Label("Clear AI notes confirmation"),
                                    dcc.Input(
                                        id="confirm-clear-ai-notes",
                                        type="text",
                                        placeholder="Type CLEAR AI NOTES"
                                    )
                                ]
                            ),
                            html.Div(
                                className="filter-box",
                                children=[
                                    html.Label("Clear logs confirmation"),
                                    dcc.Input(
                                        id="confirm-clear-logs",
                                        type="text",
                                        placeholder="Type CLEAR LOGS"
                                    )
                                ]
                            ),
                            html.Div(
                                className="filter-box",
                                children=[
                                    html.Label("Reset AI advice confirmation"),
                                    dcc.Input(
                                        id="confirm-reset-ai-advice",
                                        type="text",
                                        placeholder="Type RESET AI"
                                    )
                                ]
                            )
                        ]
                    ),
                    html.Div(
                        className="button-row",
                        children=[
                            html.Button(
                                "Clear Current Account AI Notes",
                                id="clear-ai-notes-button",
                                n_clicks=0,
                                className="secondary-button"
                            ),
                            html.Button(
                                "Clear Log Files",
                                id="clear-logs-button",
                                n_clicks=0,
                                className="secondary-button"
                            ),
                            html.Button(
                                "Reset Saved AI Advice",
                                id="reset-ai-advice-button",
                                n_clicks=0,
                                className="secondary-button"
                            )
                        ]
                    )
                ]
            ),

            html.Div(
                className="panel",
                children=[
                    html.Div("Backup / Release Packaging", className="section-title"),
                    html.Div(
                        "Create a private local backup before updates, or package a clean release folder that excludes private database, .env, logs, backups, exports, and runtime session data.",
                        className="muted-text"
                    ),
                    html.Div(
                        className="button-row",
                        children=[
                            html.Button(
                                "Create Private Backup",
                                id="create-private-backup-button",
                                n_clicks=0,
                                className="primary-button"
                            ),
                            html.Button(
                                "Prepare Clean Release Folder",
                                id="prepare-clean-release-button",
                                n_clicks=0,
                                className="secondary-button"
                            ),
                            html.Button(
                                "Test Update Installer Dry Run",
                                id="update-installer-dry-run-button",
                                n_clicks=0,
                                className="secondary-button"
                            )
                        ]
                    ),
                    html.Div(
                        id="backup-release-status",
                        className="status-text",
                        children="No backup or release package has been created yet."
                    )
                ]
            ),

            html.Div(
                className="panel",
                children=[
                    html.Div("Release Candidate Check", className="section-title"),
                    html.Div(
                        "Runs a full readiness check across files, imports, security, database migrations, account setup, RuneLite detection, health check, safety review, and EXE build status.",
                        className="muted-text"
                    ),
                    html.Div(
                        className="button-row",
                        children=[
                            html.Button(
                                "Run Release Check",
                                id="run-release-check-button",
                                n_clicks=0,
                                className="primary-button"
                            )
                        ]
                    ),
                    html.Pre(
                        id="release-check-output",
                        className="log-output",
                        children="No release check has been run yet."
                    )
                ]
            ),

            html.Div(
                id="maintenance-status",
                className="status-text",
                children="No maintenance action has been run yet."
            )
        ]
    )

