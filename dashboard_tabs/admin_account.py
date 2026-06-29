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
                            ),
                            settings_input(
                                "Dashboard PIN",
                                dcc.Input(
                                    id="account-switch-pin",
                                    type="password",
                                    placeholder="dashboard PIN"
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
                    html.Div("Dashboard PIN", className="section-title"),
                    html.Div(
                        "Set or replace the PIN used to unlock the saved local dashboard session.",
                        className="muted-text"
                    ),
                    html.Div(
                        className="filter-row",
                        children=[
                            settings_input(
                                "Local password",
                                dcc.Input(
                                    id="account-pin-password",
                                    type="password",
                                    placeholder="local OSRSFlipper password"
                                )
                            ),
                            settings_input(
                                "New PIN",
                                dcc.Input(
                                    id="account-pin-new",
                                    type="password",
                                    placeholder="4-8 digit PIN"
                                )
                            ),
                            settings_input(
                                "Confirm PIN",
                                dcc.Input(
                                    id="account-pin-confirm",
                                    type="password",
                                    placeholder="confirm dashboard PIN"
                                )
                            )
                        ]
                    ),
                    html.Button(
                        "Save Dashboard PIN",
                        id="account-pin-button",
                        n_clicks=0,
                        className="primary-button"
                    ),
                    html.Div(
                        id="account-pin-status",
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
                                "Dashboard PIN",
                                dcc.Input(
                                    id="account-create-pin",
                                    type="password",
                                    placeholder="4-8 digit PIN"
                                )
                            ),
                            settings_input(
                                "Confirm PIN",
                                dcc.Input(
                                    id="account-create-confirm-pin",
                                    type="password",
                                    placeholder="confirm dashboard PIN"
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

