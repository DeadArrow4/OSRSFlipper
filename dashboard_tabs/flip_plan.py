"""Simple decision-first Next Moves dashboard section."""
from dash import dash_table, dcc, html

from dashboard_components import settings_section
from dashboard_theme import base_table_styles


def _plan_table(table_id, page_size=8, max_height="360px", selectable=False):
    styles = base_table_styles(max_height=max_height)
    selection_props = {}

    if selectable:
        selection_props = {
            "row_selectable": "single",
            "selected_rows": [],
        }

    return dash_table.DataTable(
        id=table_id,
        data=[],
        columns=[],
        page_size=page_size,
        sort_action="native",
        filter_action="none",
        fixed_rows={"headers": True},
        style_as_list_view=True,
        **selection_props,
        style_table={
            **styles["style_table"],
            "maxHeight": max_height,
            "overflowX": "auto",
            "overflowY": "auto",
        },
        style_cell={
            **styles["style_cell"],
            "fontFamily": "Inter, Segoe UI, Arial, sans-serif",
            "fontSize": "13px",
            "padding": "9px 10px",
            "minWidth": "68px",
            "maxWidth": "180px",
            "whiteSpace": "normal",
            "lineHeight": "1.35",
        },
        style_header={
            **styles["style_header"],
            "fontSize": "13px",
            "padding": "10px",
            "textTransform": "none",
        },
        style_data_conditional=[
            {
                "if": {"filter_query": "{Action} contains 'Buy'"},
                "backgroundColor": "rgba(6, 78, 59, 0.55)",
                "color": "#d1fae5",
            },
            {
                "if": {"filter_query": "{Action} contains 'Reprice'"},
                "backgroundColor": "rgba(120, 53, 15, 0.58)",
                "color": "#fef3c7",
            },
            {
                "if": {"filter_query": "{Action} contains 'Overnight'"},
                "backgroundColor": "rgba(30, 64, 175, 0.42)",
                "color": "#dbeafe",
            },
            {
                "if": {"filter_query": "{Action} contains 'Review'"},
                "backgroundColor": "rgba(127, 29, 29, 0.55)",
                "color": "#fee2e2",
            },
            {
                "if": {"filter_query": "{Action} contains 'cancel'"},
                "backgroundColor": "rgba(120, 53, 15, 0.58)",
                "color": "#fef3c7",
            },
            {"if": {"column_id": "Action"}, "fontWeight": "900"},
            {"if": {"column_id": "Item"}, "fontWeight": "900", "minWidth": "170px"},
            {"if": {"column_id": "Why"}, "minWidth": "260px", "maxWidth": "460px"},
            {"if": {"column_id": "Reason"}, "minWidth": "260px", "maxWidth": "460px"},
            {"if": {"column_id": "Note"}, "minWidth": "320px", "maxWidth": "560px"},
        ],
        css=[
            {"selector": ".dash-spreadsheet-menu", "rule": "display: none;"},
            {"selector": ".column-header-name", "rule": "font-weight: 850;"},
            {
                "selector": "td.cell--selected, td.focused",
                "rule": "background-color: #1e293b !important; color: #f8fafc !important;",
            },
        ],
    )


def build_flip_plan_tab():
    return html.Div(
        className="settings-page flip-plan-page",
        children=[
            dcc.Store(id="flip-buy-plan-records", data=[]),
            dcc.Store(id="flip-buy-selected-index", data=0),
            dcc.Store(id="flip-offer-intents-version", data=0),
            settings_section(
                "Next Moves",
                "Your shortest path from current GP and GE offers to the next buy, sell, hold, or wait decision.",
                children=[
                    html.Div(
                        className="flip-plan-hero",
                        children=[
                            html.Div(
                                className="flip-plan-status-block",
                                children=[
                                    html.Div("Right now", className="flip-plan-eyebrow"),
                                    html.Div(
                                        id="flip-plan-status",
                                        className="flip-plan-headline",
                                        children="Building your plan from RuneLite capital and market data.",
                                    ),
                                    html.Div(
                                        id="flip-plan-updated",
                                        className="muted-text flip-plan-updated",
                                        children="",
                                    ),
                                ],
                            ),
                            html.Button(
                                "Refresh Moves",
                                id="flip-plan-refresh-button",
                                n_clicks=0,
                                className="primary-button flip-plan-refresh-button",
                            ),
                        ],
                    ),
                    html.Div(id="flip-plan-kpi-cards", className="kpi-grid flip-plan-kpis"),
                ],
            ),
            html.Div(
                className="flip-plan-stack",
                children=[
                    settings_section(
                        "Current Offers",
                        "Tax-aware action guidance for your active GE buys and sells.",
                        children=[
                            html.Div(
                                className="settings-action-row flip-offer-intent-actions",
                                children=[
                                    html.Button(
                                        "Mark Selected Overnight",
                                        id="flip-mark-overnight-button",
                                        n_clicks=0,
                                        className="secondary-button",
                                    ),
                                    html.Button(
                                        "Clear Overnight",
                                        id="flip-clear-overnight-button",
                                        n_clicks=0,
                                        className="secondary-button",
                                    ),
                                    html.Div(
                                        id="flip-offer-intent-status",
                                        className="status-text settings-save-status",
                                        children="Select an offer row to mark an intentional overnight hold.",
                                    ),
                                ],
                            ),
                            _plan_table("flip-offer-plan-table", page_size=10, max_height="360px", selectable=True),
                            html.Div(
                                id="flip-offer-plan-detail",
                                className="flip-plan-detail-panel",
                                children="Click an offer row to see the tax, reason, and overnight status.",
                            ),
                        ],
                    ),
                    settings_section(
                        "Buy Candidates",
                        "Capital-fit candidates from the ranked board, filtered to what your current GP can actually support.",
                        children=[
                            html.Div(
                                className="flip-buy-candidate-workspace",
                                children=[
                                    html.Div(
                                        id="flip-buy-candidate-list",
                                        className="flip-buy-candidate-list",
                                        children=[
                                            html.Div(
                                                "Loading buy candidates.",
                                                className="muted-text flip-buy-candidate-empty",
                                            )
                                        ],
                                    ),
                                    html.Div(
                                        id="flip-buy-plan-detail",
                                        className="flip-plan-detail-panel flip-buy-detail-panel",
                                        children="Select a buy candidate to see the reasoning and capital note.",
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            settings_section(
                "Plan Notes",
                "Things that should change your next move before you spend another slot or GP.",
                children=[html.Div(id="flip-plan-notes-list", className="flip-plan-notes-list")],
            ),
        ],
    )
