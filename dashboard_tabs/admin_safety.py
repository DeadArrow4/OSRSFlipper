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

