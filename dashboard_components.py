"""
Reusable Dash UI components for the OSRSFlipper dashboard.
"""
from dash import html, dcc, dash_table

from dashboard_theme import base_table_styles


def build_trade_table(table_id, title, subtitle=None, header_actions=None):
    styles = base_table_styles(max_height="560px")

    completed_conditionals = [
        {"if": {"column_id": "Total_Profit"}, "fontWeight": "bold"},
        {"if": {"column_id": "Net_Profit_Each"}, "fontWeight": "bold"},
        {"if": {"column_id": "ROI_Percent"}, "fontWeight": "bold"},
        {"if": {"filter_query": "{Total_Profit} < 0"}, "backgroundColor": "rgba(127, 29, 29, 0.72)", "color": "#fee2e2"},
        {"if": {"filter_query": "{Total_Profit} > 0"}, "backgroundColor": "rgba(6, 78, 59, 0.62)", "color": "#d1fae5"},
        {"if": {"column_id": "Notes"}, "maxWidth": "260px"},
        {"if": {"column_id": "Item"}, "minWidth": "180px"},
        {"if": {"column_id": "Sell_Time"}, "minWidth": "165px"},
        {"if": {"column_id": "Time"}, "minWidth": "165px"},
    ]

    return html.Div(
        className="panel trade-table-panel",
        children=[
            html.Div(
                className="trade-table-header",
                children=[
                    html.Div(
                        className="trade-table-header-copy",
                        children=[
                            html.Div(title, className="section-title"),
                            html.Div(subtitle or "", className="muted-text settings-section-subtitle"),
                        ],
                    ),
                    html.Div(
                        className="trade-table-header-actions",
                        children=header_actions or [],
                    ) if header_actions else None,
                ],
            ),
            dash_table.DataTable(
                id=table_id,
                page_size=12,
                sort_action="native",
                filter_action="none",
                fixed_rows={"headers": True},
                style_as_list_view=True,
                style_table={
                    **styles["style_table"],
                    "maxHeight": "560px",
                    "overflowX": "auto",
                    "overflowY": "auto"
                },
                style_cell={
                    **styles["style_cell"],
                    "fontFamily": "Inter, Segoe UI, Arial, sans-serif",
                    "fontSize": "13px",
                    "padding": "9px 10px",
                    "minWidth": "92px",
                    "maxWidth": "220px",
                    "whiteSpace": "normal",
                    "lineHeight": "1.35"
                },
                style_header={
                    **styles["style_header"],
                    "fontSize": "13px",
                    "padding": "10px",
                    "textTransform": "none"
                },
                style_data_conditional=completed_conditionals,
                css=[
                    {"selector": ".dash-spreadsheet-menu", "rule": "display: none;"},
                    {"selector": ".column-header-name", "rule": "font-weight: 850;"},
                    {"selector": "td.cell--selected, td.focused", "rule": "background-color: #1e293b !important; color: #f8fafc !important;"},
                ]
            )
        ]
    )


def latest_table_conditional_styles():
    return [
        {
            "if": {"filter_query": "{Category} = 'Quick Flip'"},
            "backgroundColor": "rgba(6, 78, 59, 0.62)",
            "color": "#d1fae5"
        },
        {
            "if": {"filter_query": "{Category} = 'Watch / Test First'"},
            "backgroundColor": "rgba(120, 53, 15, 0.72)",
            "color": "#fef3c7"
        },
        {
            "if": {"filter_query": "{Category} = 'Avoid'"},
            "backgroundColor": "rgba(127, 29, 29, 0.72)",
            "color": "#fee2e2"
        },
        {
            "if": {"filter_query": "{Risk} = 'High'"},
            "backgroundColor": "rgba(127, 29, 29, 0.45)",
            "color": "#fee2e2"
        },
        {
            "if": {"filter_query": "{Warning} != 'OK' && {Warning} != ''"},
            "backgroundColor": "rgba(120, 53, 15, 0.58)",
            "color": "#fef3c7"
        },
        {"if": {"column_id": "Action"}, "fontWeight": "900"},
        {"if": {"column_id": "Score"}, "fontWeight": "900"},
        {"if": {"column_id": "Item"}, "fontWeight": "900", "minWidth": "180px"},
        {"if": {"column_id": "Total Profit"}, "fontWeight": "900"},
        {"if": {"column_id": "ROI %"}, "fontWeight": "900"},
        {"if": {"column_id": "Why"}, "minWidth": "260px", "maxWidth": "420px"},
    ]


def compact_flip_table(table_id, page_size=12, max_height="620px", conditionals=None):
    styles = base_table_styles(max_height=max_height)

    return dash_table.DataTable(
        id=table_id,
        page_size=page_size,
        sort_action="native",
        filter_action="none",
        fixed_rows={"headers": True},
        style_as_list_view=True,
        style_table={
            **styles["style_table"],
            "maxHeight": max_height,
            "overflowX": "auto",
            "overflowY": "auto"
        },
        style_cell={
            **styles["style_cell"],
            "fontFamily": "Inter, Segoe UI, Arial, sans-serif",
            "fontSize": "13px",
            "padding": "9px 10px",
            "minWidth": "86px",
            "maxWidth": "220px",
            "whiteSpace": "normal",
            "lineHeight": "1.35"
        },
        style_header={
            **styles["style_header"],
            "fontSize": "13px",
            "padding": "10px",
            "textTransform": "none"
        },
        style_data_conditional=conditionals or [],
        css=[
            {"selector": ".dash-spreadsheet-menu", "rule": "display: none;"},
            {"selector": ".column-header-name", "rule": "font-weight: 850;"},
            {"selector": "td.cell--selected, td.focused", "rule": "background-color: #1e293b !important; color: #f8fafc !important;"},
        ]
    )


def build_boolean_dropdown(component_id, value):
    return dcc.Dropdown(
        id=component_id,
        options=[
            {"label": "Enabled", "value": "true"},
            {"label": "Disabled", "value": "false"}
        ],
        value="true" if bool(value) else "false",
        clearable=False
    )


def settings_input(label, component):
    return html.Div(
        className="filter-box",
        children=[
            html.Label(label),
            component
        ]
    )


def setting_text_box(component_id, value="", placeholder="", password=False):
    return dcc.Input(
        id=component_id,
        type="password" if password else "text",
        value=str(value if value is not None else ""),
        placeholder=placeholder,
        className="settings-text-input",
        debounce=False
    )


def setting_select(component_id, options, value):
    return dcc.Dropdown(
        id=component_id,
        options=options,
        value=value,
        clearable=False,
        className="settings-dropdown"
    )


def setting_card(label, control, help_text=None):
    children = [
        html.Div(label, className="settings-card-label"),
        control
    ]

    if help_text:
        children.append(html.Div(help_text, className="settings-card-help"))

    return html.Div(
        className="settings-card setting-card",
        children=children
    )


def settings_section(title, subtitle=None, children=None, footer=None):
    panel_children = [
        html.Div(title, className="section-title settings-section-title")
    ]

    if subtitle:
        panel_children.append(
            html.Div(subtitle, className="muted-text settings-section-subtitle")
        )

    if children:
        panel_children.extend(children)

    if footer:
        panel_children.append(footer)

    return html.Div(
        className="panel settings-panel settings-section",
        children=panel_children
    )
