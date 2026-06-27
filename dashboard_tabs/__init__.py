"""
Dash tab and page-layout builders for the OSRSFlipper dashboard.
"""
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
    get_current_trade_scope,
    get_item_options,
    get_account_manager_rows,
    read_saved_ai_advice,
    setting_value,
)
from dashboard_theme import base_table_styles


def build_trade_board_tab():
    return html.Div(
        className="settings-page trade-board-page",
        children=[
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
                "Controls",
                children=[
                    html.Div(
                        className="settings-grid trade-board-control-grid",
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

            settings_section(
                "Trade Refresh",
                "Use this to pull the newest RuneLite Flipping Utilities JSON into the local database before viewing results.",
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
                                html.Div("RuneLite Flipping Utilities JSON", className="trade-static-value"),
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


def build_filters():
    return html.Div(
        className="panel sticky-panel",
        children=[
            html.Div("Filters", className="section-title"),

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
        ]
    )




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
                        "Immediately imports the linked RuneLite Flipping Utilities JSON for the current account. Duplicate trades should be skipped.",
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


def build_safety_review_tab():
    return html.Div(
        className="settings-page safety-review-page",
        children=[
            settings_section(
                "Trade Safety Review",
                children=[
                    html.Div(
                        "A conservative pre-trade checklist for scanner candidates. "
                        "It suggests small test quantities, estimates GE tax impact, checks cash exposure, and flags liquidity/trend risks.",
                        className="muted-text"
                    ),
                    html.Div(
                        "This is not a guarantee of profit. Treat it as a final review before risking GP.",
                        className="settings-scope-pill safety-warning-pill"
                    )
                ]
            ),

            settings_section(
                "Safety Controls",
                "Tune the safety review limits and refresh/export the reviewed candidates.",
                children=[
                    html.Div(
                        className="settings-grid safety-control-grid",
                        children=[
                            setting_card(
                                "Max cash % per item test",
                                setting_text_box(
                                    "safety-max-cash-percent",
                                    setting_value("max_single_item_cash_percent", 10.0),
                                    "10.0"
                                ),
                                "Caps the GP used for a first test buy."
                            ),
                            setting_card(
                                "Max first-test quantity",
                                setting_text_box(
                                    "safety-max-test-quantity",
                                    setting_value("max_test_quantity", 25),
                                    "25"
                                ),
                                "Hard cap for the first test quantity."
                            ),
                            setting_card(
                                "Rows to review",
                                setting_text_box(
                                    "safety-review-limit",
                                    100,
                                    "100"
                                ),
                                "How many candidates to show in the table."
                            )
                        ]
                    ),
                    html.Div(
                        className="settings-action-row",
                        children=[
                            html.Button(
                                "Refresh Safety Review",
                                id="refresh-safety-review-button",
                                n_clicks=0,
                                className="primary-button"
                            ),
                            html.Button(
                                "Export Safety Review CSV",
                                id="export-safety-review-button",
                                n_clicks=0,
                                className="secondary-button"
                            ),
                            html.Div(
                                id="safety-review-status",
                                className="status-text settings-save-status",
                                children="Safety review will refresh automatically."
                            )
                        ]
                    )
                ]
            ),

            dcc.Download(id="safety-review-download"),

            html.Div(
                className="panel settings-panel safety-table-panel",
                children=[
                    html.Div("Reviewed Trade Candidates", className="section-title"),
                    html.Div(
                        "Filter and sort the reviewed candidates below. Verdicts are color-coded from safer test candidates to avoids.",
                        className="muted-text settings-section-subtitle"
                    ),
                    dash_table.DataTable(
                        id="safety-review-table",
                        columns=[],
                        data=[],
                        page_size=25,
                        sort_action="native",
                        filter_action="native",
                        style_table={"overflowX": "auto"},
                        style_cell={
                            "textAlign": "left",
                            "padding": "8px",
                            "whiteSpace": "normal",
                            "height": "auto",
                            "minWidth": "110px",
                            "maxWidth": "260px"
                        },
                        style_data_conditional=[
                            {
                                "if": {"filter_query": "{Safety Verdict} = 'Safer Test'"},
                                "backgroundColor": "rgba(46, 204, 113, 0.14)"
                            },
                            {
                                "if": {"filter_query": "{Safety Verdict} = 'Test First'"},
                                "backgroundColor": "rgba(241, 196, 15, 0.14)"
                            },
                            {
                                "if": {"filter_query": "{Safety Verdict} = 'Watch / Test Tiny'"},
                                "backgroundColor": "rgba(230, 126, 34, 0.14)"
                            },
                            {
                                "if": {"filter_query": "{Safety Verdict} = 'Avoid'"},
                                "backgroundColor": "rgba(231, 76, 60, 0.14)"
                            }
                        ]
                    )
                ]
            )
        ]
    )


def build_account_manager_tab():
    current = get_current_session() or {}

    return html.Div(
        children=[
            html.Div(
                className="panel",
                children=[
                    html.Div("Account Manager", className="section-title"),
                    html.Div(
                        "Create users, switch users, and update the linked RuneLite account. "
                        "After switching users, restart the control center so collector and trade watcher use the same account.",
                        className="muted-text"
                    ),
                    html.Div(
                        id="account-manager-current-user",
                        className="status-text",
                        children=(
                            f"Current session: {current.get('username', 'none')} / "
                            f"{current.get('osrs_account_name', 'none')}"
                        )
                    )
                ]
            ),

            html.Div(
                className="panel",
                children=[
                    html.Div("Users", className="section-title"),
                    dash_table.DataTable(
                        id="account-manager-users-table",
                        columns=[
                            {"name": "Current", "id": "Current"},
                            {"name": "Username", "id": "Username"},
                            {"name": "RuneLite/OSRS Account", "id": "RuneLite/OSRS Account"},
                            {"name": "Created", "id": "Created"},
                            {"name": "Updated", "id": "Updated"},
                            {"name": "Last Login", "id": "Last Login"}
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
                    html.Div("Switch User", className="section-title"),
                    html.Div(
                        "This switches the active dashboard session. Restart the control center afterward for background services.",
                        className="muted-text"
                    ),
                    html.Div(
                        className="filter-row",
                        children=[
                            settings_input(
                                "Username",
                                dcc.Input(
                                    id="account-switch-username",
                                    type="text",
                                    placeholder="local username"
                                )
                            ),
                            settings_input(
                                "Password",
                                dcc.Input(
                                    id="account-switch-password",
                                    type="password",
                                    placeholder="local OSRSFlipper password"
                                )
                            )
                        ]
                    ),
                    html.Button(
                        "Switch User",
                        id="account-switch-button",
                        n_clicks=0,
                        className="primary-button"
                    ),
                    html.Div(
                        id="account-switch-status",
                        className="status-text"
                    )
                ]
            ),

            html.Div(
                className="panel",
                children=[
                    html.Div("Create New User", className="section-title"),
                    html.Div(
                        "This creates a local OSRSFlipper account. Do not use a real Jagex/OSRS password.",
                        className="muted-text"
                    ),
                    html.Div(
                        className="filter-row",
                        children=[
                            settings_input(
                                "New username",
                                dcc.Input(
                                    id="account-create-username",
                                    type="text",
                                    placeholder="new local username"
                                )
                            ),
                            settings_input(
                                "New password",
                                dcc.Input(
                                    id="account-create-password",
                                    type="password",
                                    placeholder="local password"
                                )
                            ),
                            settings_input(
                                "Confirm password",
                                dcc.Input(
                                    id="account-create-confirm-password",
                                    type="password",
                                    placeholder="confirm local password"
                                )
                            ),
                            settings_input(
                                "RuneLite/OSRS account",
                                dcc.Input(
                                    id="account-create-osrs-account",
                                    type="text",
                                    placeholder="for example DeadArrow98"
                                )
                            )
                        ]
                    ),
                    html.Button(
                        "Create User",
                        id="account-create-button",
                        n_clicks=0,
                        className="primary-button"
                    ),
                    html.Div(
                        id="account-create-status",
                        className="status-text"
                    )
                ]
            ),

            html.Div(
                className="panel",
                children=[
                    html.Div("Update Linked RuneLite Account", className="section-title"),
                    html.Div(
                        "Updates the RuneLite/OSRS account name for an existing local user.",
                        className="muted-text"
                    ),
                    html.Div(
                        className="filter-row",
                        children=[
                            settings_input(
                                "Username",
                                dcc.Input(
                                    id="account-update-username",
                                    type="text",
                                    placeholder="local username"
                                )
                            ),
                            settings_input(
                                "New RuneLite/OSRS account",
                                dcc.Input(
                                    id="account-update-osrs-account",
                                    type="text",
                                    placeholder="new linked OSRS account"
                                )
                            )
                        ]
                    ),
                    html.Button(
                        "Update Linked Account",
                        id="account-update-button",
                        n_clicks=0,
                        className="secondary-button"
                    ),
                    html.Div(
                        id="account-update-status",
                        className="status-text"
                    )
                ]
            )
        ]
    )


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
        {"Feature": "RuneLite Flipping Utilities import", "Status": "Enabled"},
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


def build_settings_tab():
    ensure_default_settings()
    scope = get_current_trade_scope()

    boolean_options = [
        {"label": "Enabled", "value": "true"},
        {"label": "Disabled", "value": "false"}
    ]

    risk_options = [
        {"label": "Low", "value": "low"},
        {"label": "Medium", "value": "medium"},
        {"label": "High", "value": "high"}
    ]

    return html.Div(
        className="settings-page",
        children=[
            settings_section(
                "Settings",
                children=[
                    html.Div(
                        f"Local user: {scope['app_username']}  |  OSRS/RuneLite account: {scope['osrs_account_name']}",
                        id="settings-account-scope",
                        className="settings-scope-pill"
                    ),
                    html.Div(
                        "Changes are saved to SQLite. Restart the control center after changing startup options.",
                        className="muted-text"
                    )
                ]
            ),

            settings_section(
                "Startup & Collector",
                "Controls how the control center starts and what scanner values are used by default.",
                children=[
                    html.Div(
                        className="settings-grid",
                        children=[
                            setting_card(
                                "Cash stack",
                                setting_text_box(
                                    "setting-cash-stack",
                                    setting_value("cash_stack", 10000000),
                                    "10000000"
                                ),
                                "Default GP budget used by the collector."
                            ),
                            setting_card(
                                "Minimum profit",
                                setting_text_box(
                                    "setting-minimum-profit",
                                    setting_value("minimum_profit", 50000),
                                    "50000"
                                ),
                                "Minimum total profit target for scan results."
                            ),
                            setting_card(
                                "Risk profile",
                                setting_select(
                                    "setting-risk-profile",
                                    risk_options,
                                    setting_value("risk_profile", "medium")
                                ),
                                "Controls conservative vs aggressive defaults."
                            ),
                            setting_card(
                                "Trade watcher seconds",
                                setting_text_box(
                                    "setting-watch-seconds",
                                    setting_value("watch_seconds", 10),
                                    "10"
                                ),
                                "How often RuneLite trade history is checked."
                            ),
                            setting_card(
                                "Start dashboard",
                                setting_select(
                                    "setting-start-dashboard",
                                    boolean_options,
                                    "true" if setting_value("start_dashboard", True) else "false"
                                )
                            ),
                            setting_card(
                                "Start collector",
                                setting_select(
                                    "setting-start-collector",
                                    boolean_options,
                                    "true" if setting_value("start_collector", True) else "false"
                                )
                            ),
                            setting_card(
                                "Start trade watcher",
                                setting_select(
                                    "setting-start-trade-watcher",
                                    boolean_options,
                                    "true" if setting_value("start_trade_watcher", True) else "false"
                                )
                            ),
                            setting_card(
                                "Open browser",
                                setting_select(
                                    "setting-open-browser",
                                    boolean_options,
                                    "true" if setting_value("open_browser", True) else "false"
                                )
                            )
                        ]
                    ),
                    html.Div(
                        className="settings-action-row",
                        children=[
                            html.Button(
                                "Save Startup Settings",
                                id="save-core-settings-button",
                                n_clicks=0,
                                className="primary-button"
                            ),
                            html.Div(id="core-settings-status", className="status-text settings-save-status")
                        ]
                    )
                ]
            ),

            settings_section(
                "OpenAI API Key",
                "Each local OSRSFlipper account must use its own encrypted OpenAI API key. The full key is never displayed after saving.",
                children=[
                    html.Div(
                        className="settings-status-grid",
                        children=[
                            html.Div(id="openai-key-status", className="settings-status-card"),
                            html.Div(id="openai-usage-status", className="settings-status-card")
                        ]
                    ),
                    html.Div(
                        className="settings-grid settings-grid-2",
                        children=[
                            setting_card(
                                "OpenAI API key",
                                setting_text_box(
                                    "setting-openai-api-key",
                                    "",
                                    "Paste key here, for example sk-...",
                                    password=True
                                ),
                                "Saved encrypted for this local OSRSFlipper account."
                            ),
                            setting_card(
                                "Delete confirmation",
                                setting_text_box(
                                    "confirm-delete-openai-key",
                                    "",
                                    "Type DELETE API KEY"
                                ),
                                "Required before deleting the saved key."
                            )
                        ]
                    ),
                    html.Div(
                        className="settings-action-row",
                        children=[
                            html.Button(
                                "Save OpenAI API Key",
                                id="save-openai-key-button",
                                n_clicks=0,
                                className="primary-button"
                            ),
                            html.Button(
                                "Delete Saved Key",
                                id="delete-openai-key-button",
                                n_clicks=0,
                                className="secondary-button"
                            ),
                            html.Button(
                                "Test OpenAI API Key",
                                id="test-openai-key-button",
                                n_clicks=0,
                                className="secondary-button"
                            )
                        ]
                    ),
                    html.Div(id="openai-key-action-status", className="status-text settings-save-status"),
                    html.Div(id="openai-key-test-status", className="status-text settings-save-status")
                ]
            ),

            settings_section(
                "AI Advisor Rules",
                "Controls how many candidates the advisor reviews and the safety thresholds it applies.",
                children=[
                    html.Div(
                        className="settings-grid",
                        children=[
                            setting_card(
                                "Daily AI request limit",
                                setting_text_box(
                                    "setting-max-ai-requests-per-day",
                                    setting_value("max_ai_requests_per_day", 20),
                                    "20"
                                ),
                                "Set to 0 to disable AI for this account."
                            ),
                            setting_card(
                                "AI source row limit",
                                setting_text_box(
                                    "setting-ai-source-row-limit",
                                    setting_value("ai_source_row_limit", 350),
                                    "350"
                                )
                            ),
                            setting_card(
                                "Quick flip choices",
                                setting_text_box(
                                    "setting-ai-quick-choices",
                                    setting_value("ai_quick_choices", 10),
                                    "10"
                                )
                            ),
                            setting_card(
                                "Overnight choices",
                                setting_text_box(
                                    "setting-ai-overnight-choices",
                                    setting_value("ai_overnight_choices", 10),
                                    "10"
                                )
                            ),
                            setting_card(
                                "Value choices",
                                setting_text_box(
                                    "setting-ai-value-choices",
                                    setting_value("ai_value_choices", 10),
                                    "10"
                                )
                            ),
                            setting_card(
                                "Exclude traded today",
                                setting_select(
                                    "setting-exclude-items-traded-today",
                                    boolean_options,
                                    "true" if setting_value("exclude_items_traded_today", True) else "false"
                                )
                            ),
                            setting_card(
                                "Min overnight raw margin",
                                setting_text_box(
                                    "setting-min-overnight-raw-margin",
                                    setting_value("min_overnight_raw_margin", 10000),
                                    "10000"
                                )
                            ),
                            setting_card(
                                "Min overnight ROI %",
                                setting_text_box(
                                    "setting-min-overnight-roi-percent",
                                    setting_value("min_overnight_roi_percent", 5.0),
                                    "5.0"
                                )
                            ),
                            setting_card(
                                "Small loss-cut %",
                                setting_text_box(
                                    "setting-max-small-loss-percent",
                                    setting_value("max_small_loss_percent", 2.0),
                                    "2.0"
                                )
                            ),
                            setting_card(
                                "Medium loss-cut %",
                                setting_text_box(
                                    "setting-max-medium-loss-percent",
                                    setting_value("max_medium_loss_percent", 5.0),
                                    "5.0"
                                )
                            )
                        ]
                    ),
                    html.Div(
                        className="settings-action-row",
                        children=[
                            html.Button(
                                "Save AI Settings",
                                id="save-ai-settings-button",
                                n_clicks=0,
                                className="primary-button"
                            ),
                            html.Div(id="ai-settings-status", className="status-text settings-save-status")
                        ]
                    )
                ]
            )
        ]
    )


def build_app_layout():
    return html.Div(
        className="app-shell",
        children=[
            html.Div(
                className="top-bar",
                children=[
                    html.Div(
                        children=[
                            html.Div("OSRS Grand Exchange Flip Dashboard", className="app-title"),
                            html.Div(
                                "Live scanner, SQLite history, dashboard analytics, daily/weekly trends, and AI flip advice.",
                                className="app-subtitle"
                            )
                        ]
                    ),
                    html.Div("Local dashboard", className="env-badge")
                ]
            ),

            dcc.Interval(
                id="auto-refresh",
                interval=60 * 1000,
                n_intervals=0
            ),

            build_filters(),

            html.Div(id="kpi-cards", className="kpi-grid"),

            dcc.Tabs(
                id="main-tabs",
                value="overview",
                persistence=True,
                persistence_type="session",
                className="dash-tabs",
                children=[
                    dcc.Tab(
                        label="Accounts",
                        value="accounts",
                        className="tab",
                        selected_className="tab--selected",
                        children=[build_account_manager_tab()]
                    ),

                    dcc.Tab(
                        label="Overview",
                        value="overview",
                        className="tab",
                        selected_className="tab--selected",
                        children=[
                            html.Div(
                                className="chart-grid",
                                children=[
                                    html.Div(
                                        dcc.Graph(id="top-profit-chart"),
                                        className="panel chart-panel"
                                    ),
                                    html.Div(
                                        dcc.Graph(id="quick-overnight-chart"),
                                        className="panel chart-panel"
                                    ),
                                    html.Div(
                                        dcc.Graph(id="trend-position-chart"),
                                        className="panel chart-panel"
                                    ),
                                    html.Div(
                                        dcc.Graph(id="roi-volume-chart"),
                                        className="panel chart-panel"
                                    )
                                ]
                            )
                        ]
                    ),

                    dcc.Tab(
                        label="My Trades",
                        value="my-trades",
                        className="tab",
                        selected_className="tab--selected",
                        children=[build_my_trades_tab()]
                    ),

                    dcc.Tab(
                        label="AI Advisor",
                        value="ai-advisor",
                        className="tab",
                        selected_className="tab--selected",
                        children=[build_ai_panel()]
                    ),

                    dcc.Tab(
                        label="Trade Board",
                        value="trade-board",
                        className="tab",
                        selected_className="tab--selected",
                        children=[build_trade_board_tab()]
                    ),

                    dcc.Tab(
                        label="Safety Review",
                        value="safety-review",
                        className="tab",
                        selected_className="tab--selected",
                        children=[build_safety_review_tab()]
                    ),

                    dcc.Tab(
                        label="Latest Flips",
                        value="latest-flips",
                        className="tab",
                        selected_className="tab--selected",
                        children=[build_latest_table()]
                    ),

                    dcc.Tab(
                        label="Item History",
                        value="item-history",
                        className="tab",
                        selected_className="tab--selected",
                        children=[build_item_history_tab()]
                    ),

                    dcc.Tab(
                        label="Recurring Flips",
                        value="recurring-flips",
                        className="tab",
                        selected_className="tab--selected",
                        children=[build_recurring_table()]
                    ),

                    dcc.Tab(
                        label="Status / Logs",
                        value="status-logs",
                        className="tab",
                        selected_className="tab--selected",
                        children=[build_status_logs_tab()]
                    ),

                    dcc.Tab(
                        label="Maintenance",
                        value="maintenance",
                        className="tab",
                        selected_className="tab--selected",
                        children=[build_maintenance_tab()]
                    ),

                    dcc.Tab(
                        label="About",
                        value="about",
                        className="tab",
                        selected_className="tab--selected",
                        children=[build_about_tab()]
                    ),

                    dcc.Tab(
                        label="Settings",
                        value="settings",
                        className="tab",
                        selected_className="tab--selected",
                        children=[build_settings_tab()]
                    )
                ]
            )
        ]
    )

