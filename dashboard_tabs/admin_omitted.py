"""Admin page for account-scoped omitted items."""
from dash import dcc, html, dash_table

from dashboard_components import setting_card, settings_section
from dashboard_data import get_item_options, get_omitted_item_rows
from dashboard_theme import base_table_styles


def build_omitted_items_tab():
    omitted_rows = get_omitted_item_rows()
    table_styles = base_table_styles(max_height="420px")

    return html.Div(
        className="settings-page admin-omitted-items-page",
        children=[
            dcc.Store(id="omit-items-version", data=0),
            settings_section(
                "Omitted Items",
                "Hide items from recommendations, AI context, safety review, live offers, history, and exports.",
                children=[
                    html.Div(
                        className="settings-grid settings-grid-3",
                        children=[
                            setting_card(
                                "Item",
                                dcc.Dropdown(
                                    id="omit-item-dropdown",
                                    options=get_item_options(),
                                    placeholder="Choose an item to omit",
                                    clearable=True,
                                    className="dark-dropdown",
                                ),
                                "Omitted items stay hidden until restored."
                            ),
                            setting_card(
                                "Reason",
                                dcc.Input(
                                    id="omit-item-reason",
                                    type="text",
                                    placeholder="Optional note",
                                    className="settings-input",
                                ),
                                "Optional note for why you hid it."
                            ),
                            html.Div(
                                className="setting-card",
                                children=[
                                    html.Div("Actions", className="settings-card-label"),
                                    html.Div(
                                        className="settings-action-row compact-action-row",
                                        children=[
                                            html.Button(
                                                "Omit Item",
                                                id="omit-item-button",
                                                n_clicks=0,
                                                className="primary-button",
                                            ),
                                            html.Button(
                                                "Restore Selected",
                                                id="restore-omitted-item-button",
                                                n_clicks=0,
                                                className="secondary-button",
                                            ),
                                        ],
                                    ),
                                    html.Div(id="omit-item-status", className="setting-help"),
                                ],
                            ),
                        ],
                    ),
                    dash_table.DataTable(
                        id="omitted-items-table",
                        data=omitted_rows,
                        columns=[
                            {"name": "ID", "id": "ID"},
                            {"name": "Item", "id": "Item"},
                            {"name": "Item ID", "id": "Item ID"},
                            {"name": "Reason", "id": "Reason"},
                            {"name": "Created", "id": "Created"},
                        ],
                        row_selectable="single",
                        selected_rows=[],
                        page_size=12,
                        sort_action="native",
                        style_table=table_styles["style_table"],
                        style_cell=table_styles["style_cell"],
                        style_header=table_styles["style_header"],
                    ),
                ],
            ),
        ],
    )
