from dash import dcc, html, dash_table
import plotly.express as px


# =========================
# DASHBOARD DARK THEME PATCH
# =========================
# Dash core components and DataTable can inject inline white backgrounds.
# These wrappers force the newer Setup/Accounts/Settings/About controls to
# use the same dark theme as the rest of the dashboard.
THEME_BG = "#0f172a"
THEME_BG_DEEP = "#020617"
THEME_PANEL = "#111827"
THEME_PANEL_SOFT = "#162033"
THEME_PANEL_RAISED = "#1e293b"
THEME_BORDER = "#334155"
THEME_TEXT = "#f8fafc"
THEME_TEXT_SOFT = "#cbd5e1"
THEME_TEXT_MUTED = "#94a3b8"
THEME_ACCENT = "#3b82f6"


def _merge_style(default_style, user_style):
    merged = dict(default_style or {})
    merged.update(user_style or {})
    return merged


def _merge_css_classes(existing, extra):
    existing = str(existing or "").strip()
    if not existing:
        return extra
    if extra in existing.split():
        return existing
    return f"{existing} {extra}"


_ORIGINAL_DASH_INPUT = dcc.Input
_ORIGINAL_DASH_DROPDOWN = dcc.Dropdown
_ORIGINAL_DASH_DATATABLE = dash_table.DataTable


def _dark_input(*args, **kwargs):
    # Keep native Dash numeric inputs usable. The CSS file handles spinner styling.
    kwargs["className"] = _merge_css_classes(kwargs.get("className"), "themed-input")

    kwargs["style"] = _merge_style({
        "backgroundColor": THEME_BG_DEEP,
        "color": THEME_TEXT,
        "border": f"1px solid {THEME_BORDER}",
        "borderRadius": "10px",
        "minHeight": "38px",
        "boxShadow": "none",
        "colorScheme": "dark"
    }, kwargs.get("style"))
    return _ORIGINAL_DASH_INPUT(*args, **kwargs)


def _dark_dropdown(*args, **kwargs):
    kwargs["className"] = _merge_css_classes(kwargs.get("className"), "themed-dropdown")
    kwargs["style"] = _merge_style({
        "backgroundColor": THEME_BG_DEEP,
        "color": THEME_TEXT,
        "borderRadius": "10px"
    }, kwargs.get("style"))
    return _ORIGINAL_DASH_DROPDOWN(*args, **kwargs)


def _dark_datatable(*args, **kwargs):
    kwargs["style_table"] = _merge_style({
        "overflowX": "auto",
        "backgroundColor": "transparent",
        "border": f"1px solid {THEME_BORDER}",
        "borderRadius": "12px"
    }, kwargs.get("style_table"))

    kwargs["style_cell"] = _merge_style({
        "textAlign": "left",
        "padding": "9px 10px",
        "whiteSpace": "normal",
        "height": "auto",
        "backgroundColor": THEME_BG_DEEP,
        "color": THEME_TEXT_SOFT,
        "border": f"1px solid {THEME_BORDER}",
        "fontFamily": "Consolas, 'Courier New', monospace",
        "fontSize": "12px"
    }, kwargs.get("style_cell"))

    kwargs["style_header"] = _merge_style({
        "backgroundColor": THEME_PANEL_RAISED,
        "color": THEME_TEXT,
        "fontWeight": "800",
        "border": f"1px solid {THEME_BORDER}",
        "fontFamily": "Inter, Segoe UI, Arial, sans-serif",
        "fontSize": "13px"
    }, kwargs.get("style_header"))

    kwargs["style_data"] = _merge_style({
        "backgroundColor": THEME_BG_DEEP,
        "color": THEME_TEXT_SOFT,
        "border": f"1px solid {THEME_BORDER}"
    }, kwargs.get("style_data"))

    kwargs["style_filter"] = _merge_style({
        "backgroundColor": THEME_BG_DEEP,
        "color": THEME_TEXT,
        "border": f"1px solid {THEME_BORDER}"
    }, kwargs.get("style_filter"))

    existing_conditionals = list(kwargs.get("style_data_conditional") or [])
    dark_conditionals = [
        {
            "if": {"row_index": "odd"},
            "backgroundColor": "#071126",
            "color": THEME_TEXT_SOFT
        },
        {
            "if": {"state": "active"},
            "backgroundColor": THEME_PANEL_RAISED,
            "border": f"1px solid {THEME_ACCENT}",
            "color": THEME_TEXT
        },
        {
            "if": {"state": "selected"},
            "backgroundColor": THEME_PANEL_RAISED,
            "border": f"1px solid {THEME_ACCENT}",
            "color": THEME_TEXT
        }
    ]
    kwargs["style_data_conditional"] = dark_conditionals + existing_conditionals

    css = list(kwargs.get("css") or [])
    css.extend([
        {"selector": ".dash-spreadsheet-container", "rule": f"background-color: {THEME_BG_DEEP} !important; color: {THEME_TEXT_SOFT} !important;"},
        {"selector": ".dash-spreadsheet-inner", "rule": f"background-color: {THEME_BG_DEEP} !important; color: {THEME_TEXT_SOFT} !important;"},
        {"selector": "table", "rule": f"background-color: {THEME_BG_DEEP} !important; color: {THEME_TEXT_SOFT} !important;"},
        {"selector": "th", "rule": f"background-color: {THEME_PANEL_RAISED} !important; color: {THEME_TEXT} !important; border-color: {THEME_BORDER} !important;"},
        {"selector": "td", "rule": f"background-color: {THEME_BG_DEEP} !important; color: {THEME_TEXT_SOFT} !important; border-color: {THEME_BORDER} !important;"},
        {"selector": "tr:nth-child(even) td", "rule": "background-color: #071126 !important;"},
        {"selector": "input", "rule": f"background-color: {THEME_BG_DEEP} !important; color: {THEME_TEXT} !important; border-color: {THEME_BORDER} !important;"}
    ])
    kwargs["css"] = css

    return _ORIGINAL_DASH_DATATABLE(*args, **kwargs)


dcc.Input = _dark_input
dcc.Dropdown = _dark_dropdown
dash_table.DataTable = _dark_datatable


def empty_figure(title):
    fig = px.scatter(title=title)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#111827",
        plot_bgcolor="#111827",
        font={"color": "#e5e7eb"},
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[
            {
                "text": "No data available yet",
                "xref": "paper",
                "yref": "paper",
                "showarrow": False,
                "font": {"size": 18, "color": "#94a3b8"}
            }
        ]
    )

    return fig


def apply_dark_chart_layout(fig, x_title=None, y_title=None, bottom_margin=60):
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#111827",
        plot_bgcolor="#111827",
        font={"color": "#e5e7eb"},
        xaxis_title=x_title,
        yaxis_title=y_title,
        margin={"l": 50, "r": 24, "t": 60, "b": bottom_margin},
        legend_title_text=""
    )

    return fig


def make_card(title, value, subtitle=None):
    children = [
        html.Div(title, className="kpi-title"),
        html.Div(value, className="kpi-value")
    ]

    if subtitle:
        children.append(html.Div(subtitle, className="kpi-subtitle"))

    return html.Div(children, className="kpi-card")


def base_table_styles(max_height="680px"):
    return {
        "style_table": {
            "overflowX": "auto",
            "overflowY": "auto",
            "maxHeight": max_height,
            "border": "1px solid #334155",
            "borderRadius": "12px"
        },
        "style_cell": {
            "textAlign": "left",
            "padding": "10px",
            "fontFamily": "Arial",
            "fontSize": "13px",
            "backgroundColor": "#020617",
            "color": "#e5e7eb",
            "border": "1px solid #1e293b",
            "maxWidth": "240px",
            "overflow": "hidden",
            "textOverflow": "ellipsis",
            "whiteSpace": "normal"
        },
        "style_header": {
            "fontWeight": "bold",
            "backgroundColor": "#1e293b",
            "color": "#f8fafc",
            "border": "1px solid #334155"
        }
    }
