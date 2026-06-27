"""
Data, database, status, export, and maintenance helpers for the OSRSFlipper dashboard.
"""
import os
import sqlite3
import shutil
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from account_context import BASE_DIR as APP_BASE_DIR, get_account_scope
from account_manager import get_current_session, list_users
from advisor import OUTPUT_FILE
from database import init_db
from first_run_setup import locate_runelite_file
from openai_key_manager import get_api_key_status
from openai_usage_manager import get_ai_usage_summary
from settings_manager import get_setting, DEFAULT_SETTINGS

from dashboard_formatters import (
    parse_positive_int,
    format_recurring_display_df,
    summarize_import_result,
)

try:
    from trade_tracker import init_trade_db
except Exception:
    init_trade_db = None


BASE_DIR = str(APP_BASE_DIR)
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

# SQLite can briefly lock when the collector/scanner is writing while the
# dashboard is refreshing. These settings make dashboard reads wait and retry
# instead of immediately printing noisy "database is locked" errors.
SQLITE_TIMEOUT_SECONDS = 30
SQLITE_BUSY_TIMEOUT_MS = 30000
SQLITE_LOCK_RETRIES = 3

# 1.0.4 dashboard performance cache.
# Keep this intentionally short-lived so the dashboard stays responsive while
# still picking up new scan results quickly.
DASHBOARD_CACHE_TTL_SECONDS = 30
ITEM_OPTIONS_CACHE_TTL_SECONDS = 900
RECURRING_SCAN_RUN_WINDOW = 90
MAX_HISTORY_ROWS_DEFAULT = 50000

_dashboard_cache = {}


def _cache_get(cache_key, ttl_seconds):
    cached = _dashboard_cache.get(cache_key)

    if not cached:
        return None

    created_at, value = cached

    if time.time() - created_at > ttl_seconds:
        _dashboard_cache.pop(cache_key, None)
        return None

    if isinstance(value, pd.DataFrame):
        return value.copy()

    if isinstance(value, list):
        return list(value)

    return value


def _cache_set(cache_key, value):
    if isinstance(value, pd.DataFrame):
        value = value.copy()

    if isinstance(value, list):
        value = list(value)

    _dashboard_cache[cache_key] = (time.time(), value)

    if isinstance(value, pd.DataFrame):
        return value.copy()

    if isinstance(value, list):
        return list(value)

    return value


def clear_dashboard_cache():
    _dashboard_cache.clear()



# 1.0.4 My Trades cache.
# RuneLite imports can be slow, so the dashboard should not run the importer on
# initial load or every auto-refresh. These cached reads keep the tab responsive.
TRADE_DASHBOARD_CACHE_TTL_SECONDS = 30

_trade_dashboard_cache = {}


def _trade_cache_get(cache_key, ttl_seconds=TRADE_DASHBOARD_CACHE_TTL_SECONDS):
    cached = _trade_dashboard_cache.get(cache_key)

    if not cached:
        return None

    created_at, value = cached

    if time.time() - created_at > ttl_seconds:
        _trade_dashboard_cache.pop(cache_key, None)
        return None

    if isinstance(value, pd.DataFrame):
        return value.copy()

    if isinstance(value, dict):
        return dict(value)

    return value


def _trade_cache_set(cache_key, value):
    if isinstance(value, pd.DataFrame):
        value = value.copy()

    if isinstance(value, dict):
        value = dict(value)

    _trade_dashboard_cache[cache_key] = (time.time(), value)

    if isinstance(value, pd.DataFrame):
        return value.copy()

    if isinstance(value, dict):
        return dict(value)

    return value


def clear_trade_dashboard_cache():
    _trade_dashboard_cache.clear()

def open_dashboard_connection(read_only=True):
    conn = sqlite3.connect(DB_FILE, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")

    if read_only:
        try:
            conn.execute("PRAGMA query_only = ON")
        except Exception:
            # Older SQLite builds may not support query_only. Normal reads still work.
            pass

    return conn


def db_exists():
    return os.path.exists(DB_FILE)


def query_df(query, params=None):
    if params is None:
        params = ()

    if not db_exists():
        return pd.DataFrame()

    last_error = None

    for attempt in range(SQLITE_LOCK_RETRIES):
        conn = None

        try:
            conn = open_dashboard_connection(read_only=True)
            return pd.read_sql_query(query, conn, params=params)
        except sqlite3.OperationalError as error:
            last_error = error

            if "database is locked" in str(error).lower() and attempt < SQLITE_LOCK_RETRIES - 1:
                time.sleep(0.35 * (attempt + 1))
                continue

            break
        except Exception as error:
            last_error = error
            break
        finally:
            if conn is not None:
                conn.close()

    print("Dashboard database query failed:")
    print(last_error)
    print(query)
    return pd.DataFrame()


def get_latest_run_id():
    cached = _cache_get("latest_run_id", DASHBOARD_CACHE_TTL_SECONDS)

    if cached is not None:
        return cached

    df = query_df("""
        SELECT MAX(run_id) AS latest_run_id
        FROM scan_results
    """)

    if df.empty or pd.isna(df.loc[0, "latest_run_id"]):
        return None

    return _cache_set("latest_run_id", int(df.loc[0, "latest_run_id"]))


def get_latest_rows():
    latest_run_id = get_latest_run_id()

    if latest_run_id is None:
        return pd.DataFrame()

    cache_key = ("latest_rows", latest_run_id)
    cached = _cache_get(cache_key, DASHBOARD_CACHE_TTL_SECONDS)

    if cached is not None:
        return cached

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

    return _cache_set(cache_key, df)


def get_all_history(limit=MAX_HISTORY_ROWS_DEFAULT):
    # Return recent scan history without loading the entire database.
    # Use get_item_history_for_item() when a chart needs one item's full history.
    limit = parse_positive_int(
        limit,
        default=MAX_HISTORY_ROWS_DEFAULT,
        minimum=1000,
        maximum=200000
    )

    cache_key = ("all_history_recent", limit)
    cached = _cache_get(cache_key, DASHBOARD_CACHE_TTL_SECONDS)

    if cached is not None:
        return cached

    df = query_df("""
        SELECT *
        FROM scan_results
        ORDER BY scanned_at DESC, id DESC
        LIMIT ?
    """, (limit,))

    if not df.empty and "scanned_at" in df.columns:
        df["scanned_at"] = pd.to_datetime(df["scanned_at"], errors="coerce")
        df = df.sort_values("scanned_at")

    return _cache_set(cache_key, df)


def get_item_history_for_item(item_name, limit=5000):
    # Fast path for Item History charts.
    item_name = str(item_name or "").strip()

    if not item_name:
        return pd.DataFrame()

    limit = parse_positive_int(limit, default=5000, minimum=100, maximum=50000)
    cache_key = ("item_history", item_name.lower(), limit)
    cached = _cache_get(cache_key, DASHBOARD_CACHE_TTL_SECONDS)

    if cached is not None:
        return cached

    df = query_df("""
        SELECT *
        FROM scan_results
        WHERE item_name = ?
        ORDER BY scanned_at ASC, id ASC
        LIMIT ?
    """, (item_name, limit))

    if not df.empty and "scanned_at" in df.columns:
        df["scanned_at"] = pd.to_datetime(df["scanned_at"], errors="coerce")

    return _cache_set(cache_key, df)


def get_best_recurring_flips(limit=25):
    # Find recurring profitable items using a recent scan window instead of
    # grouping the full historical scan_results table on every dashboard refresh.
    limit = parse_positive_int(limit, default=25, minimum=5, maximum=500)

    latest_run_id = get_latest_run_id()

    if latest_run_id is None:
        return pd.DataFrame()

    min_run_id = max(1, int(latest_run_id) - RECURRING_SCAN_RUN_WINDOW + 1)
    cache_key = ("best_recurring_flips", min_run_id, latest_run_id, limit)
    cached = _cache_get(cache_key, DASHBOARD_CACHE_TTL_SECONDS)

    if cached is not None:
        return cached

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
        WHERE run_id >= ?
          AND (
                COALESCE(result_type, '') = 'profitable'
             OR COALESCE(total_profit, 0) > 0
          )
        GROUP BY item_id, item_name, window_name
    """

    query_two_plus = base_select + """
        HAVING Appearances >= 2
        ORDER BY Avg_Recommendation_Score DESC, Avg_Total_Profit DESC, Appearances DESC
        LIMIT ?
    """

    df = query_df(query_two_plus, (min_run_id, limit))

    if df.empty:
        query_fallback = base_select + """
            ORDER BY Avg_Recommendation_Score DESC, Avg_Total_Profit DESC, Appearances DESC
            LIMIT ?
        """

        df = query_df(query_fallback, (min_run_id, limit))

    formatted_df = format_recurring_display_df(df)
    return _cache_set(cache_key, formatted_df)


def get_item_options():
    cached = _cache_get("item_options", ITEM_OPTIONS_CACHE_TTL_SECONDS)

    if cached is not None:
        return cached

    df = query_df("""
        SELECT DISTINCT item_name
        FROM scan_results
        WHERE item_name IS NOT NULL
          AND TRIM(item_name) <> ''
        ORDER BY item_name
    """)

    if df.empty or "item_name" not in df.columns:
        return []

    options = [
        {"label": item_name, "value": item_name}
        for item_name in df["item_name"].dropna().tolist()
    ]

    return _cache_set("item_options", options)


def _trade_board_gp(value):
    try:
        value = float(value or 0)
    except Exception:
        value = 0

    sign = "-" if value < 0 else ""
    value = abs(value)

    if value >= 1000000:
        return f"{sign}{value / 1000000:.1f}M"

    return f"{sign}{value:,.0f}"


def _trade_board_percent(value):
    try:
        return f"{float(value or 0):.2f}%"
    except Exception:
        return "0.00%"


def _trade_board_number(df, column, default=0):
    if column not in df.columns:
        df[column] = default

    df[column] = pd.to_numeric(df[column], errors="coerce").fillna(default)
    return df


def _trade_board_text_value(row, column, default=""):
    value = row.get(column, default)

    if pd.isna(value):
        return default

    return str(value).strip()


def _trade_board_warning(row):
    warnings = []

    for column in ["price_warning", "margin_warning", "trend_warning"]:
        value = _trade_board_text_value(row, column, "")

        if value and value.upper() != "OK" and value.lower() not in ("none", "nan"):
            warnings.append(value)

    if not warnings:
        return "OK"

    return " | ".join(warnings[:3])


def _trade_board_risk_allowed(risk_value, risk_profile):
    risk = str(risk_value or "").strip().lower()
    profile = str(risk_profile or "medium").strip().lower()

    if profile == "high":
        return risk in ("", "low", "medium", "high")

    if profile == "low":
        return risk in ("", "low")

    return risk in ("", "low", "medium")


def _trade_board_action(row, risk_profile, minimum_profit):
    profit_per_item = float(row.get("profit_per_item", 0) or 0)
    total_profit = float(row.get("total_profit", 0) or 0)
    raw_margin = float(row.get("raw_margin", 0) or 0)
    roi_percent = float(row.get("roi_percent", 0) or 0)
    quick_score = float(row.get("quick_score", 0) or 0)
    overnight_score = float(row.get("overnight_score", 0) or 0)
    liquidity_score = float(row.get("liquidity_score", 0) or 0)
    target_buy = float(row.get("target_buy", 0) or 0)
    target_sell = float(row.get("target_sell", 0) or 0)
    quantity = float(row.get("quantity", 0) or 0)
    risk_level = _trade_board_text_value(row, "risk_level", "")
    warning = row.get("Trade Warning", "OK")

    if (
        profit_per_item <= 0
        or total_profit < minimum_profit
        or target_buy <= 0
        or target_sell <= target_buy
        or quantity <= 0
    ):
        return "Avoid / Wait"

    if not _trade_board_risk_allowed(risk_level, risk_profile):
        return "Avoid / Wait"

    if (
        raw_margin >= OVERNIGHT_RAW_MARGIN_MIN
        and roi_percent >= OVERNIGHT_ROI_MIN
        and overnight_score >= 25
        and total_profit >= minimum_profit
        and warning == "OK"
    ):
        return "Overnight Candidate"

    if (
        warning == "OK"
        and liquidity_score >= 30
        and quick_score >= 20
        and total_profit >= minimum_profit
    ):
        return "Buy Now Candidate"

    return "Test Small"


def _trade_board_reason(row):
    action = row.get("Action", "")
    warning = row.get("Trade Warning", "OK")
    quick_score = float(row.get("quick_score", 0) or 0)
    overnight_score = float(row.get("overnight_score", 0) or 0)
    liquidity_score = float(row.get("liquidity_score", 0) or 0)
    total_profit = float(row.get("total_profit", 0) or 0)
    roi_percent = float(row.get("roi_percent", 0) or 0)

    if action == "Avoid / Wait":
        if warning != "OK":
            return f"Warning present: {warning}"
        return "Does not meet minimum profit, price, risk, or margin rules."

    if action == "Overnight Candidate":
        return f"Strong overnight setup: {overnight_score:.1f} overnight score, {roi_percent:.2f}% ROI."

    if action == "Buy Now Candidate":
        return f"Good quick setup: {quick_score:.1f} quick score, liquidity {liquidity_score:.1f}, profit {_trade_board_gp(total_profit)}."

    return "Promising setup, but start small because one or more confidence/liquidity checks are weaker."


def _trade_board_safe_float(value, default=0.0):
    try:
        if pd.isna(value):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _trade_board_yes_no_warning(warning_text):
    warning_text = str(warning_text or "").strip()
    return bool(warning_text and warning_text.upper() != "OK")


def _trade_board_fill_label(row):
    liquidity_score = _trade_board_safe_float(row.get("liquidity_score", 0))
    expected_fill_hours = _trade_board_safe_float(row.get("expected_fill_hours", 0))
    hourly_volume = _trade_board_safe_float(row.get("hourly_volume", 0))
    volume = _trade_board_safe_float(row.get("volume", 0))

    if expected_fill_hours and expected_fill_hours > 36:
        return "Slow"

    if liquidity_score >= 60 or hourly_volume >= 100 or volume >= 2000:
        return "Fast"

    if liquidity_score >= 30 or hourly_volume >= 25 or volume >= 500:
        return "Moderate"

    return "Thin"


def _trade_board_confidence_label(row):
    score = _trade_board_safe_float(row.get("Trade Score", 0))
    liquidity_score = _trade_board_safe_float(row.get("liquidity_score", 0))
    warning = row.get("Trade Warning", "OK")
    risk = str(row.get("risk_level", "") or "").strip().lower()

    if _trade_board_yes_no_warning(warning) or risk == "high":
        return "Low"

    if score >= 85 and liquidity_score >= 45:
        return "High"

    if score >= 55 and liquidity_score >= 25:
        return "Medium"

    return "Low"


def _trade_board_phase2_action(row, risk_profile, minimum_profit):
    profit_per_item = _trade_board_safe_float(row.get("profit_per_item", 0))
    total_profit = _trade_board_safe_float(row.get("total_profit", 0))
    raw_margin = _trade_board_safe_float(row.get("raw_margin", 0))
    roi_percent = _trade_board_safe_float(row.get("roi_percent", 0))
    quick_score = _trade_board_safe_float(row.get("quick_score", 0))
    overnight_score = _trade_board_safe_float(row.get("overnight_score", 0))
    liquidity_score = _trade_board_safe_float(row.get("liquidity_score", 0))
    expected_fill_hours = _trade_board_safe_float(row.get("expected_fill_hours", 0))
    target_buy = _trade_board_safe_float(row.get("target_buy", 0))
    target_sell = _trade_board_safe_float(row.get("target_sell", 0))
    quantity = _trade_board_safe_float(row.get("quantity", 0))
    risk_level = _trade_board_text_value(row, "risk_level", "")
    warning = row.get("Trade Warning", "OK")

    valid_trade = (
        profit_per_item > 0
        and total_profit >= minimum_profit
        and target_buy > 0
        and target_sell > target_buy
        and quantity > 0
    )

    if not valid_trade:
        return "Avoid / Wait"

    if not _trade_board_risk_allowed(risk_level, risk_profile):
        return "Avoid / Wait"

    if warning != "OK" and liquidity_score < 45:
        return "Test Small"

    if (
        raw_margin >= OVERNIGHT_RAW_MARGIN_MIN
        and roi_percent >= OVERNIGHT_ROI_MIN
        and overnight_score >= 30
        and total_profit >= minimum_profit
        and warning == "OK"
    ):
        return "Overnight"

    if (
        warning == "OK"
        and liquidity_score >= 35
        and quick_score >= 25
        and total_profit >= minimum_profit
        and (expected_fill_hours <= 24 or expected_fill_hours == 0)
    ):
        return "Buy Now"

    return "Test Small"


def _trade_board_phase2_reason(row):
    action = row.get("Action", "")
    warning = row.get("Trade Warning", "OK")
    fill = row.get("Fill", "n/a")
    quick_score = _trade_board_safe_float(row.get("quick_score", 0))
    overnight_score = _trade_board_safe_float(row.get("overnight_score", 0))
    liquidity_score = _trade_board_safe_float(row.get("liquidity_score", 0))
    total_profit = _trade_board_safe_float(row.get("total_profit", 0))
    roi_percent = _trade_board_safe_float(row.get("roi_percent", 0))
    profit_per_item = _trade_board_safe_float(row.get("profit_per_item", 0))
    capital_needed = _trade_board_safe_float(row.get("Capital Needed Raw", 0))

    if action == "Avoid / Wait":
        if warning != "OK":
            return f"Wait because warning is present: {warning}"
        return "Wait because profit, price, risk, or quantity rules are not met."

    if action == "Buy Now":
        return (
            f"Best quick setup: {_trade_board_gp(total_profit)} total profit, "
            f"{_trade_board_gp(profit_per_item)} each, {fill.lower()} fill, "
            f"quick score {quick_score:.1f}."
        )

    if action == "Overnight":
        return (
            f"Good hold setup: {overnight_score:.1f} overnight score, "
            f"{roi_percent:.2f}% ROI, {_trade_board_gp(total_profit)} expected profit."
        )

    if warning != "OK":
        return f"Try small only because warning is present: {warning}"

    return (
        f"Promising but not strongest: liquidity {liquidity_score:.1f}, "
        f"{fill.lower()} fill, capital needed {_trade_board_gp(capital_needed)}."
    )


def get_trade_board_recommendations(limit=25, risk_profile="medium", minimum_profit=None):
    """Return the v1.0.5 Phase 2 one-table Trade Board.

    Phase 2 keeps the stable Phase 1 layout and callback, but improves:
    - action classification
    - scoring
    - fill labels
    - confidence labels
    - capital/profit efficiency
    - human-readable reasons
    """
    limit = parse_positive_int(limit, default=25, minimum=5, maximum=100)

    if minimum_profit is None:
        minimum_profit = get_setting("minimum_profit", 50000)

    minimum_profit = parse_positive_int(
        minimum_profit,
        default=50000,
        minimum=0,
        maximum=1000000000
    )

    risk_profile = str(risk_profile or "medium").strip().lower()
    latest_run_id = get_latest_run_id()
    df = get_latest_rows()

    if df.empty:
        return (
            pd.DataFrame(),
            {
                "status": "No latest scan rows found. Run the scanner first.",
                "latest_run_id": latest_run_id or "n/a",
                "candidate_count": 0,
                "buy_now_count": 0,
                "test_small_count": 0,
                "overnight_count": 0,
                "avoid_count": 0,
                "best_profit": 0,
                "minimum_profit": minimum_profit,
            }
        )

    df = add_dashboard_flags(df).copy()

    numeric_columns = [
        "target_buy", "target_sell", "quantity", "raw_margin",
        "profit_per_item", "total_profit", "roi_percent", "volume",
        "hourly_volume", "liquidity_score", "expected_fill_hours",
        "quick_score", "overnight_score", "recommendation_score", "score"
    ]

    for column in numeric_columns:
        df = _trade_board_number(df, column, 0)

    text_columns = [
        "item_name", "window_name", "risk_level", "confidence",
        "liquidity_rating", "flip_category", "signal",
        "price_warning", "margin_warning", "trend_warning",
        "expected_fill_time"
    ]

    for column in text_columns:
        if column not in df.columns:
            df[column] = ""

    df["Trade Warning"] = df.apply(_trade_board_warning, axis=1)
    df["Capital Needed Raw"] = (df["target_buy"].clip(lower=0) * df["quantity"].clip(lower=0)).fillna(0)
    df["Profit Per 1M Capital"] = (
        df["total_profit"].clip(lower=0)
        / (df["Capital Needed Raw"].replace(0, 1) / 1000000)
    ).replace([float("inf"), -float("inf")], 0).fillna(0)
    df["Fill"] = df.apply(_trade_board_fill_label, axis=1)

    risk_penalty = df["risk_level"].astype(str).str.lower().map(
        {"low": 0, "medium": 7, "high": 22}
    ).fillna(5)
    warning_penalty = (df["Trade Warning"] != "OK").astype(int) * 18
    slow_fill_penalty = df["Fill"].map({"Fast": 0, "Moderate": 5, "Thin": 12, "Slow": 18}).fillna(8)

    df["Trade Score"] = (
        df["recommendation_score"].clip(lower=0)
        + df["quick_score"].clip(lower=0) * 0.30
        + df["overnight_score"].clip(lower=0) * 0.18
        + df["liquidity_score"].clip(lower=0) * 0.22
        + df["roi_percent"].clip(lower=0, upper=30)
        + (df["total_profit"].clip(lower=0) / 100000).clip(upper=25)
        + (df["Profit Per 1M Capital"].clip(lower=0) / 10000).clip(upper=15)
        - risk_penalty
        - warning_penalty
        - slow_fill_penalty
    )

    df["Action"] = df.apply(
        lambda row: _trade_board_phase2_action(row, risk_profile, minimum_profit),
        axis=1
    )
    df["Confidence"] = df.apply(_trade_board_confidence_label, axis=1)
    df["Reason"] = df.apply(_trade_board_phase2_reason, axis=1)

    action_order = {
        "Buy Now": 0,
        "Overnight": 1,
        "Test Small": 2,
        "Avoid / Wait": 3,
    }
    confidence_order = {
        "High": 0,
        "Medium": 1,
        "Low": 2,
    }
    df["_action_order"] = df["Action"].map(action_order).fillna(9)
    df["_confidence_order"] = df["Confidence"].map(confidence_order).fillna(9)

    df = df.sort_values(
        by=["_action_order", "_confidence_order", "Trade Score", "total_profit", "liquidity_score"],
        ascending=[True, True, False, False, False]
    )

    if "item_id" in df.columns:
        df = df.drop_duplicates(subset=["item_id", "window_name"], keep="first")
    else:
        df = df.drop_duplicates(subset=["item_name", "window_name"], keep="first")

    top_df = df.head(limit).copy()

    display_df = pd.DataFrame({
        "Action": top_df["Action"],
        "Item": top_df["item_name"],
        "Window": top_df["window_name"],
        "Buy": top_df["target_buy"].apply(_trade_board_gp),
        "Sell": top_df["target_sell"].apply(_trade_board_gp),
        "Qty": top_df["quantity"].round(0).astype(int),
        "Capital Needed": top_df["Capital Needed Raw"].apply(_trade_board_gp),
        "Profit/Item": top_df["profit_per_item"].apply(_trade_board_gp),
        "Total Profit": top_df["total_profit"].apply(_trade_board_gp),
        "ROI": top_df["roi_percent"].apply(_trade_board_percent),
        "Profit/1M": top_df["Profit Per 1M Capital"].apply(_trade_board_gp),
        "Fill": top_df["Fill"],
        "Volume": top_df["volume"].round(0).astype(int),
        "Liquidity": top_df["liquidity_score"].round(1),
        "Score": top_df["Trade Score"].round(1),
        "Risk": top_df["risk_level"].replace("", "n/a"),
        "Confidence": top_df["Confidence"],
        "Warning": top_df["Trade Warning"],
        "Reason": top_df["Reason"],
    })

    summary = {
        "status": f"Trade Board Phase 2 built from scan run {latest_run_id or 'n/a'}. Manual refresh only.",
        "latest_run_id": latest_run_id or "n/a",
        "candidate_count": int(len(df)),
        "buy_now_count": int((df["Action"] == "Buy Now").sum()),
        "test_small_count": int((df["Action"] == "Test Small").sum()),
        "overnight_count": int((df["Action"] == "Overnight").sum()),
        "avoid_count": int((df["Action"] == "Avoid / Wait").sum()),
        "best_profit": int(df["total_profit"].max()) if "total_profit" in df.columns else 0,
        "minimum_profit": minimum_profit,
    }

    return display_df, summary


def read_saved_ai_advice():
    if not os.path.exists(OUTPUT_FILE):
        return (
            "## No AI advice yet\n\n"
            "Run `main.py` or `collector.py`, then click **Generate AI Advice**."
        )

    with open(OUTPUT_FILE, "r", encoding="utf-8") as file:
        return file.read()


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
    scope = get_current_trade_scope()
    cache_key = ("trade_summary", scope["app_username"], scope["osrs_account_name"])
    cached = _trade_cache_get(cache_key)

    if cached is not None:
        return cached

    if not table_exists("completed_trades"):
        summary = {
            "completed_count": 0,
            "realized_profit": 0,
            "avg_roi": 0,
            "best_trade": 0,
            "worst_trade": 0,
            "open_event_count": 0,
            "open_buy_value": 0
        }
        return _trade_cache_set(cache_key, summary)

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

    return _trade_cache_set(cache_key, summary)


def get_completed_trade_rows(limit=100):
    limit = parse_positive_int(limit, default=100, minimum=10, maximum=500)

    if not table_exists("completed_trades"):
        return pd.DataFrame()

    scope = get_current_trade_scope()
    cache_key = ("completed_trade_rows", scope["app_username"], scope["osrs_account_name"], limit)
    cached = _trade_cache_get(cache_key)

    if cached is not None:
        return cached

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

    return _trade_cache_set(cache_key, df)


def get_open_trade_rows(limit=100):
    limit = parse_positive_int(limit, default=100, minimum=10, maximum=500)

    if not table_exists("trade_events"):
        return pd.DataFrame()

    scope = get_current_trade_scope()
    cache_key = ("open_trade_rows", scope["app_username"], scope["osrs_account_name"], limit)
    cached = _trade_cache_get(cache_key)

    if cached is not None:
        return cached

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

    return _trade_cache_set(cache_key, df)


def get_completed_trade_history(limit=5000):
    limit = parse_positive_int(limit, default=5000, minimum=100, maximum=50000)

    if not table_exists("completed_trades"):
        return pd.DataFrame()

    scope = get_current_trade_scope()
    cache_key = ("completed_trade_history", scope["app_username"], scope["osrs_account_name"], limit)
    cached = _trade_cache_get(cache_key)

    if cached is not None:
        return cached

    df = query_df("""
        SELECT
            sell_time,
            item_name,
            total_profit,
            roi_percent
        FROM (
            SELECT
                id,
                sell_time,
                item_name,
                total_profit,
                roi_percent
            FROM completed_trades
            WHERE app_username = ?
              AND osrs_account_name = ?
            ORDER BY sell_time DESC, id DESC
            LIMIT ?
        )
        ORDER BY sell_time ASC, id ASC
    """, (
        scope["app_username"],
        scope["osrs_account_name"],
        limit
    ))

    if not df.empty:
        df["sell_time"] = pd.to_datetime(df["sell_time"], errors="coerce")
        df["cumulative_profit"] = df["total_profit"].fillna(0).cumsum()

    return _trade_cache_set(cache_key, df)


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
        # Use SELECT * so the dashboard remains compatible with older/newer
        # imported_trade_files schemas. The canonical column from trade_importer
        # is matched_rows, but older development builds used other names.
        import_df = query_df(
            """
            SELECT *
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
            matched_count = (
                row.get("matched_rows", None)
                if "matched_rows" in row.index else None
            )

            if matched_count is None and "matched_trades" in row.index:
                matched_count = row.get("matched_trades", 0)

            if matched_count is None and "matched" in row.index:
                matched_count = row.get("matched", 0)

            if matched_count is None:
                matched_count = 0

            latest_trade_import = row.get("imported_at", "No trade import yet")
            latest_import_status = (
                f"{row.get('status', 'Unknown')} | "
                f"rows {row.get('imported_rows', 0)} | "
                f"skipped {row.get('skipped_rows', 0)} | "
                f"matched {matched_count} | "
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

    conn = open_dashboard_connection(read_only=False)

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

    conn = open_dashboard_connection(read_only=False)
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
    r"""
    Run health_check.py from the resolved OSRSFlipper project folder.

    Loading by exact file path avoids accidentally reusing a health_check module
    from a test install or stale process path.
    """
    import importlib.util

    health_check_path = Path(BASE_DIR) / "health_check.py"

    if not health_check_path.exists():
        return (
            f"Health check failed: expected file not found: {health_check_path}",
            str(health_check_path)
        )

    spec = importlib.util.spec_from_file_location(
        "osrsflipper_project_health_check",
        health_check_path
    )

    if spec is None or spec.loader is None:
        return (
            f"Health check failed: could not load module from {health_check_path}",
            str(health_check_path)
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    text = module.run_health_check(write_report=True)

    return text, str(module.REPORT_FILE)


def setting_value(key, default=None):
    return get_setting(key, default if default is not None else DEFAULT_SETTINGS.get(key, {}).get("value"))


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
