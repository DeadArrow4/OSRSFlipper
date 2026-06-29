"""Admin tab shell for the OSRSFlipper dashboard."""
from dash import dcc, html

from .admin_about import build_about_tab
from .admin_account import build_account_manager_tab
from .admin_data_health import build_data_health_tab
from .admin_maintenance import build_maintenance_tab
from .admin_omitted import build_omitted_items_tab
from .admin_safety import build_safety_review_tab
from .admin_settings import build_settings_tab
from .admin_setup import build_setup_tab
from .admin_status import (
    build_log_dropdown_options,
    build_status_cards,
    build_status_logs_tab,
)


def build_admin_tab():
    return html.Div(
        className="settings-page admin-page",
        children=[
            html.Div(
                className="panel settings-panel",
                children=[
                    html.Div("Admin", className="section-title"),
                    html.Div(
                        "Low-frequency tools are grouped here to keep the main dashboard tab row focused on day-to-day flipping.",
                        className="muted-text settings-section-subtitle"
                    ),
                ],
            ),
            dcc.Tabs(
                id="admin-tabs",
                value="admin-account",
                className="custom-tabs admin-tabs",
                children=[
                    dcc.Tab(
                        label="Account",
                        value="admin-account",
                        className="custom-tab",
                        selected_className="custom-tab--selected",
                        children=[build_account_manager_tab()]
                    ),
                    dcc.Tab(
                        label="Status / Logs",
                        value="admin-status-logs",
                        className="custom-tab",
                        selected_className="custom-tab--selected",
                        children=[build_status_logs_tab()]
                    ),
                    
                    dcc.Tab(
                        label="Data Health",
                        value="admin-data-health",
                        className="custom-tab",
                        selected_className="custom-tab--selected",
                        children=[build_data_health_tab()]
                    ),
dcc.Tab(
                        label="Maintenance",
                        value="admin-maintenance",
                        className="custom-tab",
                        selected_className="custom-tab--selected",
                        children=[build_maintenance_tab()]
                    ),
                    dcc.Tab(
                        label="Omitted Items",
                        value="admin-omitted-items",
                        className="custom-tab",
                        selected_className="custom-tab--selected",
                        children=[build_omitted_items_tab()]
                    ),
                    dcc.Tab(
                        label="Settings",
                        value="admin-settings",
                        className="custom-tab",
                        selected_className="custom-tab--selected",
                        children=[build_settings_tab()]
                    ),
                    dcc.Tab(
                        label="About",
                        value="admin-about",
                        className="custom-tab",
                        selected_className="custom-tab--selected",
                        children=[build_about_tab()]
                    ),
                ],
            ),
        ],
    )

