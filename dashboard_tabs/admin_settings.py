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
    budget_options = [
        {"label": "Manual only", "value": "manual"},
        {"label": "Live usable GP", "value": "live"},
        {"label": "Live usable GP capped by Cash stack", "value": "live_capped"},
    ]
    dashboard_open_options = [
        {"label": "App window", "value": "app"},
        {"label": "Browser tab", "value": "browser"},
    ]
    status_mode_options = [
        {"label": "Quiet launcher", "value": "quiet"},
        {"label": "Live status screen", "value": "status"},
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
                                "Manual GP cap for the collector. Live capital can use this as a safety cap."
                            ),
                            setting_card(
                                "Capital budget mode",
                                setting_select(
                                    "setting-capital-budget-mode",
                                    budget_options,
                                    setting_value("capital_budget_mode", "live_capped")
                                ),
                                "Controls whether scanner quantity uses manual Cash stack, live usable GP, or both."
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
                            ),
                            setting_card(
                                "Dashboard window",
                                setting_select(
                                    "setting-dashboard-open-mode",
                                    dashboard_open_options,
                                    setting_value("dashboard_open_mode", "app")
                                ),
                                "App window uses Edge/Chrome app mode when available."
                            ),
                            setting_card(
                                "Control window",
                                setting_select(
                                    "setting-control-center-status-mode",
                                    status_mode_options,
                                    setting_value("control_center_status_mode", "quiet")
                                ),
                                "Quiet launcher stops the console from repainting every few seconds."
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
                                "Input cost / 1M tokens",
                                setting_text_box(
                                    "setting-ai-input-cost-per-1m-tokens",
                                    setting_value("ai_input_cost_per_1m_tokens", 0.0),
                                    "0.00"
                                ),
                                "Used only for local cost estimates. Leave 0 to disable cost math."
                            ),
                            setting_card(
                                "Output cost / 1M tokens",
                                setting_text_box(
                                    "setting-ai-output-cost-per-1m-tokens",
                                    setting_value("ai_output_cost_per_1m_tokens", 0.0),
                                    "0.00"
                                ),
                                "Used with logged token counts to estimate per-prompt cost."
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
                                "Overnight slots",
                                setting_text_box(
                                    "setting-overnight-slot-target",
                                    setting_value("overnight_slot_target", 1),
                                    "1"
                                ),
                                "Target GE slots for longer overnight flips. Use 0, 1, or 2."
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

