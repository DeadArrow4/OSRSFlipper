"""Top-level dashboard layout builder."""
from dash import html, dcc

from account_manager import get_current_session
from app_version import get_version_line

from .admin import build_admin_tab, build_safety_review_tab
from .ai import build_ai_panel
from .market import build_market_data_tab
from .overview import build_filters
from .trade_board import build_trade_board_tab
from .trades import build_my_trades_tab


def _build_app_command_bar():
    try:
        session = get_current_session() or {}
    except Exception:
        session = {}

    app_user = session.get("username") or "No local user"
    osrs_account = session.get("osrs_account_name") or "RuneLite not linked"

    return html.Div(
        className="app-command-bar",
        children=[
            html.Div(
                className="app-command-brand",
                children=[
                    html.Div("OSRSFlipper", className="app-command-title"),
                    html.Div(get_version_line(), className="app-command-subtitle"),
                ],
            ),
            html.Div(
                className="app-command-meta",
                children=[
                    html.Div(
                        className="app-command-chip",
                        children=[
                            html.Span("User", className="app-command-chip-label"),
                            html.Span(app_user, className="app-command-chip-value"),
                        ],
                    ),
                    html.Div(
                        className="app-command-chip",
                        children=[
                            html.Span("RuneLite", className="app-command-chip-label"),
                            html.Span(osrs_account, className="app-command-chip-value"),
                        ],
                    ),
                ],
            ),
        ],
    )


def build_app_layout():
    return html.Div(
        className="app-shell",
        children=[
            html.Div(className="osrs-hidden-legacy-top-banner", style={"display": "none"}),

            dcc.Interval(
                id="auto-refresh",
                interval=60 * 1000,
                n_intervals=0
            ),

            build_filters(),

            _build_app_command_bar(),

            html.Div(
                className="osrs-hidden-legacy-top-kpis",
                style={"display": "none"},
                children=[
                    html.Div(id="kpi-cards", className="kpi-grid")
                ],
            ),

            dcc.Tabs(
                id="main-tabs",
                value="overview",
                persistence=True,
                persistence_type="session",
                className="dash-tabs",
                children=[
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
                        label="Market Data",
                        value="market-data",
                        className="custom-tab",
                        selected_className="custom-tab--selected",
                        children=[build_market_data_tab()]
                    ),
dcc.Tab(
                        label="Admin",
                        value="admin",
                        className="custom-tab",
                        selected_className="custom-tab--selected",
                        children=[build_admin_tab()]
                    ),
]
            )
        ]
    )

