import os
from security_runtime import scrub_shared_openai_env
scrub_shared_openai_env()
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px

from account_context import get_account_scope, apply_account_env
from app_version import get_version_info, get_version_line
from account_manager import (
    authenticate_user,
    create_user,
    get_current_session,
    list_users,
    save_session,
    update_osrs_account
)
from openai_key_manager import save_api_key, delete_api_key, get_api_key_status, validate_key_shape
from openai_usage_manager import get_ai_usage_summary, init_ai_usage_db
from openai_key_tester import test_current_account_openai_key
from migration_manager import run_app_migrations
from safety_manager import build_safety_review, write_safety_review
from release_check import run_release_check
from backup_manager import create_private_backup
from prepare_release import prepare_clean_release_package
from update_install import install_update
from first_run_setup import locate_runelite_file
from settings_manager import (
    ensure_default_settings,
    get_setting,
    set_setting,
    DEFAULT_SETTINGS
)

from dash import Dash, html, dcc, dash_table, Input, Output, State, ctx, no_update, ctx, no_update
from advisor import generate_ai_advice, OUTPUT_FILE
from database import init_db

try:
    from trade_tracker import init_trade_db
except Exception:
    init_trade_db = None


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



BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "osrs_flip_scanner.db")
LOG_DIR = os.path.join(BASE_DIR, "logs")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

# Make sure SQLite has all current columns before the dashboard queries it.
init_db()

# Trade tracker tables are optional, but create them when trade_tracker.py exists.
if init_trade_db is not None:
    try:
        init_trade_db()
    except Exception as error:
        print("Trade tracker database init failed:")
        print(error)

# Dashboard overnight display rules. These match the advisor's stricter
# overnight preference: enough one-item margin, positive post-tax profit,
# and a worthwhile ROI.
OVERNIGHT_RAW_MARGIN_MIN = 10000
OVERNIGHT_ROI_MIN = 5.0


# =========================
# DATABASE HELPERS
# =========================

def db_exists():
    return os.path.exists(DB_FILE)


def query_df(query, params=None):
    if params is None:
        params = ()

    if not db_exists():
        return pd.DataFrame()

    conn = sqlite3.connect(DB_FILE)

    try:
        df = pd.read_sql_query(query, conn, params=params)
    except Exception as error:
        print("Dashboard database query failed:")
        print(error)
        print(query)
        df = pd.DataFrame()
    finally:
        conn.close()

    return df


def get_latest_run_id():
    df = query_df("""
        SELECT MAX(run_id) AS latest_run_id
        FROM scan_results
    """)

    if df.empty or pd.isna(df.loc[0, "latest_run_id"]):
        return None

    return int(df.loc[0, "latest_run_id"])


def get_latest_rows():
    latest_run_id = get_latest_run_id()

    if latest_run_id is None:
        return pd.DataFrame()

    df = query_df("""
        SELECT *
        FROM scan_results
        WHERE run_id = ?
        ORDER BY
            COALESCE(recommendation_score, 0) DESC,
            COALESCE(score, 0) DESC
    """, (latest_run_id,))

    if not df.empty and "scanned_at" in df.columns:
        df["scanned_at"] = pd.to_datetime(df["scanned_at"], errors="coerce")

    return df


def get_all_history():
    df = query_df("""
        SELECT *
        FROM scan_results
    """)

    if not df.empty and "scanned_at" in df.columns:
        df["scanned_at"] = pd.to_datetime(df["scanned_at"], errors="coerce")

    return df


def get_best_recurring_flips(limit=25):
    """
    Finds items/windows that keep appearing as profitable candidates.
    Older logic required 3+ appearances and could show a blank table on
    small databases. This version tries 2+ appearances first, then falls
    back to the best historical candidates so the tab remains useful.
    """
    limit = parse_positive_int(limit, default=25, minimum=5, maximum=500) if "parse_positive_int" in globals() else int(limit or 25)

    base_select = """
        SELECT
            item_name AS Item,
            window_name AS Window,
            COUNT(*) AS Appearances,
            ROUND(AVG(COALESCE(total_profit, 0)), 0) AS Avg_Total_Profit,
            ROUND(MAX(COALESCE(total_profit, 0)), 0) AS Best_Total_Profit,
            ROUND(AVG(COALESCE(profit_per_item, 0)), 2) AS Avg_Profit_Per_Item,
            ROUND(AVG(COALESCE(roi_percent, 0)), 2) AS Avg_ROI_Percent,
            ROUND(AVG(COALESCE(volume, 0)), 0) AS Avg_Volume,
            ROUND(AVG(COALESCE(quick_score, 0)), 2) AS Avg_Quick_Score,
            ROUND(AVG(COALESCE(overnight_score, 0)), 2) AS Avg_Overnight_Score,
            ROUND(AVG(COALESCE(recommendation_score, score, 0)), 2) AS Avg_Recommendation_Score,
            MAX(scanned_at) AS Last_Seen
        FROM scan_results
        WHERE COALESCE(result_type, '') = 'profitable'
           OR COALESCE(total_profit, 0) > 0
        GROUP BY item_id, item_name, window_name
    """

    query_two_plus = base_select + """
        HAVING Appearances >= 2
        ORDER BY Avg_Recommendation_Score DESC, Avg_Total_Profit DESC, Appearances DESC
        LIMIT ?
    """

    df = query_df(query_two_plus, (limit,))

    if not df.empty:
        return format_recurring_display_df(df)

    query_fallback = base_select + """
        ORDER BY Avg_Recommendation_Score DESC, Avg_Total_Profit DESC, Appearances DESC
        LIMIT ?
    """

    df = query_df(query_fallback, (limit,))
    return format_recurring_display_df(df)




def get_item_options():
    df = query_df("""
        SELECT DISTINCT item_name
        FROM scan_results
        ORDER BY item_name
    """)

    if df.empty or "item_name" not in df.columns:
        return []

    return [
        {"label": item_name, "value": item_name}
        for item_name in df["item_name"].dropna().tolist()
    ]


def read_saved_ai_advice():
    if not os.path.exists(OUTPUT_FILE):
        return (
            "## No AI advice yet\n\n"
            "Run `main.py` or `collector.py`, then click **Generate AI Advice**."
        )

    with open(OUTPUT_FILE, "r", encoding="utf-8") as file:
        return file.read()


# =========================
# FORMAT HELPERS
# =========================

def format_gp(value):
    if value is None or pd.isna(value):
        return "N/A"

    return f"{int(value):,}"


def format_percent(value):
    if value is None or pd.isna(value):
        return "N/A"

    return f"{round(float(value), 2)}%"


def format_time(value):
    if value is None or pd.isna(value):
        return "N/A"

    try:
        return pd.to_datetime(value).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


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


def sort_latest_rows(df):
    if df.empty:
        return df

    sort_columns = []
    ascending = []

    for column in [
        "recommendation_score",
        "quick_score",
        "overnight_score",
        "liquidity_score",
        "total_profit",
        "score"
    ]:
        if column in df.columns:
            sort_columns.append(column)
            ascending.append(False)

    if not sort_columns:
        return df

    return df.sort_values(
        by=sort_columns,
        ascending=ascending
    )


def add_chart_size(df):
    """
    Plotly scatter size values must be positive.
    Watchlist rows can have zero or negative total_profit after tax, so this
    creates a safe chart-size field without changing real profit values.
    """
    if df.empty:
        return df

    df = df.copy()

    if "total_profit" in df.columns:
        df["chart_size"] = pd.to_numeric(
            df["total_profit"],
            errors="coerce"
        ).fillna(0).abs()
        df["chart_size"] = df["chart_size"].clip(lower=1)
    else:
        df["chart_size"] = 1

    return df


def add_dashboard_flags(df):
    """
    Adds dashboard-only flags for clearer filtering and KPIs.

    This does not change SQLite data.
    """
    if df.empty:
        return df

    df = df.copy()

    for column_name in ["raw_margin", "profit_per_item", "roi_percent"]:
        if column_name not in df.columns:
            df[column_name] = 0

        df[column_name] = pd.to_numeric(
            df[column_name],
            errors="coerce"
        ).fillna(0)

    df["overnight_qualified"] = (
        (df["raw_margin"] >= OVERNIGHT_RAW_MARGIN_MIN)
        & (df["profit_per_item"] > 0)
        & (df["roi_percent"] >= OVERNIGHT_ROI_MIN)
    )

    return df


def get_balanced_latest_rows(df, limit):
    """
    Keeps the default dashboard from being dominated by Quick Flips.
    """
    if df.empty:
        return df

    limit = int(limit)
    quick_limit = max(5, limit // 3)
    overnight_limit = max(5, limit // 3)

    quick_df = pd.DataFrame()
    overnight_df = pd.DataFrame()

    if "flip_category" in df.columns:
        quick_df = df[df["flip_category"] == "Quick Flip"].copy()
        if not quick_df.empty:
            quick_sort = [column for column in ["quick_score", "recommendation_score", "liquidity_score", "total_profit", "score"] if column in quick_df.columns]
            if quick_sort:
                quick_df = quick_df.sort_values(by=quick_sort, ascending=[False] * len(quick_sort))
            quick_df = quick_df.head(quick_limit)

    if "overnight_qualified" in df.columns:
        overnight_df = df[df["overnight_qualified"] == True].copy()
        if not overnight_df.empty:
            overnight_sort = [column for column in ["overnight_score", "roi_percent", "profit_per_item", "raw_margin", "total_profit", "score"] if column in overnight_df.columns]
            if overnight_sort:
                overnight_df = overnight_df.sort_values(by=overnight_sort, ascending=[False] * len(overnight_sort))
            overnight_df = overnight_df.head(overnight_limit)

    selected_keys = set()

    for selected_df in [quick_df, overnight_df]:
        if selected_df.empty:
            continue

        for _, row in selected_df.iterrows():
            selected_keys.add((row.get("item_id"), row.get("window_name"), row.get("result_type")))

    remaining_df = df.copy()

    if selected_keys:
        remaining_df = remaining_df[
            ~remaining_df.apply(
                lambda row: (row.get("item_id"), row.get("window_name"), row.get("result_type")) in selected_keys,
                axis=1
            )
        ]

    remaining_df = sort_latest_rows(remaining_df)

    combined_df = pd.concat(
        [quick_df, overnight_df, remaining_df],
        ignore_index=True
    )

    if not combined_df.empty:
        combined_df = combined_df.drop_duplicates(
            subset=["item_id", "window_name", "result_type"],
            keep="first"
        )

    return combined_df.head(limit)


def get_filtered_latest(
    window_filter,
    result_type_filter,
    signal_filter,
    category_filter,
    trend_filter,
    limit
):
    df = get_latest_rows()

    if df.empty:
        return df

    df = add_dashboard_flags(df)

    if window_filter != "all" and "window_name" in df.columns:
        df = df[df["window_name"] == window_filter]

    if result_type_filter != "all" and "result_type" in df.columns:
        df = df[df["result_type"] == result_type_filter]

    if signal_filter != "all" and "signal" in df.columns:
        df = df[df["signal"] == signal_filter]

    if category_filter == "Quick Flip" and "flip_category" in df.columns:
        df = df[df["flip_category"] == "Quick Flip"]
    elif category_filter == "overnight_qualified" and "overnight_qualified" in df.columns:
        df = df[df["overnight_qualified"] == True]
    elif category_filter in ("Watch / Test First", "Avoid") and "flip_category" in df.columns:
        df = df[df["flip_category"] == category_filter]

    if trend_filter == "warnings" and "trend_warning" in df.columns:
        df = df[df["trend_warning"].fillna("OK") != "OK"]
    elif trend_filter == "ok" and "trend_warning" in df.columns:
        df = df[df["trend_warning"].fillna("OK") == "OK"]

    if category_filter == "all":
        return get_balanced_latest_rows(df, limit)

    df = sort_latest_rows(df)

    return df.head(limit)



# =========================
# TRADE TRACKER HELPERS
# =========================

def get_current_trade_scope():
    return get_account_scope()


def table_exists(table_name):
    df = query_df(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,)
    )

    return not df.empty


def get_trade_summary():
    if not table_exists("completed_trades"):
        return {
            "completed_count": 0,
            "realized_profit": 0,
            "avg_roi": 0,
            "best_trade": 0,
            "worst_trade": 0,
            "open_event_count": 0,
            "open_buy_value": 0
        }

    scope = get_current_trade_scope()

    completed_df = query_df("""
        SELECT
            COUNT(*) AS completed_count,
            COALESCE(SUM(total_profit), 0) AS realized_profit,
            COALESCE(AVG(roi_percent), 0) AS avg_roi,
            COALESCE(MAX(total_profit), 0) AS best_trade,
            COALESCE(MIN(total_profit), 0) AS worst_trade
        FROM completed_trades
        WHERE app_username = ?
          AND osrs_account_name = ?
    """, (
        scope["app_username"],
        scope["osrs_account_name"]
    ))

    if table_exists("trade_events"):
        open_df = query_df("""
            SELECT
                COUNT(*) AS open_event_count,
                COALESCE(SUM(CASE WHEN side = 'BUY' THEN price_each * remaining_quantity ELSE 0 END), 0) AS open_buy_value
            FROM trade_events
            WHERE app_username = ?
              AND osrs_account_name = ?
              AND remaining_quantity > 0
        """, (
            scope["app_username"],
            scope["osrs_account_name"]
        ))
    else:
        open_df = pd.DataFrame()

    if completed_df.empty:
        summary = {
            "completed_count": 0,
            "realized_profit": 0,
            "avg_roi": 0,
            "best_trade": 0,
            "worst_trade": 0
        }
    else:
        summary = completed_df.iloc[0].to_dict()

    if open_df.empty:
        summary["open_event_count"] = 0
        summary["open_buy_value"] = 0
    else:
        summary.update(open_df.iloc[0].to_dict())

    return summary


def get_completed_trade_rows(limit=100):
    if not table_exists("completed_trades"):
        return pd.DataFrame()

    scope = get_current_trade_scope()

    df = query_df("""
        SELECT
            sell_time AS Sell_Time,
            item_name AS Item,
            quantity AS Qty,
            buy_price_each AS Buy_Each,
            sell_price_each AS Sell_Each,
            raw_margin_each AS Raw_Margin_Each,
            tax_each AS Tax_Each,
            net_profit_each AS Net_Profit_Each,
            total_profit AS Total_Profit,
            ROUND(roi_percent, 2) AS ROI_Percent,
            source AS Source,
            notes AS Notes
        FROM completed_trades
        WHERE app_username = ?
          AND osrs_account_name = ?
        ORDER BY sell_time DESC, id DESC
        LIMIT ?
    """, (
        scope["app_username"],
        scope["osrs_account_name"],
        limit
    ))

    return df


def get_open_trade_rows(limit=100):
    if not table_exists("trade_events"):
        return pd.DataFrame()

    scope = get_current_trade_scope()

    df = query_df("""
        SELECT
            traded_at AS Time,
            item_name AS Item,
            side AS Side,
            price_each AS Price_Each,
            quantity AS Original_Qty,
            remaining_quantity AS Remaining_Qty,
            total_value AS Total_Value,
            source AS Source,
            status AS Status,
            notes AS Notes
        FROM trade_events
        WHERE app_username = ?
          AND osrs_account_name = ?
          AND remaining_quantity > 0
        ORDER BY traded_at DESC, id DESC
        LIMIT ?
    """, (
        scope["app_username"],
        scope["osrs_account_name"],
        limit
    ))

    return df


def get_completed_trade_history():
    if not table_exists("completed_trades"):
        return pd.DataFrame()

    scope = get_current_trade_scope()

    df = query_df("""
        SELECT
            sell_time,
            item_name,
            total_profit,
            roi_percent
        FROM completed_trades
        WHERE app_username = ?
          AND osrs_account_name = ?
        ORDER BY sell_time ASC, id ASC
    """, (
        scope["app_username"],
        scope["osrs_account_name"]
    ))

    if not df.empty:
        df["sell_time"] = pd.to_datetime(df["sell_time"], errors="coerce")
        df["cumulative_profit"] = df["total_profit"].fillna(0).cumsum()

    return df


def clean_trade_display_df(df):
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()

    for column in ["Sell_Time", "Time"]:
        if column in df.columns:
            df[column] = (
                df[column]
                .astype(str)
                .str.replace("T", " ", regex=False)
                .str.replace("+00:00", "", regex=False)
                .str.replace(".000000", "", regex=False)
            )

    return df


def trade_table_columns(df):
    friendly_names = {
        "Sell_Time": "Sell Time",
        "Time": "Time",
        "Item": "Item",
        "Qty": "Qty",
        "Buy_Each": "Buy Each",
        "Sell_Each": "Sell Each",
        "Raw_Margin_Each": "Raw Margin",
        "Tax_Each": "Tax",
        "Net_Profit_Each": "Net Profit Each",
        "Total_Profit": "Total Profit",
        "ROI_Percent": "ROI %",
        "Price_Each": "Price Each",
        "Original_Qty": "Original Qty",
        "Remaining_Qty": "Remaining Qty",
        "Total_Value": "Total Value",
        "Source": "Source",
        "Status": "Status",
        "Notes": "Notes",
        "Side": "Side"
    }

    return [
        {"name": friendly_names.get(column, str(column).replace("_", " ")), "id": column}
        for column in df.columns
    ]


def parse_positive_int(value, default=100, minimum=10, maximum=500):
    try:
        parsed = int(float(str(value).replace(",", "").strip()))
    except Exception:
        parsed = default

    return max(minimum, min(maximum, parsed))


def summarize_import_result(result):
    if not result:
        return "RuneLite import ran. No details returned."

    if isinstance(result, dict):
        imported = (
            result.get("imported")
            or result.get("imported_rows")
            or result.get("rows_imported")
            or 0
        )
        skipped = (
            result.get("skipped")
            or result.get("skipped_rows")
            or result.get("duplicates")
            or 0
        )
        matched = (
            result.get("matched")
            or result.get("matched_rows")
            or result.get("completed")
            or 0
        )
        status = result.get("status") or "OK"
        message = result.get("message") or ""

        return (
            f"RuneLite import {status}: imported {imported}, "
            f"skipped {skipped}, matched {matched}. {message}"
        ).strip()

    return f"RuneLite import result: {result}"


def refresh_runelite_trades_for_dashboard():
    """
    Imports the latest RuneLite Flipping Utilities JSON before refreshing
    My Trades. This keeps the My Trades tab current even when the background
    trade watcher is stopped.
    """
    try:
        return summarize_import_result(import_runelite_now())
    except Exception as primary_error:
        try:
            scope = get_current_trade_scope()
            runelite_path = locate_runelite_file(scope["osrs_account_name"])

            if not runelite_path:
                return f"RuneLite import skipped: no RuneLite JSON found for {scope['osrs_account_name']}."

            from trade_importer import import_file

            result = import_file(
                file_path=runelite_path,
                source="runelite-live-json",
                force=True
            )

            return summarize_import_result(result)

        except Exception as fallback_error:
            return f"RuneLite import failed: {fallback_error} | Primary path: {primary_error}"


def build_trade_table(table_id, title, subtitle=None):
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
            html.Div(title, className="section-title"),
            html.Div(subtitle or "", className="muted-text settings-section-subtitle"),
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


# =========================
# DASH APP
# =========================

app = Dash(__name__)
app.title = "OSRS Flip Dashboard"


# =========================
# LAYOUT BUILDERS
# =========================

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
                    ),

                    html.Div(
                        children=[
                            html.Label("Item history"),
                            dcc.Dropdown(
                                id="item-dropdown",
                                options=get_item_options(),
                                placeholder="Select an item",
                                clearable=True
                            )
                        ],
                        className="filter-box-wide"
                    )
                ]
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
                                "Uses liquidity, fill-time estimates, history, and daily/weekly trend scores.",
                                className="muted-text"
                            )
                        ]
                    ),
                    html.Div(
                        "After pressing Ask AI, results may take up to 5 minutes to appear. The dashboard will update when the AI response is ready.",
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





# =========================
# STATUS / LOG HELPERS
# =========================

def safe_file_modified_time(file_path):
    try:
        path = Path(file_path)

        if not path.exists():
            return "Not found"

        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %I:%M:%S %p")

    except Exception:
        return "Unknown"


def read_last_lines(file_path, max_lines=80):
    path = Path(file_path)

    if not path.exists():
        return f"{path.name} not found yet."

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as error:
        return f"Could not read {path.name}: {error}"

    lines = text.splitlines()

    if not lines:
        return f"{path.name} exists but is empty."

    return "\n".join(lines[-max_lines:])


def get_scalar(query, params=None, default=None):
    if params is None:
        params = ()

    df = query_df(query, params)

    if df.empty:
        return default

    value = df.iloc[0, 0]

    if pd.isna(value):
        return default

    return value


def get_status_summary():
    scope = get_current_trade_scope()

    latest_scan = get_scalar(
        """
        SELECT MAX(scanned_at)
        FROM scan_results
        """,
        default="No scan yet"
    )

    latest_trade_import = "No trade import yet"
    latest_import_status = "Unknown"
    latest_import_message = ""

    if table_exists("imported_trade_files"):
        import_df = query_df(
            """
            SELECT imported_at, imported_rows, skipped_rows, matched_trades, status, message, file_name
            FROM imported_trade_files
            WHERE app_username = ?
              AND osrs_account_name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                scope["app_username"],
                scope["osrs_account_name"]
            )
        )

        if not import_df.empty:
            row = import_df.iloc[0]
            latest_trade_import = row.get("imported_at", "No trade import yet")
            latest_import_status = (
                f"{row.get('status', 'Unknown')} | "
                f"rows {row.get('imported_rows', 0)} | "
                f"skipped {row.get('skipped_rows', 0)} | "
                f"matched {row.get('matched_trades', 0)} | "
                f"file {row.get('file_name', '')}"
            )
            latest_import_message = str(row.get("message", "") or "")

    latest_trade_event = "No trade event yet"

    if table_exists("trade_events"):
        latest_trade_event = get_scalar(
            """
            SELECT MAX(imported_at)
            FROM trade_events
            WHERE app_username = ?
              AND osrs_account_name = ?
            """,
            (
                scope["app_username"],
                scope["osrs_account_name"]
            ),
            default="No trade event yet"
        )

    completed_count = 0
    realized_profit = 0
    open_buys = 0

    if table_exists("completed_trades"):
        completed_count = get_scalar(
            """
            SELECT COUNT(*)
            FROM completed_trades
            WHERE app_username = ?
              AND osrs_account_name = ?
            """,
            (
                scope["app_username"],
                scope["osrs_account_name"]
            ),
            default=0
        )

        realized_profit = get_scalar(
            """
            SELECT COALESCE(SUM(total_profit), 0)
            FROM completed_trades
            WHERE app_username = ?
              AND osrs_account_name = ?
            """,
            (
                scope["app_username"],
                scope["osrs_account_name"]
            ),
            default=0
        )

    if table_exists("trade_events"):
        open_buys = get_scalar(
            """
            SELECT COUNT(*)
            FROM trade_events
            WHERE app_username = ?
              AND osrs_account_name = ?
              AND side = 'BUY'
              AND remaining_quantity > 0
            """,
            (
                scope["app_username"],
                scope["osrs_account_name"]
            ),
            default=0
        )

    ai_advice_modified = safe_file_modified_time(OUTPUT_FILE)
    ai_advice_size = 0

    try:
        if os.path.exists(OUTPUT_FILE):
            ai_advice_size = os.path.getsize(OUTPUT_FILE)
    except Exception:
        ai_advice_size = 0

    runelite_file = os.path.join(
        os.path.expanduser("~"),
        ".runelite",
        "flipping",
        f"{scope['osrs_account_name']}.json"
    )

    return {
        "Local User": scope["app_username"],
        "OSRS/RuneLite Account": scope["osrs_account_name"],
        "Database": DB_FILE,
        "RuneLite File": runelite_file,
        "RuneLite File Modified": safe_file_modified_time(runelite_file),
        "Latest Market Scan": latest_scan,
        "Latest Trade Import": latest_trade_import,
        "Latest Import Status": latest_import_status,
        "Latest Import Message": latest_import_message,
        "Latest Trade Event": latest_trade_event,
        "Completed Flips": completed_count,
        "Realized P/L": f"{int(realized_profit):,} gp",
        "Open Buy Rows": open_buys,
        "AI Advice File Modified": ai_advice_modified,
        "AI Advice File Size": f"{int(ai_advice_size):,} bytes",
        "Logs Folder": LOG_DIR
    }


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




# =========================
# MAINTENANCE HELPERS
# =========================

def safe_timestamp_for_filename():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_export_dirs():
    os.makedirs(EXPORT_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)


def get_account_file_prefix():
    scope = get_current_trade_scope()

    safe_user = "".join(
        char for char in scope["app_username"]
        if char.isalnum() or char in ("-", "_")
    ) or "user"

    safe_account = "".join(
        char for char in scope["osrs_account_name"]
        if char.isalnum() or char in ("-", "_")
    ) or "account"

    return f"{safe_user}_{safe_account}"


def backup_database_file():
    ensure_export_dirs()

    if not os.path.exists(DB_FILE):
        raise FileNotFoundError(f"Database not found: {DB_FILE}")

    timestamp = safe_timestamp_for_filename()
    backup_name = f"osrs_flip_scanner_backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    shutil.copy2(DB_FILE, backup_path)

    return backup_path


def export_dataframe_to_csv(df, filename):
    ensure_export_dirs()

    if df is None:
        df = pd.DataFrame()

    path = os.path.join(EXPORT_DIR, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig")

    return path


def export_completed_trades_csv():
    scope = get_current_trade_scope()
    prefix = get_account_file_prefix()
    timestamp = safe_timestamp_for_filename()

    df = query_df(
        """
        SELECT *
        FROM completed_trades
        WHERE app_username = ?
          AND osrs_account_name = ?
        ORDER BY sell_time DESC, id DESC
        """,
        (
            scope["app_username"],
            scope["osrs_account_name"]
        )
    )

    filename = f"{prefix}_completed_trades_{timestamp}.csv"
    return export_dataframe_to_csv(df, filename)


def export_trade_events_csv():
    scope = get_current_trade_scope()
    prefix = get_account_file_prefix()
    timestamp = safe_timestamp_for_filename()

    df = query_df(
        """
        SELECT *
        FROM trade_events
        WHERE app_username = ?
          AND osrs_account_name = ?
        ORDER BY traded_at DESC, id DESC
        """,
        (
            scope["app_username"],
            scope["osrs_account_name"]
        )
    )

    filename = f"{prefix}_trade_events_{timestamp}.csv"
    return export_dataframe_to_csv(df, filename)


def export_ai_notes_csv():
    scope = get_current_trade_scope()
    prefix = get_account_file_prefix()
    timestamp = safe_timestamp_for_filename()

    if not table_exists("ai_trade_notes"):
        df = pd.DataFrame()
    else:
        df = query_df(
            """
            SELECT *
            FROM ai_trade_notes
            WHERE app_username = ?
              AND osrs_account_name = ?
            ORDER BY created_at DESC, id DESC
            """,
            (
                scope["app_username"],
                scope["osrs_account_name"]
            )
        )

    filename = f"{prefix}_ai_notes_{timestamp}.csv"
    return export_dataframe_to_csv(df, filename)


def export_latest_scan_csv():
    latest_run_id = get_latest_run_id()
    timestamp = safe_timestamp_for_filename()

    if latest_run_id is None:
        df = pd.DataFrame()
    else:
        df = query_df(
            """
            SELECT *
            FROM scan_results
            WHERE run_id = ?
            ORDER BY recommendation_score DESC, total_profit DESC
            """,
            (latest_run_id,)
        )

    filename = f"latest_scan_run_{latest_run_id or 'none'}_{timestamp}.csv"
    return export_dataframe_to_csv(df, filename)



def optimize_database_file():
    """
    Creates a backup, then runs SQLite optimize and VACUUM.
    """
    backup_path = backup_database_file()

    conn = sqlite3.connect(DB_FILE)

    try:
        conn.execute("PRAGMA optimize")
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()

    return backup_path


def clear_current_account_ai_notes():
    """
    Clears AI feedback notes for the current app user / OSRS account only.
    A DB backup is created first.
    """
    backup_path = backup_database_file()
    scope = get_current_trade_scope()

    if not table_exists("ai_trade_notes"):
        return backup_path, 0

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM ai_trade_notes
        WHERE app_username = ?
          AND osrs_account_name = ?
        """,
        (
            scope["app_username"],
            scope["osrs_account_name"]
        )
    )

    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    return backup_path, deleted


def clear_log_files():
    """
    Truncates known log files. This does not delete the log folder.
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    known_logs = [
        "dashboard.log",
        "dashboard_error.log",
        "collector.log",
        "collector_error.log",
        "trade_watcher.log",
        "trade_watcher_error.log",
        "control_center.log",
        "control_center_error.log"
    ]

    cleared = 0

    for name in known_logs:
        path = os.path.join(LOG_DIR, name)

        if os.path.exists(path):
            with open(path, "w", encoding="utf-8") as file:
                file.write("")
            cleared += 1

    return cleared


def reset_ai_advice_file():
    """
    Moves the current AI advice text file into backups instead of deleting it.
    """
    ensure_export_dirs()

    if not os.path.exists(OUTPUT_FILE):
        return None

    timestamp = safe_timestamp_for_filename()
    backup_name = f"osrs_ai_advice_{timestamp}.txt"
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    shutil.move(OUTPUT_FILE, backup_path)

    return backup_path


def import_runelite_now():
    """
    Runs one immediate RuneLite import for the current account.
    Existing duplicate trades should be skipped by trade_importer.py.
    """
    scope = get_current_trade_scope()

    from trade_importer import import_runelite_file

    result = import_runelite_file(
        account=scope["osrs_account_name"],
        force=True
    )

    return result




def run_health_check_report():
    from health_check import run_health_check, REPORT_FILE

    text = run_health_check(write_report=True)

    return text, str(REPORT_FILE)



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


def setting_value(key, default=None):
    return get_setting(key, default if default is not None else DEFAULT_SETTINGS.get(key, {}).get("value"))


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



def get_setup_summary_items():
    scope = get_current_trade_scope()
    key_status = get_api_key_status()
    usage = get_ai_usage_summary()

    runelite_file = locate_runelite_file(scope["osrs_account_name"])
    runelite_found = runelite_file.exists()

    status_rows = [
        {
            "Step": "Local account",
            "Status": "Configured" if scope["app_username"] != "default" else "Needs setup",
            "Details": scope["app_username"]
        },
        {
            "Step": "RuneLite account",
            "Status": "Configured" if scope["osrs_account_name"] != "default" else "Needs setup",
            "Details": scope["osrs_account_name"]
        },
        {
            "Step": "RuneLite Flipping Utilities file",
            "Status": "Found" if runelite_found else "Not found",
            "Details": str(runelite_file)
        },
        {
            "Step": "Encrypted OpenAI API key",
            "Status": "Configured" if key_status.get("has_key") else "Missing",
            "Details": key_status.get("key_hint", "not set")
        },
        {
            "Step": "Daily AI request limit",
            "Status": "Configured",
            "Details": str(usage.get("daily_limit", get_setting("max_ai_requests_per_day", 20)))
        },
        {
            "Step": "Cash stack",
            "Status": "Configured",
            "Details": f"{int(get_setting('cash_stack', 0)):,} gp"
        },
        {
            "Step": "Minimum profit",
            "Status": "Configured",
            "Details": f"{int(get_setting('minimum_profit', 0)):,} gp"
        },
        {
            "Step": "Risk profile",
            "Status": "Configured",
            "Details": str(get_setting("risk_profile", "medium"))
        }
    ]

    return status_rows



# =========================
# ACCOUNT MANAGER TAB
# =========================

def get_account_manager_rows():
    rows = []

    try:
        users = list_users()
    except Exception:
        users = []

    current = get_current_session() or {}
    current_username = str(current.get("username") or "").strip().lower()

    for user in users:
        username = str(user.get("username") or "").strip().lower()

        rows.append({
            "Current": "Yes" if username == current_username else "",
            "Username": username,
            "RuneLite/OSRS Account": user.get("osrs_account_name", ""),
            "Created": user.get("created_at", ""),
            "Updated": user.get("updated_at", ""),
            "Last Login": user.get("last_login_at", "") or "Never"
        })

    return rows



# =========================
# TRADE SAFETY REVIEW TAB
# =========================

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




# =========================
# ABOUT / VERSION TAB
# =========================

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
        className="settings-card",
        children=children
    )


def settings_section(title, subtitle=None, children=None, footer=None):
    panel_children = [
        html.Div(title, className="section-title")
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
        className="panel settings-panel",
        children=panel_children
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


app.layout = html.Div(
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
            className="dash-tabs",
            children=[
                dcc.Tab(
                    label="Accounts",
                    className="tab",
                    selected_className="tab--selected",
                    children=[build_account_manager_tab()]
                ),

                dcc.Tab(
                    label="Overview",
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
                    className="tab",
                    selected_className="tab--selected",
                    children=[build_my_trades_tab()]
                ),

                dcc.Tab(
                    label="AI Advisor",
                    className="tab",
                    selected_className="tab--selected",
                    children=[build_ai_panel()]
                ),

                dcc.Tab(
                    label="Safety Review",
                    className="tab",
                    selected_className="tab--selected",
                    children=[build_safety_review_tab()]
                ),

                dcc.Tab(
                    label="Latest Flips",
                    className="tab",
                    selected_className="tab--selected",
                    children=[build_latest_table()]
                ),

                dcc.Tab(
                    label="Item History",
                    className="tab",
                    selected_className="tab--selected",
                    children=[
                        html.Div(
                            dcc.Graph(id="item-history-chart"),
                            className="panel chart-panel"
                        )
                    ]
                ),

                dcc.Tab(
                    label="Recurring Flips",
                    className="tab",
                    selected_className="tab--selected",
                    children=[build_recurring_table()]
                ),

                dcc.Tab(
                    label="Status / Logs",
                    className="tab",
                    selected_className="tab--selected",
                    children=[build_status_logs_tab()]
                ),

                dcc.Tab(
                    label="Maintenance",
                    className="tab",
                    selected_className="tab--selected",
                    children=[build_maintenance_tab()]
                ),

                dcc.Tab(
                    label="About",
                    className="tab",
                    selected_className="tab--selected",
                    children=[build_about_tab()]
                ),

                dcc.Tab(
                    label="Settings",
                    className="tab",
                    selected_className="tab--selected",
                    children=[build_settings_tab()]
                )
            ]
        )
    ]
)


# =========================
# TABLE HELPERS
# =========================

def format_display_number(value, decimals=0, suffix=""):
    if value is None or pd.isna(value):
        return ""

    try:
        number = float(value)
    except Exception:
        return str(value)

    if decimals == 0:
        text = f"{int(round(number)):,}"
    else:
        text = f"{number:,.{decimals}f}"

    return f"{text}{suffix}"


def format_display_bool(value):
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    text = str(value).strip().lower()
    if text in {"1", "true", "yes"}:
        return "Yes"
    if text in {"0", "false", "no"}:
        return "No"
    return str(value)


def format_latest_display_df(df):
    if df is None or df.empty:
        return pd.DataFrame()

    preferred = [
        ("recommendation", "Action"),
        ("recommendation_score", "Score"),
        ("risk_level", "Risk"),
        ("flip_category", "Category"),
        ("item_name", "Item"),
        ("window_name", "Window"),
        ("price_source", "Source"),
        ("target_buy", "Buy"),
        ("target_sell", "Sell"),
        ("raw_margin", "Raw Margin"),
        ("profit_per_item", "Net/Item"),
        ("quantity", "Qty"),
        ("total_profit", "Total Profit"),
        ("roi_percent", "ROI %"),
        ("volume", "Volume"),
        ("expected_fill_time", "Fill Time"),
        ("weekly_trend", "Trend"),
        ("trend_warning", "Warning"),
        ("why", "Why"),
    ]

    out = pd.DataFrame()

    for source, label in preferred:
        if source in df.columns:
            out[label] = df[source]

    money_columns = ["Buy", "Sell", "Raw Margin", "Net/Item", "Total Profit", "Volume", "Qty"]
    for column in money_columns:
        if column in out.columns:
            out[column] = out[column].apply(lambda value: format_display_number(value, decimals=0))

    if "Score" in out.columns:
        out["Score"] = out["Score"].apply(lambda value: format_display_number(value, decimals=2))

    if "ROI %" in out.columns:
        out["ROI %"] = out["ROI %"].apply(lambda value: format_display_number(value, decimals=2, suffix="%"))

    for column in ["Action", "Risk", "Category", "Item", "Window", "Source", "Fill Time", "Trend", "Warning", "Why"]:
        if column in out.columns:
            out[column] = out[column].fillna("").astype(str)

    return out


def format_recurring_display_df(df):
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()

    rename_map = {
        "Avg_Total_Profit": "Avg Profit",
        "Best_Total_Profit": "Best Profit",
        "Avg_Profit_Per_Item": "Avg Net/Item",
        "Avg_ROI_Percent": "Avg ROI %",
        "Avg_Volume": "Avg Volume",
        "Avg_Quick_Score": "Avg Quick",
        "Avg_Overnight_Score": "Avg Overnight",
        "Avg_Recommendation_Score": "Avg Score",
        "Last_Seen": "Last Seen",
    }

    df = df.rename(columns=rename_map)

    preferred = [
        "Item",
        "Window",
        "Appearances",
        "Avg Score",
        "Avg Profit",
        "Best Profit",
        "Avg Net/Item",
        "Avg ROI %",
        "Avg Volume",
        "Avg Quick",
        "Avg Overnight",
        "Last Seen",
    ]

    out = df[[column for column in preferred if column in df.columns]].copy()

    for column in ["Appearances", "Avg Profit", "Best Profit", "Avg Net/Item", "Avg Volume"]:
        if column in out.columns:
            out[column] = out[column].apply(lambda value: format_display_number(value, decimals=0))

    for column in ["Avg Score", "Avg ROI %", "Avg Quick", "Avg Overnight"]:
        if column in out.columns:
            suffix = "%" if column == "Avg ROI %" else ""
            out[column] = out[column].apply(lambda value: format_display_number(value, decimals=2, suffix=suffix))

    if "Last Seen" in out.columns:
        out["Last Seen"] = (
            out["Last Seen"]
            .astype(str)
            .str.replace("T", " ", regex=False)
            .str.replace("+00:00", "", regex=False)
        )

    return out



def build_latest_display_df(df):
    return format_latest_display_df(df)


# =========================
# CALLBACKS
# =========================

@app.callback(
    Output("kpi-cards", "children"),
    Output("top-profit-chart", "figure"),
    Output("quick-overnight-chart", "figure"),
    Output("trend-position-chart", "figure"),
    Output("roi-volume-chart", "figure"),
    Output("latest-table", "data"),
    Output("latest-table", "columns"),
    Output("recurring-table", "data"),
    Output("recurring-table", "columns"),
    Input("window-filter", "value"),
    Input("result-type-filter", "value"),
    Input("signal-filter", "value"),
    Input("category-filter", "value"),
    Input("trend-filter", "value"),
    Input("limit-filter", "value"),
    Input("auto-refresh", "n_intervals")
)
def update_dashboard(
    window_filter,
    result_type_filter,
    signal_filter,
    category_filter,
    trend_filter,
    limit,
    _
):
    df = get_filtered_latest(
        window_filter=window_filter,
        result_type_filter=result_type_filter,
        signal_filter=signal_filter,
        category_filter=category_filter,
        trend_filter=trend_filter,
        limit=limit
    )

    if df.empty:
        cards = [
            make_card("Best Profit", "0 gp", "run main.py or collector.py first"),
            make_card("Avg ROI", "N/A", "post-tax"),
            make_card("Best Net/Item", "0 gp", "post-tax"),
            make_card("Best Quick Score", "0", "active flips"),
            make_card("Overnight Qualified", "0", f"{OVERNIGHT_RAW_MARGIN_MIN:,}+ raw margin and {OVERNIGHT_ROI_MIN}%+ ROI"),
            make_card("Trend Warnings", "0", "current filters")
        ]

        recurring_df = get_best_recurring_flips(limit=limit)
        recurring_data = recurring_df.to_dict("records")
        recurring_columns = [{"name": column, "id": column} for column in recurring_df.columns]

        return (
            cards,
            empty_figure("Top Profit Opportunities"),
            empty_figure("Quick Score vs Overnight Score"),
            empty_figure("7-Day Price Position"),
            empty_figure("ROI vs Volume"),
            [],
            [],
            recurring_data,
            recurring_columns
        )

    best_profit = df["total_profit"].max() if "total_profit" in df.columns else 0
    avg_roi = df["roi_percent"].mean() if "roi_percent" in df.columns else 0
    best_net_item = df["profit_per_item"].max() if "profit_per_item" in df.columns else 0
    best_quick_score = df["quick_score"].max() if "quick_score" in df.columns else 0
    best_overnight_score = df["overnight_score"].max() if "overnight_score" in df.columns else 0

    overnight_qualified_count = 0

    if "overnight_qualified" in df.columns:
        overnight_qualified_count = int(df["overnight_qualified"].sum())

    trend_warning_count = 0

    if "trend_warning" in df.columns:
        trend_warning_count = len(df[df["trend_warning"].fillna("OK") != "OK"])

    cards = [
        make_card("Best Profit", f"{format_gp(best_profit)} gp", "best total profit in view"),
        make_card("Avg ROI", format_percent(avg_roi), "post-tax average"),
        make_card("Best Net/Item", f"{format_gp(best_net_item)} gp", "post-tax per item"),
        make_card("Best Quick Score", round(float(best_quick_score), 2), "active flipping strength"),
        make_card("Overnight Qualified", str(overnight_qualified_count), f"{OVERNIGHT_RAW_MARGIN_MIN:,}+ raw margin and {OVERNIGHT_ROI_MIN}%+ ROI"),
        make_card("Trend Warnings", str(trend_warning_count), f"best overnight score {round(float(best_overnight_score), 2)}")
    ]

    df = add_chart_size(df)
    chart_df = df.head(15).copy()

    top_profit_fig = px.bar(
        chart_df,
        x="item_name",
        y="total_profit",
        color="flip_category" if "flip_category" in chart_df.columns else None,
        hover_data=[
            column for column in [
                "window_name",
                "flip_category",
                "price_source",
                "target_buy",
                "target_sell",
                "quantity",
                "roi_percent",
                "quick_score",
                "overnight_score",
                "weekly_trend",
                "trend_warning"
            ]
            if column in chart_df.columns
        ],
        title="Top Profit Opportunities"
    )
    top_profit_fig.update_layout(xaxis_tickangle=-45)
    apply_dark_chart_layout(
        top_profit_fig,
        x_title="Item",
        y_title="Total Profit",
        bottom_margin=130
    )

    if "quick_score" in df.columns and "overnight_score" in df.columns:
        quick_overnight_fig = px.scatter(
            df,
            x="quick_score",
            y="overnight_score",
            size="chart_size" if "chart_size" in df.columns else None,
            color="flip_category" if "flip_category" in df.columns else None,
            hover_name="item_name",
            hover_data=[
                column for column in [
                    "window_name",
                    "expected_fill_time",
                    "liquidity_rating",
                    "weekly_trend",
                    "trend_warning",
                    "total_profit",
                    "roi_percent"
                ]
                if column in df.columns
            ],
            title="Quick Score vs Overnight Score"
        )
        apply_dark_chart_layout(
            quick_overnight_fig,
            x_title="Quick Score",
            y_title="Overnight Score"
        )
    else:
        quick_overnight_fig = empty_figure("Quick Score vs Overnight Score")

    if "price_position_7d_percent" in df.columns:
        trend_position_fig = px.scatter(
            df,
            x="price_position_7d_percent",
            y="weekly_change_percent" if "weekly_change_percent" in df.columns else "roi_percent",
            size="chart_size" if "chart_size" in df.columns else None,
            color="weekly_trend" if "weekly_trend" in df.columns else None,
            hover_name="item_name",
            hover_data=[
                column for column in [
                    "window_name",
                    "flip_category",
                    "seven_day_low",
                    "seven_day_high",
                    "trend_confidence",
                    "trend_warning",
                    "overnight_score"
                ]
                if column in df.columns
            ],
            title="7-Day Price Position vs Weekly Change"
        )
        apply_dark_chart_layout(
            trend_position_fig,
            x_title="Price Position in 7-Day Range %",
            y_title="Weekly Change %"
        )
    else:
        trend_position_fig = empty_figure("7-Day Price Position")

    roi_volume_fig = px.scatter(
        df,
        x="roi_percent",
        y="volume",
        size="chart_size" if "chart_size" in df.columns else None,
        color="flip_category" if "flip_category" in df.columns else None,
        hover_name="item_name",
        hover_data=[
            column for column in [
                "window_name",
                "price_source",
                "target_buy",
                "target_sell",
                "quantity",
                "total_profit",
                "signal",
                "confidence",
                "liquidity_score",
                "expected_fill_time"
            ]
            if column in df.columns
        ],
        title="ROI vs Volume"
    )
    apply_dark_chart_layout(
        roi_volume_fig,
        x_title="ROI %",
        y_title="Window Volume"
    )

    display_df = build_latest_display_df(df)

    recurring_df = get_best_recurring_flips(limit=limit)

    latest_data = display_df.to_dict("records")
    latest_columns = [{"name": column, "id": column} for column in display_df.columns]

    recurring_data = recurring_df.to_dict("records")
    recurring_columns = [{"name": column, "id": column} for column in recurring_df.columns]

    return (
        cards,
        top_profit_fig,
        quick_overnight_fig,
        trend_position_fig,
        roi_volume_fig,
        latest_data,
        latest_columns,
        recurring_data,
        recurring_columns
    )


@app.callback(
    Output("item-history-chart", "figure"),
    Input("item-dropdown", "value"),
    Input("auto-refresh", "n_intervals")
)
def update_item_history(selected_item, _):
    if not selected_item:
        return empty_figure("Select an item to view margin history")

    df = get_all_history()

    if df.empty:
        return empty_figure("Item Margin History")

    item_df = df[df["item_name"] == selected_item].copy()

    if item_df.empty:
        return empty_figure(f"No history for {selected_item}")

    item_df = item_df.sort_values("scanned_at")

    y_columns = ["raw_margin"]

    for column in ["quick_score", "overnight_score"]:
        if column in item_df.columns:
            # Keep raw margin as primary chart because it is the historical money signal.
            # Quick/overnight values are available in hover.
            pass

    fig = px.line(
        item_df,
        x="scanned_at",
        y="raw_margin",
        color="window_name",
        hover_data=[
            column for column in [
                "price_source",
                "target_buy",
                "target_sell",
                "profit_per_item",
                "total_profit",
                "roi_percent",
                "volume",
                "signal",
                "flip_category",
                "quick_score",
                "overnight_score",
                "daily_trend",
                "weekly_trend",
                "trend_warning"
            ]
            if column in item_df.columns
        ],
        title=f"Margin History: {selected_item}"
    )

    apply_dark_chart_layout(
        fig,
        x_title="Scan Time",
        y_title="Raw Margin"
    )

    return fig



@app.callback(
    Output("trade-import-status", "children"),
    Output("trade-kpi-cards", "children"),
    Output("trade-profit-chart", "figure"),
    Output("trade-item-profit-chart", "figure"),
    Output("completed-trades-table", "data"),
    Output("completed-trades-table", "columns"),
    Output("open-trades-table", "data"),
    Output("open-trades-table", "columns"),
    Input("refresh-trades-button", "n_clicks"),
    Input("auto-refresh", "n_intervals"),
    State("my-trades-limit", "value")
)
def update_trade_dashboard(refresh_clicks, intervals, row_limit):
    import_status = refresh_runelite_trades_for_dashboard()
    limit = parse_positive_int(row_limit, default=100, minimum=10, maximum=500)

    summary = get_trade_summary()

    cards = [
        make_card("Realized P/L", f"{format_gp(summary.get('realized_profit', 0))} gp", "matched completed flips"),
        make_card("Completed Flips", str(int(summary.get("completed_count", 0))), "buy/sell pairs matched"),
        make_card("Average ROI", format_percent(summary.get("avg_roi", 0)), "completed flips"),
        make_card("Best Trade", f"{format_gp(summary.get('best_trade', 0))} gp", "single matched flip"),
        make_card("Worst Trade", f"{format_gp(summary.get('worst_trade', 0))} gp", "single matched flip"),
        make_card("Open Buy Value", f"{format_gp(summary.get('open_buy_value', 0))} gp", f"{int(summary.get('open_event_count', 0))} open events")
    ]

    history_df = get_completed_trade_history()

    if history_df.empty:
        profit_fig = empty_figure("Cumulative Realized Profit")
        item_fig = empty_figure("Profit by Item")
    else:
        profit_fig = px.line(
            history_df,
            x="sell_time",
            y="cumulative_profit",
            hover_data=["item_name", "total_profit", "roi_percent"],
            title="Cumulative Realized Profit"
        )
        apply_dark_chart_layout(
            profit_fig,
            x_title="Sell Time",
            y_title="Cumulative Profit"
        )

        item_df = history_df.groupby("item_name", as_index=False)["total_profit"].sum()
        item_df = item_df.sort_values("total_profit", ascending=False).head(15)

        item_fig = px.bar(
            item_df,
            x="item_name",
            y="total_profit",
            title="Profit by Item"
        )
        item_fig.update_layout(xaxis_tickangle=-45)
        apply_dark_chart_layout(
            item_fig,
            x_title="Item",
            y_title="Total Profit",
            bottom_margin=130
        )

    completed_df = clean_trade_display_df(get_completed_trade_rows(limit=limit))
    open_df = clean_trade_display_df(get_open_trade_rows(limit=limit))

    completed_data = completed_df.to_dict("records")
    completed_columns = trade_table_columns(completed_df)

    open_data = open_df.to_dict("records")
    open_columns = trade_table_columns(open_df)

    return (
        import_status,
        cards,
        profit_fig,
        item_fig,
        completed_data,
        completed_columns,
        open_data,
        open_columns
    )

@app.callback(
    Output("ai-advice-output", "children"),
    Output("ai-status", "children"),
    Input("generate-ai-button", "n_clicks"),
    State("ai-risk-profile", "value"),
    State("ai-limit", "value"),
    prevent_initial_call=True
)
def update_ai_advice(n_clicks, risk_profile, limit):
    if not n_clicks:
        return read_saved_ai_advice(), ""

    try:
        advice = generate_ai_advice(
            risk_profile=risk_profile,
            limit=limit
        )

        status = (
            "AI advice generated successfully. "
            f"Risk profile: {risk_profile}. "
            f"Candidate source limit: {limit}."
        )

        return advice, status

    except Exception as error:
        return (
            read_saved_ai_advice(),
            f"AI advice failed: {error}"
        )



@app.callback(
    Output("trade-account-scope", "children"),
    Input("auto-refresh", "n_intervals")
)
def update_trade_account_scope(_):
    scope = get_current_trade_scope()
    return f"Showing trades for local user: {scope['app_username']} | OSRS/RuneLite account: {scope['osrs_account_name']}"




@app.callback(
    Output("openai-key-status", "children"),
    Input("auto-refresh", "n_intervals")
)
def update_openai_key_status(_):
    status = get_api_key_status()

    if not status.get("has_key"):
        return (
            "No saved OpenAI API key for this account. "
            "AI Advisor will use .env fallback only if one exists."
        )

    return (
        f"Saved key: {status.get('key_hint')} | "
        f"Updated: {status.get('updated_at') or 'n/a'} | "
        f"Last used: {status.get('last_used_at') or 'n/a'}"
    )


@app.callback(
    Output("openai-usage-status", "children"),
    Input("auto-refresh", "n_intervals")
)
def update_openai_usage_status(_):
    init_ai_usage_db()
    summary = get_ai_usage_summary()

    today = summary["today"]
    all_time = summary["all_time"]
    limit = summary["daily_limit"]

    return (
        f"AI usage today: {today.get('total_requests', 0)}/{limit} requests, "
        f"{int(today.get('total_tokens', 0) or 0):,} tokens. "
        f"All time: {all_time.get('total_requests', 0)} requests, "
        f"{int(all_time.get('total_tokens', 0) or 0):,} tokens."
    )


@app.callback(
    Output("openai-key-action-status", "children"),
    Output("setting-openai-api-key", "value"),
    Input("save-openai-key-button", "n_clicks"),
    Input("delete-openai-key-button", "n_clicks"),
    State("setting-openai-api-key", "value"),
    State("confirm-delete-openai-key", "value"),
    prevent_initial_call=True
)
def save_or_delete_openai_key(save_clicks, delete_clicks, api_key, confirm_delete):
    triggered_id = ctx.triggered_id

    try:
        if triggered_id == "save-openai-key-button":
            api_key = str(api_key or "").strip()
            valid, message = validate_key_shape(api_key)

            if not valid:
                return f"Key was not saved: {message}", ""

            result = save_api_key(api_key)
            return f"Encrypted OpenAI API key saved for this account: {result['key_hint']}", ""

        if triggered_id == "delete-openai-key-button":
            if str(confirm_delete or "").strip() != "DELETE API KEY":
                return "Type DELETE API KEY before deleting the saved key.", ""

            deleted = delete_api_key()
            return f"Deleted saved OpenAI API key rows: {deleted}", ""

        return "No API key action selected.", ""

    except Exception as error:
        return f"API key action failed: {error}", ""


@app.callback(
    Output("settings-account-scope", "children"),
    Input("auto-refresh", "n_intervals")
)
def update_settings_account_scope(_):
    scope = get_current_trade_scope()
    return f"Settings are saved for local user: {scope['app_username']} | OSRS/RuneLite account: {scope['osrs_account_name']}"


@app.callback(
    Output("core-settings-status", "children"),
    Input("save-core-settings-button", "n_clicks"),
    State("setting-cash-stack", "value"),
    State("setting-minimum-profit", "value"),
    State("setting-risk-profile", "value"),
    State("setting-watch-seconds", "value"),
    State("setting-start-dashboard", "value"),
    State("setting-start-collector", "value"),
    State("setting-start-trade-watcher", "value"),
    State("setting-open-browser", "value"),
    prevent_initial_call=True
)
def save_core_settings(n_clicks, cash_stack, minimum_profit, risk_profile, watch_seconds, start_dashboard, start_collector, start_trade_watcher, open_browser):
    if not n_clicks:
        return ""

    try:
        set_setting("cash_stack", int(cash_stack or 0), "int")
        set_setting("minimum_profit", int(minimum_profit or 0), "int")
        set_setting("risk_profile", risk_profile or "medium", "str")
        set_setting("watch_seconds", int(watch_seconds or 10), "int")
        set_setting("start_dashboard", start_dashboard == "true", "bool")
        set_setting("start_collector", start_collector == "true", "bool")
        set_setting("start_trade_watcher", start_trade_watcher == "true", "bool")
        set_setting("open_browser", open_browser == "true", "bool")

        return "Startup / collector settings saved. Restart the control center for startup changes to take effect."

    except Exception as error:
        return f"Settings save failed: {error}"


@app.callback(
    Output("ai-settings-status", "children"),
    Input("save-ai-settings-button", "n_clicks"),
    State("setting-ai-source-row-limit", "value"),
    State("setting-ai-quick-choices", "value"),
    State("setting-ai-overnight-choices", "value"),
    State("setting-ai-value-choices", "value"),
    State("setting-exclude-items-traded-today", "value"),
    State("setting-max-ai-requests-per-day", "value"),
    State("setting-min-overnight-raw-margin", "value"),
    State("setting-min-overnight-roi-percent", "value"),
    State("setting-max-small-loss-percent", "value"),
    State("setting-max-medium-loss-percent", "value"),
    prevent_initial_call=True
)
def save_ai_settings(n_clicks, source_limit, quick_choices, overnight_choices, value_choices, exclude_today, max_ai_requests, min_margin, min_roi, small_loss, medium_loss):
    if not n_clicks:
        return ""

    try:
        set_setting("ai_source_row_limit", int(source_limit or 350), "int")
        set_setting("ai_quick_choices", int(quick_choices or 10), "int")
        set_setting("ai_overnight_choices", int(overnight_choices or 10), "int")
        set_setting("ai_value_choices", int(value_choices or 10), "int")
        set_setting("exclude_items_traded_today", exclude_today == "true", "bool")
        set_setting("max_ai_requests_per_day", int(max_ai_requests or 0), "int")
        set_setting("min_overnight_raw_margin", int(min_margin or 10000), "int")
        set_setting("min_overnight_roi_percent", float(min_roi or 5.0), "float")
        set_setting("max_small_loss_percent", float(small_loss or 2.0), "float")
        set_setting("max_medium_loss_percent", float(medium_loss or 5.0), "float")

        return "AI settings saved. New AI runs will use these values."

    except Exception as error:
        return f"AI settings save failed: {error}"



@app.callback(
    Output("status-log-cards", "children"),
    Input("auto-refresh", "n_intervals")
)
def update_status_log_cards(_):
    summary = get_status_summary()
    return build_status_cards(summary)


@app.callback(
    Output("log-file-output", "children"),
    Input("log-file-select", "value"),
    Input("log-line-count", "value"),
    Input("auto-refresh", "n_intervals")
)
def update_log_file_output(log_file_name, line_count, _):
    if not log_file_name:
        return "No log file selected."

    safe_name = os.path.basename(log_file_name)
    log_path = os.path.join(LOG_DIR, safe_name)

    return read_last_lines(log_path, max_lines=int(line_count or 80))



@app.callback(
    Output("maintenance-status", "children"),
    Output("maintenance-download", "data"),
    Output("health-check-output", "children"),
    Output("release-check-output", "children"),
    Output("backup-release-status", "children"),
    Input("backup-database-button", "n_clicks"),
    Input("run-health-check-button", "n_clicks"),
    Input("optimize-database-button", "n_clicks"),
    Input("run-migrations-button", "n_clicks"),
    Input("run-release-check-button", "n_clicks"),
    Input("create-private-backup-button", "n_clicks"),
    Input("prepare-clean-release-button", "n_clicks"),
    Input("update-installer-dry-run-button", "n_clicks"),
    Input("import-runelite-now-button", "n_clicks"),
    Input("export-completed-trades-button", "n_clicks"),
    Input("export-trade-events-button", "n_clicks"),
    Input("export-ai-notes-button", "n_clicks"),
    Input("export-latest-scan-button", "n_clicks"),
    Input("clear-ai-notes-button", "n_clicks"),
    Input("clear-logs-button", "n_clicks"),
    Input("reset-ai-advice-button", "n_clicks"),
    State("confirm-clear-ai-notes", "value"),
    State("confirm-clear-logs", "value"),
    State("confirm-reset-ai-advice", "value"),
    prevent_initial_call=True
)
def run_maintenance_action(
    backup_clicks,
    health_check_clicks,
    optimize_clicks,
    migration_clicks,
    release_check_clicks,
    private_backup_clicks,
    prepare_release_clicks,
    update_installer_dry_run_clicks,
    import_runelite_clicks,
    completed_clicks,
    events_clicks,
    notes_clicks,
    scan_clicks,
    clear_ai_notes_clicks,
    clear_logs_clicks,
    reset_ai_advice_clicks,
    confirm_clear_ai_notes,
    confirm_clear_logs,
    confirm_reset_ai_advice
):
    triggered_id = ctx.triggered_id

    if not triggered_id:
        return "No action selected.", no_update, no_update, no_update, no_update

    try:
        if triggered_id == "backup-database-button":
            path = backup_database_file()
            return f"Database backup created: {path}", no_update, no_update, no_update, no_update

        if triggered_id == "run-health-check-button":
            text, report_path = run_health_check_report()
            return f"Health check complete. Report saved to: {report_path}", no_update, text, no_update, no_update

        if triggered_id == "optimize-database-button":
            backup_path = optimize_database_file()
            return f"Database optimized. Backup created first: {backup_path}", no_update, no_update, no_update, no_update

        if triggered_id == "run-migrations-button":
            result = run_app_migrations(force=True, write_report=True)
            return f"Database repair/migrations complete. Report: {result.get('report_path')}", no_update, no_update, no_update, no_update

        if triggered_id == "run-release-check-button":
            result = run_release_check(strict=False, write_report=True)
            status = result.get("status", "UNKNOWN")
            report_path = result.get("report_path", "")
            return f"Release check finished with status {status}. Report: {report_path}", no_update, no_update, result.get("report", ""), no_update

        if triggered_id == "create-private-backup-button":
            result = create_private_backup(reason="dashboard")
            message = (
                f"Private backup created: {result.get('path')} | "
                f"files: {result.get('file_count')} | "
                f"missing optional files: {result.get('missing_count')}. "
                "Do not share this backup publicly."
            )
            return "Private backup complete.", no_update, no_update, no_update, message

        if triggered_id == "prepare-clean-release-button":
            result = prepare_clean_release_package(include_exe=True, zip_release=True, run_check=True)
            message = (
                f"Clean release folder: {result.get('release_dir')} | "
                f"zip: {result.get('zip_path')} | "
                f"files: {result.get('file_count')} | "
                f"warnings: {result.get('warning_count')} | "
                f"missing: {result.get('missing_count')}. "
                "Private database, .env, logs, backups, exports, and runtime files are excluded."
            )
            return "Clean release package prepared.", no_update, no_update, no_update, message

        if triggered_id == "update-installer-dry-run-button":
            result = install_update(
                source_root=BASE_DIR,
                target_root=BASE_DIR,
                dry_run=True,
                no_backup=True,
                no_migrations=True,
                no_release_check=True,
                allow_same_folder=True
            )
            message = (
                f"Update installer dry run complete. "
                f"Would copy {len(result.get('copied_files', []))} release files. "
                "No files were changed."
            )
            return "Update installer dry run complete.", no_update, no_update, no_update, message

        if triggered_id == "import-runelite-now-button":
            result = import_runelite_now()
            return (
                "RuneLite import finished: "
                f"imported {result.get('imported', 0)}, "
                f"skipped {result.get('skipped', 0)}, "
                f"matched {result.get('matched', 0)}. "
                f"File: {result.get('file', '')}"
            ), no_update, no_update, no_update, no_update

        if triggered_id == "export-completed-trades-button":
            path = export_completed_trades_csv()
            return f"Completed trades exported: {path}", dcc.send_file(path), no_update, no_update, no_update

        if triggered_id == "export-trade-events-button":
            path = export_trade_events_csv()
            return f"Trade events exported: {path}", dcc.send_file(path), no_update, no_update, no_update

        if triggered_id == "export-ai-notes-button":
            path = export_ai_notes_csv()
            return f"AI notes exported: {path}", dcc.send_file(path), no_update, no_update, no_update

        if triggered_id == "export-latest-scan-button":
            path = export_latest_scan_csv()
            return f"Latest scan exported: {path}", dcc.send_file(path), no_update, no_update, no_update

        if triggered_id == "clear-ai-notes-button":
            if str(confirm_clear_ai_notes or "").strip() != "CLEAR AI NOTES":
                return "Type CLEAR AI NOTES before clearing current account AI notes.", no_update, no_update, no_update, no_update

            backup_path, deleted = clear_current_account_ai_notes()
            return f"Cleared {deleted} AI notes for the current account. Backup created first: {backup_path}", no_update, no_update, no_update, no_update

        if triggered_id == "clear-logs-button":
            if str(confirm_clear_logs or "").strip() != "CLEAR LOGS":
                return "Type CLEAR LOGS before clearing logs.", no_update, no_update, no_update, no_update

            cleared = clear_log_files()
            return f"Cleared {cleared} log files.", no_update, no_update, no_update, no_update

        if triggered_id == "reset-ai-advice-button":
            if str(confirm_reset_ai_advice or "").strip() != "RESET AI":
                return "Type RESET AI before resetting saved AI advice.", no_update, no_update, no_update, no_update

            backup_path = reset_ai_advice_file()

            if backup_path:
                return f"Saved AI advice moved to backup: {backup_path}", no_update, no_update, no_update, no_update

            return "No saved AI advice file existed to reset.", no_update, no_update, no_update, no_update

        return "Unknown maintenance action.", no_update, no_update, no_update, no_update

    except Exception as error:
        return f"Maintenance action failed: {error}", no_update, no_update, no_update, no_update



@app.callback(
    Output("setup-checklist-table", "data"),
    Input("auto-refresh", "n_intervals")
)
def update_setup_checklist(_):
    return get_setup_summary_items()


@app.callback(
    Output("setup-api-key-status", "children"),
    Output("setup-openai-api-key", "value"),
    Input("setup-save-openai-key-button", "n_clicks"),
    State("setup-openai-api-key", "value"),
    prevent_initial_call=True
)
def setup_save_openai_key(n_clicks, api_key):
    if not n_clicks:
        return "", ""

    try:
        api_key = str(api_key or "").strip()
        valid, message = validate_key_shape(api_key)

        if not valid:
            return f"Key was not saved: {message}", ""

        result = save_api_key(api_key)
        return f"Encrypted OpenAI API key saved: {result['key_hint']}", ""

    except Exception as error:
        return f"Could not save OpenAI API key: {error}", ""


@app.callback(
    Output("setup-settings-status", "children"),
    Input("setup-save-settings-button", "n_clicks"),
    State("setup-cash-stack", "value"),
    State("setup-minimum-profit", "value"),
    State("setup-risk-profile", "value"),
    State("setup-max-ai-requests", "value"),
    prevent_initial_call=True
)
def setup_save_quick_settings(n_clicks, cash_stack, minimum_profit, risk_profile, max_ai_requests):
    if not n_clicks:
        return ""

    try:
        set_setting("cash_stack", int(cash_stack or 0), "int")
        set_setting("minimum_profit", int(minimum_profit or 0), "int")
        set_setting("risk_profile", str(risk_profile or "medium"), "str")
        set_setting("max_ai_requests_per_day", int(max_ai_requests or 0), "int")

        return "Setup settings saved."

    except Exception as error:
        return f"Could not save setup settings: {error}"



@app.callback(
    Output("account-manager-users-table", "data"),
    Output("account-manager-current-user", "children"),
    Input("auto-refresh", "n_intervals")
)
def update_account_manager_table(_):
    current = get_current_session() or {}
    current_text = (
        f"Current session: {current.get('username', 'none')} / "
        f"{current.get('osrs_account_name', 'none')}"
    )

    return get_account_manager_rows(), current_text


@app.callback(
    Output("account-switch-status", "children"),
    Input("account-switch-button", "n_clicks"),
    State("account-switch-username", "value"),
    State("account-switch-password", "value"),
    prevent_initial_call=True
)
def switch_dashboard_user(n_clicks, username, password):
    if not n_clicks:
        return ""

    username = str(username or "").strip().lower()
    password = str(password or "")

    if not username or not password:
        return "Enter username and password."

    user = authenticate_user(username, password)

    if not user:
        return "Invalid username or password."

    save_session(user)
    apply_account_env(
        app_username=user["username"],
        osrs_account_name=user["osrs_account_name"]
    )

    return (
        f"Switched dashboard session to {user['username']} / {user['osrs_account_name']}. "
        "Restart the control center so collector and trade watcher use this account too."
    )


@app.callback(
    Output("account-create-status", "children"),
    Input("account-create-button", "n_clicks"),
    State("account-create-username", "value"),
    State("account-create-password", "value"),
    State("account-create-confirm-password", "value"),
    State("account-create-osrs-account", "value"),
    prevent_initial_call=True
)
def create_dashboard_user(n_clicks, username, password, confirm_password, osrs_account_name):
    if not n_clicks:
        return ""

    username = str(username or "").strip().lower()
    password = str(password or "")
    confirm_password = str(confirm_password or "")
    osrs_account_name = str(osrs_account_name or "").strip()

    if not username:
        return "Username is required."

    if not osrs_account_name:
        return "RuneLite/OSRS account name is required."

    if password != confirm_password:
        return "Passwords do not match."

    if len(password) < 6:
        return "Password must be at least 6 characters."

    try:
        user = create_user(
            username=username,
            password=password,
            osrs_account_name=osrs_account_name
        )

        authenticated = authenticate_user(username, password)

        if authenticated:
            save_session(authenticated)
            apply_account_env(
                app_username=authenticated["username"],
                osrs_account_name=authenticated["osrs_account_name"]
            )

        return (
            f"Created user {user['username']} linked to {user['osrs_account_name']}. "
            "Add this user's OpenAI key in Setup or Settings."
        )

    except Exception as error:
        return f"Could not create user: {error}"


@app.callback(
    Output("account-update-status", "children"),
    Input("account-update-button", "n_clicks"),
    State("account-update-username", "value"),
    State("account-update-osrs-account", "value"),
    prevent_initial_call=True
)
def update_dashboard_user_osrs_account(n_clicks, username, osrs_account_name):
    if not n_clicks:
        return ""

    username = str(username or "").strip().lower()
    osrs_account_name = str(osrs_account_name or "").strip()

    if not username or not osrs_account_name:
        return "Enter username and new RuneLite/OSRS account name."

    try:
        user = update_osrs_account(username, osrs_account_name)
        current = get_current_session() or {}

        if str(current.get("username") or "").strip().lower() == username:
            apply_account_env(
                app_username=user["username"],
                osrs_account_name=user["osrs_account_name"]
            )

        return (
            f"Updated {user['username']} to linked RuneLite/OSRS account {user['osrs_account_name']}. "
            "Restart the control center if collector/trade watcher are running."
        )

    except Exception as error:
        return f"Could not update linked account: {error}"



@app.callback(
    Output("openai-key-test-status", "children"),
    Input("test-openai-key-button", "n_clicks"),
    prevent_initial_call=True
)
def test_settings_openai_key(n_clicks):
    if not n_clicks:
        return ""

    result = test_current_account_openai_key()
    prefix = "PASS" if result.get("ok") else "FAIL"

    return f"{prefix}: {result.get('message', '')}"


@app.callback(
    Output("setup-api-key-test-status", "children"),
    Input("setup-test-openai-key-button", "n_clicks"),
    prevent_initial_call=True
)
def test_setup_openai_key(n_clicks):
    if not n_clicks:
        return ""

    result = test_current_account_openai_key()
    prefix = "PASS" if result.get("ok") else "FAIL"

    return f"{prefix}: {result.get('message', '')}"



@app.callback(
    Output("safety-review-table", "data"),
    Output("safety-review-table", "columns"),
    Output("safety-review-status", "children"),
    Input("refresh-safety-review-button", "n_clicks"),
    Input("auto-refresh", "n_intervals"),
    State("safety-review-limit", "value"),
    State("safety-max-cash-percent", "value"),
    State("safety-max-test-quantity", "value")
)
def update_safety_review_table(refresh_clicks, intervals, limit, max_cash_percent, max_test_quantity):
    try:
        set_setting("max_single_item_cash_percent", float(max_cash_percent or 10.0), "float")
        set_setting("max_test_quantity", int(max_test_quantity or 25), "int")

        df = build_safety_review(limit=int(limit or 100))

        if df.empty:
            return [], [], "No scan rows found yet. Run the collector/scanner first."

        columns = [{"name": column, "id": column} for column in df.columns]
        return df.to_dict("records"), columns, f"Safety review loaded: {len(df)} candidates."

    except Exception as error:
        return [], [], f"Safety review failed: {error}"


@app.callback(
    Output("safety-review-download", "data"),
    Input("export-safety-review-button", "n_clicks"),
    State("safety-review-limit", "value"),
    prevent_initial_call=True
)
def export_safety_review(n_clicks, limit):
    if not n_clicks:
        return no_update

    try:
        path, df = write_safety_review(limit=int(limit or 100))
        return dcc.send_file(str(path))

    except Exception:
        return no_update


if __name__ == "__main__":
    app.run(
        debug=True,
        dev_tools_ui=False
    )
