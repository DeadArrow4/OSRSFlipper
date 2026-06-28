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


def build_data_health_tab():
    return html.Div(
        className="settings-page data-health-page",
        children=[
            settings_section(
                "Data Health",
                "Review database growth, scanner coverage, recommended indexes, and daily aggregate readiness.",
                children=[
                    html.Div(
                        className="settings-grid settings-grid-3",
                        children=[
                            setting_card(
                                "Daily metrics rebuild days",
                                dcc.Input(
                                    id="daily-metrics-days",
                                    type="number",
                                    min=1,
                                    max=3650,
                                    step=1,
                                    value=120,
                                    className="settings-input",
                                    persistence=True,
                                    persisted_props=["value"],
                                    persistence_type="local",
                                ),
                                "How many recent days to rebuild into daily_item_metrics."
                            ),
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Refresh"),
                                    html.Button(
                                        "Refresh Data Health",
                                        id="refresh-data-health-button",
                                        n_clicks=0,
                                        className="secondary-button"
                                    ),
                                    html.Div("Reload current data health snapshot.", className="setting-help"),
                                ],
                            ),
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Schema / Indexes"),
                                    html.Button(
                                        "Apply Data Schema / Indexes",
                                        id="apply-data-health-schema-button",
                                        n_clicks=0,
                                        className="secondary-button"
                                    ),
                                    html.Div("Creates daily_item_metrics and recommended indexes if missing.", className="setting-help"),
                                ],
                            ),
                        ],
                    ),
                    html.Div(
                        className="settings-action-row",
                        children=[

                            html.Button(
                                "Refresh Stale Metrics",
                                id="refresh-stale-daily-metrics-button",
                                n_clicks=0,
                                className="secondary-button"
                            ),
                            html.Button(
                                "Rebuild Daily Item Metrics",
                                id="rebuild-daily-metrics-button",
                                n_clicks=0,
                                className="primary-button"
                            ),
                            html.Div(
                                id="data-health-status",
                                className="status-text settings-save-status",
                                children="Data Health has not been refreshed yet."
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(id="data-health-cards", className="kpi-grid"),
            settings_section(
                "Largest Tables",
                "Raw table size overview.",
                children=[
                    dash_table.DataTable(
                        id="data-health-tables-table",
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
                "Time Coverage",
                "Shows whether the database has enough history for short-term, 30-day, or monthly trend views.",
                children=[
                    dash_table.DataTable(
                        id="data-health-time-table",
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
                "Recommended Indexes",
                "Indexes keep dashboard history, trend, and aggregation queries fast as scan_results grows.",
                children=[
                    dash_table.DataTable(
                        id="data-health-index-table",
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
                "Daily Item Metrics",
                "Aggregated item/day rows used for future long-term trend views and prediction scoring.",
                children=[
                    dash_table.DataTable(
                        id="data-health-metrics-table",
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
                "Metrics Automation",
                "Shows whether daily_item_metrics is current and provides a safe refresh for stale aggregate data.",
                children=[
                    dash_table.DataTable(
                        id="data-health-automation-table",
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
                "Database Backup",
                "Create and verify a SQLite safety backup before any future cleanup action is added.",
                children=[
                    html.Div(
                        className="settings-grid settings-grid-3",
                        children=[
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Safety Backup"),
                                    html.Button(
                                        "Create Safety Backup",
                                        id="create-database-safety-backup-button",
                                        n_clicks=0,
                                        className="primary-button"
                                    ),
                                    html.Div("Uses SQLite backup API and writes to backups/database.", className="setting-help"),
                                ],
                            ),
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Refresh List"),
                                    html.Button(
                                        "Refresh Backup List",
                                        id="refresh-database-backup-list-button",
                                        n_clicks=0,
                                        className="secondary-button"
                                    ),
                                    html.Div("Shows the newest database backup files.", className="setting-help"),
                                ],
                            ),
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Cleanup Safety"),
                                    html.Div("Required before delete", className="setting-value"),
                                    html.Div("Future cleanup should require a fresh verified backup.", className="setting-help"),
                                ],
                            ),
                        ],
                    ),
                    html.Div(
                        id="database-backup-status",
                        className="status-text settings-save-status",
                        children="No database safety backup action has run yet."
                    ),
                    dash_table.DataTable(
                        id="database-backup-table",
                        data=[],
                        columns=[],
                        page_size=10,
                        sort_action="native",
                        filter_action="native",
                        style_table={"overflowX": "auto"},
                    ),
                ],
            ),

            settings_section(
                "Database Compaction",
                "Preview whether SQLite compaction would reclaim space after guarded cleanup.",
                children=[
                    html.Div(
                        className="settings-grid settings-grid-3",
                        children=[
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Preview"),
                                    html.Button(
                                        "Preview Compact Database",
                                        id="preview-database-compaction-button",
                                        n_clicks=0,
                                        className="secondary-button"
                                    ),
                                    html.Div("Calculates free SQLite pages. Does not run VACUUM.", className="setting-help"),
                                ],
                            ),
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Compaction Action"),
                                    html.Div("Compacted copy enabled", className="setting-value"),
                                    html.Div("Creates a verified compacted copy; live replacement is manual only.", className="setting-help"),
                                ],
                            ),
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Safety"),
                                    html.Div("Backup required later", className="setting-value"),
                                    html.Div("Future compact action should require a fresh safety backup.", className="setting-help"),
                                ],
                            ),
                        ],
                    ),

                    html.Div(
                        className="settings-grid settings-grid-3",
                        children=[
                            setting_card(
                                "Compact confirmation",
                                dcc.Input(
                                    id="database-compaction-confirmation",
                                    type="text",
                                    placeholder="Type COMPACT DATABASE",
                                    value="",
                                    className="settings-input",
                                    persistence=False,
                                ),
                                "Required text: COMPACT DATABASE"
                            ),
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Guarded Compact Copy"),
                                    html.Button(
                                        "Create Compacted Copy",
                                        id="create-compacted-database-copy-button",
                                        n_clicks=0,
                                        className="secondary-button"
                                    ),
                                    html.Div("Requires exact confirmation and a fresh safety backup.", className="setting-help"),
                                ],
                            ),
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Replacement"),
                                    html.Div("Manual only", className="setting-value"),
                                    html.Div("The live database is not replaced while the dashboard is running.", className="setting-help"),
                                ],
                            ),
                        ],
                    ),
                    html.Div(
                        id="database-compaction-status",
                        className="status-text settings-save-status",
                        children="Database compaction preview has not been run yet."
                    ),
                    dash_table.DataTable(
                        id="database-compaction-preview-table",
                        data=[],
                        columns=[],
                        page_size=12,
                        sort_action="native",
                        filter_action="native",
                        style_table={"overflowX": "auto"},
                    ),
                ],
            ),
            settings_section(
                "Retention Safety",
                "Preview raw scan_results cleanup impact before any future deletion feature exists.",
                children=[
                    html.Div(
                        className="settings-grid settings-grid-3",
                        children=[
                            setting_card(
                                "Raw scan retention",
                                dcc.Dropdown(
                                    id="raw-scan-retention-days",
                                    options=[
                                        {"label": "Keep forever", "value": 0},
                                        {"label": "Keep last 120 days", "value": 120},
                                        {"label": "Keep last 90 days", "value": 90},
                                        {"label": "Keep last 60 days", "value": 60},
                                        {"label": "Keep last 30 days", "value": 30},
                                    ],
                                    value=90,
                                    clearable=False,
                                    className="settings-input",
                                    persistence=True,
                                    persisted_props=["value"],
                                    persistence_type="local",
                                ),
                                "Preview only. This does not delete raw scan_results."
                            ),
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Preview"),
                                    html.Button(
                                        "Preview Cleanup",
                                        id="preview-retention-cleanup-button",
                                        n_clicks=0,
                                        className="secondary-button"
                                    ),
                                    html.Div("Shows what would be removed if cleanup is added later.", className="setting-help"),
                                ],
                            ),
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Safety"),
                                    html.Div("Guarded cleanup enabled", className="setting-value"),
                                    html.Div("Delete is blocked unless confirmation and a fresh safety backup are present.", className="setting-help"),
                                ],
                            ),
                        ],
                    ),

                    html.Div(
                        className="settings-grid settings-grid-3",
                        children=[
                            setting_card(
                                "Cleanup confirmation",
                                dcc.Input(
                                    id="retention-cleanup-confirmation",
                                    type="text",
                                    placeholder="Type DELETE OLD SCANS",
                                    value="",
                                    className="settings-input",
                                    persistence=False,
                                ),
                                "Required text: DELETE OLD SCANS"
                            ),
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Guarded Cleanup"),
                                    html.Button(
                                        "Delete Old Raw Scan Rows",
                                        id="run-retention-cleanup-button",
                                        n_clicks=0,
                                        className="secondary-button"
                                    ),
                                    html.Div("Requires preview settings, exact confirmation, and a fresh safety backup.", className="setting-help"),
                                ],
                            ),
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Label("Backup Guard"),
                                    html.Div("Fresh backup required", className="setting-value"),
                                    html.Div("Backup must be 24 hours old or newer.", className="setting-help"),
                                ],
                            ),
                        ],
                    ),
                    html.Div(
                        id="data-retention-preview-status",
                        className="status-text settings-save-status",
                        children="Retention preview has not been run yet."
                    ),
                    dash_table.DataTable(
                        id="data-retention-preview-table",
                        data=[],
                        columns=[],
                        page_size=12,
                        sort_action="native",
                        filter_action="native",
                        style_table={"overflowX": "auto"},
                    ),
                ],
            ),

            settings_section(
                "Maintenance History",
                "Recent database maintenance events such as backups, previews, cleanup, and future compaction actions.",
                children=[
                    html.Div(
                        className="settings-action-row",
                        children=[
                            html.Button(
                                "Refresh Maintenance History",
                                id="refresh-maintenance-history-button",
                                n_clicks=0,
                                className="secondary-button"
                            ),
                            html.Div(
                                id="maintenance-history-status",
                                className="status-text settings-save-status",
                                children="Maintenance history has not been refreshed yet."
                            ),
                        ],
                    ),
                    dash_table.DataTable(
                        id="maintenance-history-table",
                        data=[],
                        columns=[],
                        page_size=10,
                        sort_action="native",
                        filter_action="native",
                        style_table={"overflowX": "auto"},
                    ),
                ],
            ),
            settings_section(
                "Trend Readiness",
                "Shows whether daily aggregates are ready for short-term, 30-day, and monthly trend analysis.",
                children=[
                    dash_table.DataTable(
                        id="data-health-trend-readiness-table",
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
                "Early Trend Signals",
                "Uses daily_item_metrics to rank items with improving margin/score and enough daily observations. This is a signal view, not automatic prediction.",
                children=[
                    dash_table.DataTable(
                        id="data-health-trend-items-table",
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

