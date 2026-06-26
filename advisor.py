import os
import sqlite3
from datetime import datetime

import pandas as pd
from openai import OpenAI, RateLimitError, AuthenticationError, APIError

from database import init_db
from trade_ai_context import build_trade_ai_context, save_ai_feedback
from account_context import get_account_scope, BASE_DIR as APP_BASE_DIR
from openai_key_manager import get_api_key, get_api_key_status
from openai_usage_manager import assert_ai_daily_limit, log_ai_usage
from settings_manager import get_setting
from security_runtime import scrub_shared_openai_env, get_non_secret_env_value


BASE_DIR = str(APP_BASE_DIR)
scrub_shared_openai_env()

DB_FILE = os.path.join(BASE_DIR, "osrs_flip_scanner.db")
MODEL = get_non_secret_env_value("OPENAI_MODEL", "gpt-5.5")
OUTPUT_FILE = os.path.join(BASE_DIR, "osrs_ai_advice.txt")
RUNELITE_ACCOUNT = os.getenv("RUNELITE_ACCOUNT", None)


# More choices than before. These are account-scoped settings.
QUICK_FLIP_TARGET_COUNT = int(get_setting("ai_quick_choices", 10))
OVERNIGHT_FLIP_TARGET_COUNT = int(get_setting("ai_overnight_choices", 10))
VALUE_FLIP_TARGET_COUNT = int(get_setting("ai_value_choices", 10))
WATCH_CONTEXT_TARGET_COUNT = 12
AVOID_CONTEXT_TARGET_COUNT = 8

# Pull a larger source pool so the AI has more options after filtering
# out items already traded today.
AI_SOURCE_ROW_LIMIT = int(get_setting("ai_source_row_limit", 350))

# Overnight rules requested:
#
# raw_margin = target_sell - target_buy before GE tax
# profit_per_item = post-tax profit for one item
# roi_percent = post-tax return percentage from the scanner
#
# Overnight recommendations should not qualify just because bulk quantity
# makes total_profit large.
#
# Overnight candidates must now have:
# - raw_margin >= configured minimum gp
# - profit_per_item > 0 after tax
# - roi_percent >= configured minimum %
MIN_OVERNIGHT_RAW_MARGIN_PER_ITEM = int(get_setting("min_overnight_raw_margin", 10000))
MIN_OVERNIGHT_ROI_PERCENT = float(get_setting("min_overnight_roi_percent", 5.0))

# Additional valuable flips are separate from Quick/Overnight. These are
# potentially useful opportunities that may not be the fastest fills but
# still have meaningful profit, ROI, or net/item upside.
MIN_VALUE_TOTAL_PROFIT = 100000
MIN_VALUE_PROFIT_PER_ITEM = 1000
MIN_VALUE_RAW_MARGIN_PER_ITEM = 1500

# Do not recommend items already traded today.
EXCLUDE_TODAYS_TRADED_ITEMS = bool(get_setting("exclude_items_traded_today", True))


def get_connection():
    return sqlite3.connect(DB_FILE)


def format_gp(value):
    if value is None or pd.isna(value):
        return "N/A"

    return f"{int(value):,}"


def format_gp_signed(value):
    if value is None or pd.isna(value):
        return "N/A"

    value = int(value)
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,} gp"


def safe_numeric_column(df, column_name, default=0):
    if column_name not in df.columns:
        df[column_name] = default

    df[column_name] = pd.to_numeric(
        df[column_name],
        errors="coerce"
    ).fillna(default)

    return df


def table_exists(cursor, table_name):
    cursor.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,)
    )

    return cursor.fetchone() is not None


def get_today_date_string():
    return datetime.now().strftime("%Y-%m-%d")


def get_latest_run_info():
    conn = get_connection()

    query = """
        SELECT
            id AS run_id,
            scanned_at,
            cash_stack,
            minimum_profit
        FROM scan_runs
        ORDER BY id DESC
        LIMIT 1
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        return None

    return df.iloc[0].to_dict()


def get_todays_traded_items():
    """
    Returns item IDs and names that were bought/sold/completed today
    for the currently logged-in OSRSFlipper user and linked OSRS account.

    This is used to stop the AI from recommending the same item again
    after the user has already flipped or traded it today.
    """
    today = get_today_date_string()
    scope = get_account_scope()

    traded_ids = set()
    traded_names = set()
    rows = []

    if not os.path.exists(DB_FILE):
        return {
            "date": today,
            "app_username": scope["app_username"],
            "osrs_account_name": scope["osrs_account_name"],
            "item_ids": traded_ids,
            "item_names": traded_names,
            "rows": rows
        }

    conn = get_connection()
    cursor = conn.cursor()

    try:
        if table_exists(cursor, "trade_events"):
            cursor.execute(
                """
                SELECT
                    item_id,
                    item_name,
                    side,
                    price_each,
                    quantity,
                    remaining_quantity,
                    traded_at,
                    source
                FROM trade_events
                WHERE app_username = ?
                  AND osrs_account_name = ?
                  AND substr(traded_at, 1, 10) = ?
                ORDER BY traded_at DESC
                """,
                (
                    scope["app_username"],
                    scope["osrs_account_name"],
                    today
                )
            )

            for row in cursor.fetchall():
                (
                    item_id,
                    item_name,
                    side,
                    price_each,
                    quantity,
                    remaining_quantity,
                    traded_at,
                    source
                ) = row

                if item_id is not None:
                    try:
                        traded_ids.add(int(item_id))
                    except Exception:
                        pass

                if item_name:
                    traded_names.add(str(item_name).strip().lower())

                rows.append({
                    "source_table": "trade_events",
                    "item_id": item_id,
                    "item_name": item_name,
                    "side": side,
                    "price_each": price_each,
                    "quantity": quantity,
                    "remaining_quantity": remaining_quantity,
                    "time": traded_at,
                    "source": source
                })

        if table_exists(cursor, "completed_trades"):
            cursor.execute(
                """
                SELECT
                    item_id,
                    item_name,
                    quantity,
                    buy_price_each,
                    sell_price_each,
                    total_profit,
                    roi_percent,
                    buy_time,
                    sell_time
                FROM completed_trades
                WHERE app_username = ?
                  AND osrs_account_name = ?
                  AND (
                        substr(buy_time, 1, 10) = ?
                     OR substr(sell_time, 1, 10) = ?
                     OR substr(created_at, 1, 10) = ?
                  )
                ORDER BY sell_time DESC
                """,
                (
                    scope["app_username"],
                    scope["osrs_account_name"],
                    today,
                    today,
                    today
                )
            )

            for row in cursor.fetchall():
                (
                    item_id,
                    item_name,
                    quantity,
                    buy_price_each,
                    sell_price_each,
                    total_profit,
                    roi_percent,
                    buy_time,
                    sell_time
                ) = row

                if item_id is not None:
                    try:
                        traded_ids.add(int(item_id))
                    except Exception:
                        pass

                if item_name:
                    traded_names.add(str(item_name).strip().lower())

                rows.append({
                    "source_table": "completed_trades",
                    "item_id": item_id,
                    "item_name": item_name,
                    "side": "COMPLETED_FLIP",
                    "buy_price_each": buy_price_each,
                    "sell_price_each": sell_price_each,
                    "quantity": quantity,
                    "total_profit": total_profit,
                    "roi_percent": roi_percent,
                    "time": sell_time or buy_time,
                    "source": "completed_trades"
                })

    finally:
        conn.close()

    return {
        "date": today,
        "app_username": scope["app_username"],
        "osrs_account_name": scope["osrs_account_name"],
        "item_ids": traded_ids,
        "item_names": traded_names,
        "rows": rows
    }


def format_todays_trade_summary(todays_trades, max_items=25):
    rows = todays_trades.get("rows", [])
    date = todays_trades.get("date", get_today_date_string())

    if not rows:
        return (
            f"Today's traded-item exclusion date: {date}\n"
            "No trades from today were found. No items are excluded for today's activity."
        )

    unique_items = {}

    for row in rows:
        item_id = row.get("item_id")
        item_name = row.get("item_name") or "Unknown item"
        key = item_id if item_id is not None else item_name.lower()

        if key not in unique_items:
            unique_items[key] = {
                "item_id": item_id,
                "item_name": item_name,
                "events": 0,
                "completed_profit": 0
            }

        unique_items[key]["events"] += 1

        if row.get("source_table") == "completed_trades":
            try:
                unique_items[key]["completed_profit"] += int(row.get("total_profit") or 0)
            except Exception:
                pass

    lines = []
    lines.append(f"Today's traded-item exclusion date: {date}")
    if todays_trades.get("app_username") or todays_trades.get("osrs_account_name"):
        lines.append(
            f"Account scope: {todays_trades.get('app_username')} / {todays_trades.get('osrs_account_name')}"
        )
    lines.append(
        "Do not recommend these items again today unless the user explicitly asks for repeats."
    )
    lines.append(f"Unique items traded today: {len(unique_items)}")
    lines.append("Items traded today:")

    for index, item in enumerate(unique_items.values(), start=1):
        if index > max_items:
            lines.append(f"- ...and {len(unique_items) - max_items} more items.")
            break

        id_text = f"ID {item['item_id']}" if item["item_id"] is not None else "No item ID"
        profit_text = ""

        if item["completed_profit"] != 0:
            profit_text = f", completed P/L {format_gp_signed(item['completed_profit'])}"

        lines.append(
            f"- {item['item_name']} ({id_text}), events today {item['events']}{profit_text}"
        )

    return "\n".join(lines)


def exclude_todays_traded_candidates(df):
    """
    Removes scanner candidates whose item_id or item_name appears in today's
    trade history.
    """
    if df.empty or not EXCLUDE_TODAYS_TRADED_ITEMS:
        return df, get_todays_traded_items(), []

    todays_trades = get_todays_traded_items()
    traded_ids = todays_trades.get("item_ids", set())
    traded_names = todays_trades.get("item_names", set())

    if not traded_ids and not traded_names:
        return df, todays_trades, []

    work_df = df.copy()

    if "item_id" not in work_df.columns:
        work_df["item_id"] = None

    if "item_name" not in work_df.columns:
        work_df["item_name"] = ""

    item_ids = pd.to_numeric(
        work_df["item_id"],
        errors="coerce"
    )

    item_names = work_df["item_name"].fillna("").astype(str).str.strip().str.lower()

    id_mask = item_ids.isin(traded_ids) if traded_ids else False
    name_mask = item_names.isin(traded_names) if traded_names else False

    excluded_mask = id_mask | name_mask

    excluded_rows = work_df[excluded_mask].copy()
    filtered_df = work_df[~excluded_mask].copy()

    excluded_items = []

    if not excluded_rows.empty:
        seen = set()

        for _, row in excluded_rows.iterrows():
            key = (
                str(row.get("item_id", "")),
                str(row.get("item_name", "")).lower()
            )

            if key in seen:
                continue

            seen.add(key)

            excluded_items.append({
                "item_id": row.get("item_id"),
                "item_name": row.get("item_name"),
                "quick_score": row.get("quick_score"),
                "overnight_score": row.get("overnight_score"),
                "profit_per_item": row.get("profit_per_item"),
                "roi_percent": row.get("roi_percent")
            })

    return filtered_df, todays_trades, excluded_items


def prepare_candidate_numbers(df):
    number_columns = {
        "recommendation_score": 0,
        "score": 0,
        "raw_margin": 0,
        "total_profit": 0,
        "profit_per_item": 0,
        "roi_percent": 0,
        "volume": 0,
        "hourly_volume": 0,
        "liquidity_score": 0,
        "expected_fill_hours": 999,
        "hist_samples": 0,
        "margin_delta_percent": 0,

        "daily_change_percent": 0,
        "weekly_change_percent": 0,
        "long_term_change_percent": 0,
        "daily_volatility_percent": 0,
        "weekly_volatility_percent": 0,
        "seven_day_high": 0,
        "seven_day_low": 0,
        "price_position_7d_percent": 50,
        "quick_score": 0,
        "overnight_score": 0
    }

    for column_name, default in number_columns.items():
        df = safe_numeric_column(df, column_name, default)

    text_columns = [
        "flip_category",
        "category_reason",
        "price_warning",
        "margin_warning",
        "trend_warning",
        "signal",
        "window_name",
        "result_type",
        "daily_trend",
        "weekly_trend",
        "long_term_trend",
        "trend_confidence",
        "liquidity_rating",
        "confidence"
    ]

    for column_name in text_columns:
        if column_name not in df.columns:
            df[column_name] = ""

        df[column_name] = df[column_name].fillna("")

    return df


def add_trend_confidence_rank(df):
    if df.empty:
        return df

    rank_map = {
        "High": 4,
        "Medium": 3,
        "Low": 2,
        "Very low": 1,
        "No data": 0,
        "": 0
    }

    df["trend_confidence_rank"] = df["trend_confidence"].map(rank_map).fillna(0)

    return df


def sort_general_candidates(df):
    if df.empty:
        return df

    return df.sort_values(
        by=[
            "recommendation_score",
            "quick_score",
            "overnight_score",
            "liquidity_score",
            "roi_percent",
            "raw_margin",
            "profit_per_item",
            "total_profit",
            "volume",
            "score"
        ],
        ascending=[False, False, False, False, False, False, False, False, False, False]
    )


def sort_quick_candidates(df):
    if df.empty:
        return df

    return df.sort_values(
        by=[
            "quick_score",
            "recommendation_score",
            "liquidity_score",
            "total_profit",
            "volume",
            "score"
        ],
        ascending=[False, False, False, False, False, False]
    )


def sort_overnight_candidates(df):
    if df.empty:
        return df

    return df.sort_values(
        by=[
            "overnight_score",
            "roi_percent",
            "profit_per_item",
            "raw_margin",
            "recommendation_score",
            "trend_confidence_rank",
            "liquidity_score",
            "total_profit",
            "score"
        ],
        ascending=[False, False, False, False, False, False, False, False, False]
    )


def sort_value_candidates(df):
    if df.empty:
        return df

    return df.sort_values(
        by=[
            "total_profit",
            "profit_per_item",
            "raw_margin",
            "roi_percent",
            "recommendation_score",
            "liquidity_score",
            "trend_confidence_rank",
            "score"
        ],
        ascending=[False, False, False, False, False, False, False, False]
    )


def dedupe_candidates(df):
    """
    Avoid showing the exact same item/window/result_type more than once.
    """
    if df.empty:
        return df

    return df.drop_duplicates(
        subset=["item_id", "window_name", "result_type"],
        keep="first"
    )


def dedupe_items(df):
    """
    Keep one row per item for sections where variety is more useful.
    """
    if df.empty:
        return df

    return df.drop_duplicates(
        subset=["item_id"],
        keep="first"
    )


def build_candidate_key_series(df):
    return (
        df["item_id"].astype(str)
        + "|"
        + df["window_name"].astype(str)
        + "|"
        + df["result_type"].astype(str)
    )


def build_item_key_series(df):
    return df["item_id"].astype(str)


def select_quick_candidates(df, target_count=10):
    """
    Builds a pool of quick-flip candidates.

    Uses Quick Score first, then falls back to liquidity/fill rules.
    """
    if df.empty:
        return df

    preferred = df[
        (df["flip_category"] == "Quick Flip")
        | (df["quick_score"] >= 70)
    ].copy()

    preferred["ai_bucket"] = "Quick Flip Candidate"
    preferred["ai_bucket_reason"] = (
        "High quick score or rule-based recommender classified this as a Quick Flip."
    )

    backup = df[
        (df["profit_per_item"] > 0)
        & (df["quick_score"] >= 55)
        & (df["liquidity_score"] >= 35)
        & (df["expected_fill_hours"] <= 2)
        & (df["price_warning"].isin(["", "OK"]))
        & (~df["signal"].isin(["Below average", "Watch only"]))
    ].copy()

    backup["ai_bucket"] = "Quick Backup Candidate"
    backup["ai_bucket_reason"] = (
        "Not a strict Quick Flip, but Quick Score, fill time, and liquidity are usable."
    )

    fallback = df[
        (df["profit_per_item"] > 0)
        & (df["quick_score"] >= 40)
        & (df["liquidity_score"] >= 25)
        & (df["expected_fill_hours"] <= 4)
    ].copy()

    fallback["ai_bucket"] = "Quick Fallback Candidate"
    fallback["ai_bucket_reason"] = (
        "Used to expand the quick-flip list. Treat as lower-confidence and test small."
    )

    combined = pd.concat(
        [preferred, backup, fallback],
        ignore_index=True
    )

    combined = dedupe_candidates(combined)
    combined = dedupe_items(combined)
    combined = sort_quick_candidates(combined)

    return combined.head(target_count)


def apply_overnight_rules(df):
    """
    Overnight candidates must have a meaningful one-item spread
    and still be profitable after GE tax.

    Rules:
    - raw_margin >= 10,000 gp before tax
    - profit_per_item > 0 after tax
    - roi_percent >= 5%
    """
    if df.empty:
        return df

    return df[
        (df["raw_margin"] >= MIN_OVERNIGHT_RAW_MARGIN_PER_ITEM)
        & (df["profit_per_item"] > 0)
        & (df["roi_percent"] >= MIN_OVERNIGHT_ROI_PERCENT)
    ].copy()


def select_overnight_candidates(df, target_count=10, exclude_item_keys=None):
    """
    Builds overnight candidates using strict per-item rules.

    Overnight flips must have:
    - raw_margin >= MIN_OVERNIGHT_RAW_MARGIN_PER_ITEM
    - profit_per_item > 0 after tax
    - roi_percent >= MIN_OVERNIGHT_ROI_PERCENT
    """
    if exclude_item_keys is None:
        exclude_item_keys = set()

    if df.empty:
        return df

    work_df = df.copy()
    work_df["item_key"] = build_item_key_series(work_df)

    non_excluded_df = work_df[
        ~work_df["item_key"].isin(exclude_item_keys)
    ].copy()

    non_excluded_df = apply_overnight_rules(non_excluded_df)

    preferred = non_excluded_df[
        (non_excluded_df["flip_category"] == "Overnight Flip")
        | (non_excluded_df["overnight_score"] >= 70)
    ].copy()

    preferred["ai_bucket"] = "Overnight Flip Candidate"
    preferred["ai_bucket_reason"] = (
        f"High overnight score/category and meets overnight rules: "
        f"raw margin at least {MIN_OVERNIGHT_RAW_MARGIN_PER_ITEM:,} gp, "
        f"positive post-tax profit, and ROI at least {MIN_OVERNIGHT_ROI_PERCENT}%."
    )

    backup = non_excluded_df[
        (non_excluded_df["overnight_score"] >= 55)
        & (non_excluded_df["liquidity_score"] >= 25)
        & (non_excluded_df["expected_fill_hours"] <= 12)
        & (~non_excluded_df["signal"].isin(["Below average", "Watch only"]))
    ].copy()

    backup["ai_bucket"] = "Overnight Backup Candidate"
    backup["ai_bucket_reason"] = (
        f"Meets overnight rules, but is not a strict top overnight candidate."
    )

    fallback = non_excluded_df[
        (non_excluded_df["overnight_score"] >= 40)
        & (non_excluded_df["liquidity_score"] >= 15)
        & (non_excluded_df["expected_fill_hours"] <= 24)
    ].copy()

    fallback["ai_bucket"] = "Overnight Fallback Candidate"
    fallback["ai_bucket_reason"] = (
        "Meets overnight rules. Used to expand the overnight list only if stronger candidates are unavailable."
    )

    combined = pd.concat(
        [preferred, backup, fallback],
        ignore_index=True
    )

    combined = dedupe_candidates(combined)
    combined = dedupe_items(combined)
    combined = sort_overnight_candidates(combined)

    return combined.head(target_count)


def select_value_candidates(df, target_count=10, exclude_item_keys=None):
    """
    Adds more choices for potentially valuable flips.

    These are not necessarily the fastest quick flips or strict overnight flips.
    They are selected because they have meaningful total profit, per-item profit,
    raw margin, or ROI while still avoiding obvious warnings when possible.
    """
    if exclude_item_keys is None:
        exclude_item_keys = set()

    if df.empty:
        return df

    work_df = df.copy()
    work_df["item_key"] = build_item_key_series(work_df)

    work_df = work_df[
        ~work_df["item_key"].isin(exclude_item_keys)
    ].copy()

    preferred = work_df[
        (work_df["profit_per_item"] > 0)
        & (
            (work_df["total_profit"] >= MIN_VALUE_TOTAL_PROFIT)
            | (work_df["profit_per_item"] >= MIN_VALUE_PROFIT_PER_ITEM)
            | (work_df["raw_margin"] >= MIN_VALUE_RAW_MARGIN_PER_ITEM)
        )
        & (work_df["roi_percent"] > 0)
        & (work_df["liquidity_score"] >= 15)
    ].copy()

    preferred["ai_bucket"] = "Additional Valuable Candidate"
    preferred["ai_bucket_reason"] = (
        "Additional value candidate with meaningful profit, margin, ROI, or total upside. "
        "Use as an alternate choice, especially when quick or overnight choices are limited."
    )

    backup = work_df[
        (work_df["profit_per_item"] > 0)
        & (work_df["total_profit"] > 0)
        & (work_df["recommendation_score"] >= 40)
        & (work_df["liquidity_score"] >= 10)
    ].copy()

    backup["ai_bucket"] = "Additional Value Backup"
    backup["ai_bucket_reason"] = (
        "Backup value candidate. It has positive scanner profit but should be tested small."
    )

    combined = pd.concat(
        [preferred, backup],
        ignore_index=True
    )

    combined = dedupe_candidates(combined)
    combined = dedupe_items(combined)
    combined = sort_value_candidates(combined)

    return combined.head(target_count)


def build_balanced_ai_pool(df, quick_count=10, overnight_count=10, value_count=10):
    """
    Returns a larger balanced candidate pool for the AI:
    - Up to 10 Quick Flip candidates
    - Up to 10 Overnight Flip candidates, but only if each meets:
      raw_margin >= 10,000 gp, positive post-tax profit, and ROI >= 5%
    - Up to 10 Additional Valuable Flip candidates
    - Watch/Avoid rows for context
    """
    if df.empty:
        return df

    df = prepare_candidate_numbers(df)
    df = add_trend_confidence_rank(df)

    quick_df = select_quick_candidates(
        df=df,
        target_count=quick_count
    )

    used_item_keys = set()

    if not quick_df.empty:
        used_item_keys.update(set(build_item_key_series(quick_df)))

    overnight_df = select_overnight_candidates(
        df=df,
        target_count=overnight_count,
        exclude_item_keys=used_item_keys
    )

    if not overnight_df.empty:
        used_item_keys.update(set(build_item_key_series(overnight_df)))

    value_df = select_value_candidates(
        df=df,
        target_count=value_count,
        exclude_item_keys=used_item_keys
    )

    if not value_df.empty:
        used_item_keys.update(set(build_item_key_series(value_df)))

    watch_df = df[
        df["flip_category"].isin(["Watch / Test First"])
    ].copy()

    if not watch_df.empty:
        watch_df["ai_bucket"] = "Watch / Test First"
        watch_df["ai_bucket_reason"] = watch_df["category_reason"].fillna(
            "Included as caution context."
        )
        watch_df = sort_general_candidates(watch_df)
        watch_df = dedupe_items(watch_df).head(WATCH_CONTEXT_TARGET_COUNT)

    avoid_df = df[
        df["flip_category"].isin(["Avoid"])
    ].copy()

    if not avoid_df.empty:
        avoid_df["ai_bucket"] = "Avoid"
        avoid_df["ai_bucket_reason"] = avoid_df["category_reason"].fillna(
            "Included as avoid context."
        )
        avoid_df = sort_general_candidates(avoid_df)
        avoid_df = dedupe_items(avoid_df).head(AVOID_CONTEXT_TARGET_COUNT)

    balanced_df = pd.concat(
        [quick_df, overnight_df, value_df, watch_df, avoid_df],
        ignore_index=True
    )

    balanced_df = dedupe_candidates(balanced_df)

    # Keep AI bucket order stable.
    bucket_order = {
        "Quick Flip Candidate": 1,
        "Quick Backup Candidate": 2,
        "Quick Fallback Candidate": 3,
        "Overnight Flip Candidate": 4,
        "Overnight Backup Candidate": 5,
        "Overnight Fallback Candidate": 6,
        "Additional Valuable Candidate": 7,
        "Additional Value Backup": 8,
        "Watch / Test First": 9,
        "Avoid": 10
    }

    balanced_df["ai_bucket_order"] = balanced_df["ai_bucket"].map(
        bucket_order
    ).fillna(99)

    balanced_df = balanced_df.sort_values(
        by=[
            "ai_bucket_order",
            "quick_score",
            "overnight_score",
            "total_profit",
            "roi_percent",
            "profit_per_item",
            "raw_margin",
            "recommendation_score",
            "liquidity_score"
        ],
        ascending=[True, False, False, False, False, False, False, False, False]
    )

    return balanced_df


def get_latest_candidates(limit=AI_SOURCE_ROW_LIMIT):
    conn = get_connection()

    query = """
        SELECT
            sr.item_id,
            sr.item_name,
            sr.window_name,
            sr.window_rank,
            sr.result_type,

            sr.recommendation_rank,
            sr.recommendation,
            sr.recommendation_score,
            sr.risk_level,
            sr.why,

            sr.flip_category,
            sr.category_reason,

            sr.price_source,
            sr.target_buy,
            sr.target_sell,
            sr.avg_low,
            sr.avg_high,
            sr.buy_vs_avg_low_percent,
            sr.sell_vs_avg_high_percent,
            sr.price_warning,

            sr.quantity,
            sr.cost,
            sr.tax,
            sr.raw_margin,
            sr.profit_per_item,
            sr.total_profit,
            sr.roi_percent,

            sr.volume,
            sr.hourly_volume,
            sr.liquidity_score,
            sr.liquidity_rating,
            sr.expected_fill_hours,
            sr.expected_fill_time,
            sr.high_volume,
            sr.low_volume,

            sr.buy_limit,
            sr.confidence,

            sr.hist_samples,
            sr.avg_raw_margin,
            sr.margin_delta_percent,
            sr.margin_warning,
            sr.signal,

            sr.daily_trend,
            sr.weekly_trend,
            sr.long_term_trend,
            sr.daily_change_percent,
            sr.weekly_change_percent,
            sr.long_term_change_percent,
            sr.daily_volatility_percent,
            sr.weekly_volatility_percent,
            sr.seven_day_high,
            sr.seven_day_low,
            sr.price_position_7d_percent,
            sr.trend_confidence,
            sr.trend_warning,
            sr.quick_score,
            sr.overnight_score,

            sr.score
        FROM scan_results sr
        WHERE sr.run_id = (
            SELECT MAX(run_id)
            FROM scan_results
        )
          AND sr.result_type IN ('profitable', 'watchlist')
        ORDER BY
            sr.quick_score DESC,
            sr.overnight_score DESC,
            sr.total_profit DESC,
            sr.roi_percent DESC,
            sr.profit_per_item DESC,
            sr.raw_margin DESC,
            sr.recommendation_score DESC,
            sr.score DESC
        LIMIT ?
    """

    source_limit = max(int(limit), AI_SOURCE_ROW_LIMIT)

    df = pd.read_sql_query(query, conn, params=(source_limit,))
    conn.close()

    if df.empty:
        todays_trades = get_todays_traded_items()
        return df, todays_trades, []

    df = prepare_candidate_numbers(df)

    filtered_df, todays_trades, excluded_items = exclude_todays_traded_candidates(df)

    if filtered_df.empty:
        return filtered_df, todays_trades, excluded_items

    balanced_df = build_balanced_ai_pool(
        df=filtered_df,
        quick_count=QUICK_FLIP_TARGET_COUNT,
        overnight_count=OVERNIGHT_FLIP_TARGET_COUNT,
        value_count=VALUE_FLIP_TARGET_COUNT
    )

    return balanced_df, todays_trades, excluded_items


def format_excluded_candidates_summary(excluded_items, max_items=30):
    if not excluded_items:
        return "No scanner candidates were removed because of today's trades."

    lines = []
    lines.append(
        "Scanner candidates removed because the user already traded the item today:"
    )

    for index, item in enumerate(excluded_items, start=1):
        if index > max_items:
            lines.append(f"- ...and {len(excluded_items) - max_items} more excluded candidates.")
            break

        lines.append(
            f"- {item.get('item_name')} "
            f"(ID {item.get('item_id')}), "
            f"quick_score {item.get('quick_score')}, "
            f"overnight_score {item.get('overnight_score')}, "
            f"net/item {item.get('profit_per_item')}, "
            f"ROI {item.get('roi_percent')}"
        )

    return "\n".join(lines)


def build_ai_prompt(run_info, candidates_df, risk_profile, trade_memory=None, todays_trade_summary=None, excluded_summary=None):
    candidate_json = candidates_df.to_json(
        orient="records",
        indent=2
    )

    if trade_memory is None:
        trade_memory = "No local trade memory was provided."

    if todays_trade_summary is None:
        todays_trade_summary = "No today's-trade summary was provided."

    if excluded_summary is None:
        excluded_summary = "No excluded-candidate summary was provided."

    cash_stack = int(run_info["cash_stack"])
    minimum_profit = int(run_info["minimum_profit"])
    run_id = int(run_info["run_id"])
    scanned_at = run_info["scanned_at"]

    return f"""
You are an OSRS Grand Exchange flipping assistant.

The user has:
- Cash stack: {cash_stack:,} gp
- Minimum desired profit: {minimum_profit:,} gp
- Risk profile: {risk_profile}
- Latest scan run ID: {run_id}
- Latest scan time: {scanned_at}
- AI quick choices setting: {QUICK_FLIP_TARGET_COUNT}
- AI overnight choices setting: {OVERNIGHT_FLIP_TARGET_COUNT}
- AI additional value choices setting: {VALUE_FLIP_TARGET_COUNT}
- Same-day traded item exclusion enabled: {EXCLUDE_TODAYS_TRADED_ITEMS}

Trade memory from the user's actual completed and open trades:
{trade_memory}

Today's trade exclusion memory:
{todays_trade_summary}

Excluded scanner candidates:
{excluded_summary}

Analyze the latest scanner results together with the user's trade memory.

Important trade-memory rules:
- Use the user's realized profit/loss, ROI, open positions, recent wins/losses, and best/worst items when making recommendations.
- Prefer item types and flip styles that have worked well for the user historically.
- Warn the user about repeated losing items, bad holding patterns, poor ROI patterns, or too much GP tied up in open buys.
- If current open exposure is high, recommend fewer new buys and prioritize exits.
- If recent realized ROI is poor, suggest safer test quantities and lower-risk flips.
- If a scanner candidate matches an item the user has lost money on in the past, call that out clearly.
- If a scanner candidate matches an item the user has performed well on historically, explain why it may fit the user's history.
- Use LIVE GE SLOT ANALYSIS only when discussing current GE slots, currently buying offers, currently selling offers, repricing, or controlled loss exits.
- Do not treat LOCAL UNMATCHED BUY HISTORY as currently buying, currently selling, or occupying a GE slot.
- Use stale live-slot analysis to decide whether it may be better to accept a controlled loss and free one of the 8 Grand Exchange slots.
- Treat a GE slot as valuable opportunity cost. If a live SELLING offer has been sitting too long and the estimated loss is small, it may be better to exit and redeploy the slot.
- Never recommend accepting a large loss casually. Explain the estimated loss, held time, slot pressure, and why the exit may or may not be worth it.
- If live slot pressure is high, be more willing to recommend repricing or controlled small-loss exits for live SELLING offers only.
- For live BUYING offers, suggest canceling or repricing if stale; do not suggest selling at a loss because the item may not be bought yet.
- If live slot pressure is low, prefer patience or repricing unless the live offer is very stale or trend/liquidity is poor.
- Do not overfit to one trade. Use repeated patterns more strongly than single one-off wins/losses.
- Do not invent trades not present in the trade memory.

Critical same-day repeat rule:
- Do not recommend items listed in Today's trade exclusion memory.
- Do not recommend candidates listed in Excluded scanner candidates.
- The user does not want to be offered items they have already traded today.
- If a same-day traded item looks good, mention only that it was intentionally skipped because it was already traded today.
- If the candidate list has fewer choices because of this filter, explain that today's trade filter reduced the list.

Important scanner rules:
- Do not claim a flip is guaranteed.
- Consider GE tax already included in profit_per_item.
- Use the provided data only. Do not invent current OSRS prices.
- Prioritize realistic fills, liquidity, confidence, historical signal, trend stability, and total profit.
- Expected fill time is an estimate based on recent volume, not a guarantee.
- Price Warning means latest target prices differ sharply from average prices.
- Margin Warning means the margin is far above historical average and may be unstable.
- Trend Warning means daily/weekly trend data shows extra risk such as volatility, weekly decline, or price near 7-day high.
- Quick Score is the scanner's score for active short-term flipping.
- Overnight Score is the scanner's score for leaving offers in the GE while away or logged out.
- raw_margin is target_sell minus target_buy for one item before GE tax.
- profit_per_item is the post-tax profit for one item.
- roi_percent is the post-tax return percentage from the scanner.
- total_profit is bulk profit across the selected quantity.
- Low history sample counts should reduce trust.
- Do not over-recommend items with poor liquidity, suspicious price warnings, trend warnings, or limited history.
- Explain quick flips separately from overnight flips.
- Provide more choices than before so the user has alternatives.

Critical loss-cut / slot recovery rules:
- There are only 8 Grand Exchange slots.
- Use only the LIVE GE SLOT ANALYSIS from trade memory when deciding whether to suggest accepting a loss.
- Ignore LOCAL UNMATCHED BUY HISTORY for current slot pressure because those rows are historical/inventory estimates, not live offers.
- For each stale live SELLING offer, compare:
  - how long it has been held
  - estimated fast-exit loss or profit
  - estimated patient-exit loss or profit
  - percent of open value lost
  - live GE slot pressure
  - liquidity and trend warnings
  - whether the slot could be better used on stronger current candidates
- Recommend "accept a controlled loss" only when a live SELLING offer is stale, the estimated loss is small or moderate, and slot pressure/opportunity cost justifies it.
- Recommend "reprice and wait" when the loss is too large or slot pressure is low.
- Recommend "hold" only when the position is not stale, has acceptable trend/liquidity, or the estimated exit loss is too large.
- Be clear that this is advice only and the user must confirm any in-game sale.

Critical overnight rules:
- Overnight Flips must have raw_margin >= {MIN_OVERNIGHT_RAW_MARGIN_PER_ITEM:,} gp for one item.
- Overnight Flips must have profit_per_item > 0 after GE tax.
- Overnight Flips should have roi_percent >= {MIN_OVERNIGHT_ROI_PERCENT}%.
- This is a per-item rule, not a bulk total_profit rule.
- Do not put an item in Overnight Flips just because quantity makes total_profit large.
- Do not include overnight items with raw_margin below {MIN_OVERNIGHT_RAW_MARGIN_PER_ITEM:,} gp.
- Do not include overnight items with roi_percent below {MIN_OVERNIGHT_ROI_PERCENT}%.
- Do not include overnight items with profit_per_item <= 0.
- If fewer than {OVERNIGHT_FLIP_TARGET_COUNT} overnight candidates meet these rules, provide fewer than 10 and clearly say there were not enough qualifying overnight flips.

Candidate pool rules:
- The field ai_bucket tells you why the scanner included that candidate.
- Provide up to {QUICK_FLIP_TARGET_COUNT} Quick Flips.
- Provide up to {OVERNIGHT_FLIP_TARGET_COUNT} Overnight Flips, but only include items that meet all overnight rules.
- Provide up to {VALUE_FLIP_TARGET_COUNT} Additional Valuable Flips as alternate options.
- Additional Valuable Flips do not need to meet overnight rules unless you explicitly describe them as overnight holds.
- If a candidate is marked Backup or Fallback, you may still include it, but clearly label it as test-first or lower confidence.
- Do not use the exact same item in more than one recommendation section unless there are not enough unique candidates.
- For Quick Flips, prefer ai_bucket values starting with "Quick" and higher quick_score.
- For Overnight Flips, prefer ai_bucket values starting with "Overnight", higher overnight_score, higher roi_percent, and stronger post-tax profit_per_item.
- For Additional Valuable Flips, prefer ai_bucket values starting with "Additional", higher total_profit, stronger profit_per_item, and acceptable liquidity.
- If there are fewer ideal candidates, fill with best available backup candidates and label them clearly.

Category meaning:
- Quick Flip: active short-term flip, usually faster fill, good liquidity, short estimated fill time, and a strong Quick Score.
- Overnight Flip: slower flip better for leaving offers in the GE while away; must have raw per-item margin of at least {MIN_OVERNIGHT_RAW_MARGIN_PER_ITEM:,} gp, positive post-tax profit, at least {MIN_OVERNIGHT_ROI_PERCENT}% ROI, stable daily/weekly trend, reasonable fill time, and strong Overnight Score.
- Additional Valuable Flip: alternate candidate with meaningful total profit, per-item profit, ROI, or raw margin. May require testing and does not automatically qualify as overnight.
- Watch / Test First: possible opportunity, but test with a small quantity before committing.
- Avoid: poor liquidity, suspicious pricing, weak history, volatile trend, or unstable margin behavior.

Return the response in readable Markdown.

Formatting rules:
- Do NOT use Markdown tables.
- Use clear section headings.
- Use short bullet points.
- Keep each item concise.
- Use this structure exactly.
- Number items.
- For overnight items, always show Raw margin/item, Net profit/item, and ROI.
- If a section has fewer than 10 items, say why.

## Quick Flips

Give up to {QUICK_FLIP_TARGET_COUNT} active quick-flip choices.

For each item include:
- Buy target
- Sell target
- Quantity
- Expected fill
- Liquidity
- Quick score
- Estimated profit
- ROI
- Confidence
- Trend
- Why it fits quick flipping
- Caution

## Overnight Flips

Give up to {OVERNIGHT_FLIP_TARGET_COUNT} overnight choices. Only include items that meet every overnight rule.

For each item include:
- Buy target
- Sell target
- Raw margin/item
- Net profit/item
- Quantity
- Expected fill
- Liquidity
- Overnight score
- Estimated total profit
- ROI
- Confidence
- Daily/weekly trend
- Why it fits overnight flipping
- Caution

## Additional Valuable Flips

Give up to {VALUE_FLIP_TARGET_COUNT} additional valuable choices.

For each item include:
- Buy target
- Sell target
- Raw margin/item
- Net profit/item
- Quantity
- Expected fill
- Liquidity
- Estimated total profit
- ROI
- Why it may be valuable
- Caution

## Skipped Because Already Traded Today

Briefly list same-day traded items that were intentionally not recommended again.

## Loss-Cut / Slot Recovery Advice

Use LIVE GE SLOT ANALYSIS to decide whether any current live offers should be canceled, repriced, held, or sold at a controlled loss to free a GE slot.

Only live SELLING offers can receive a controlled-loss recommendation. Live BUYING offers can only be canceled or repriced.

For each relevant live offer include:
- Item
- Held time
- Current live offer value
- Estimated fast-exit price
- Estimated fast-exit P/L
- Estimated loss %
- Slot-pressure impact
- Recommendation: Hold, Cancel, Reprice, or Accept controlled loss
- Why

## Watch / Test First

List backup or risky items that should be tested with a small quantity first.

## Avoid

List items that look risky and explain why.

## My Trades Feedback

Use the user's trade memory to give specific feedback. Include:
- One thing the user is doing well
- One repeated risk or mistake to watch
- Best item/style pattern from recent history
- Worst item/style pattern from recent history
- Whether open exposure is safe or too high
- Whether any stale positions should be repriced or exited to free a GE slot
- How today's recommendations should change because of this history

## Overall Plan

Give a short practical plan. Include:
- What to try first
- What to leave overnight
- What to avoid
- How much quantity to test with when warnings exist
- Whether there were enough qualifying overnight flips with raw_margin >= {MIN_OVERNIGHT_RAW_MARGIN_PER_ITEM:,}, positive post-tax profit, and ROI >= {MIN_OVERNIGHT_ROI_PERCENT}%
- How the user's My Trades history affects the plan
- How the same-day exclusion filter affected the choices
- Whether any current item should be sold at a controlled loss, repriced, or held because of the 8-slot limit

Scanner results:
{candidate_json}
"""


def ask_ai_for_advice(prompt):
    key_status = get_api_key_status()
    api_key = get_api_key(mark_used=True)

    if not api_key:
        raise RuntimeError(
            "No encrypted OpenAI API key is saved for this OSRSFlipper account. "
            "Open the dashboard Settings tab and save this user's OpenAI API key, "
            "or run: python openai_key_manager.py set. "
            "For safety, .env OPENAI_API_KEY fallback is disabled."
        )

    limit_status = assert_ai_daily_limit()

    print(
        "Using encrypted per-account OpenAI key: "
        f"{key_status.get('key_hint', 'set')}; "
        f"daily AI requests used: {limit_status['used']}/{limit_status['limit']}"
    )

    client = OpenAI(api_key=api_key)

    try:
        response = client.responses.create(
            model=MODEL,
            instructions=(
                "You are a careful OSRS flipping analyst. "
                "You explain tradeoffs clearly, separate quick flips from overnight flips, "
                "give the user many viable alternatives, "
                "use the user's My Trades history to personalize advice, "
                "never recommend items already traded today, "
                "identify repeated profit/loss patterns, consider open exposure, "
                "use stale-position analysis to suggest holding, repricing, or controlled loss exits when appropriate, "
                f"use daily and weekly trend data, enforce overnight rules of raw margin "
                f"at least {MIN_OVERNIGHT_RAW_MARGIN_PER_ITEM:,} gp, positive post-tax profit, "
                f"ROI at least {MIN_OVERNIGHT_ROI_PERCENT}%, and never guarantee profit."
            ),
            input=prompt
        )

        usage = log_ai_usage(
            model=MODEL,
            request_type="advisor",
            response=response,
            success=True
        )

        print(
            "AI usage logged: "
            f"{usage.get('total_tokens', 0)} total tokens"
        )

        return response.output_text

    except AuthenticationError as error:
        log_ai_usage(
            model=MODEL,
            request_type="advisor",
            success=False,
            error_message="OpenAI authentication failed."
        )
        raise RuntimeError(
            "OpenAI authentication failed. Check the encrypted API key saved for this OSRSFlipper account."
        ) from error

    except RateLimitError as error:
        log_ai_usage(
            model=MODEL,
            request_type="advisor",
            success=False,
            error_message="OpenAI rate limit or quota error."
        )
        raise RuntimeError(
            "OpenAI rate limit or quota error. Check this user's OpenAI API billing/quota."
        ) from error

    except APIError as error:
        log_ai_usage(
            model=MODEL,
            request_type="advisor",
            success=False,
            error_message=f"OpenAI API error: {error}"
        )
        raise RuntimeError(
            f"OpenAI API error: {error}"
        ) from error


def save_advice(advice):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        file.write(advice)

    return os.path.abspath(OUTPUT_FILE)


def generate_ai_advice(risk_profile="medium", limit=AI_SOURCE_ROW_LIMIT):
    """
    Reusable function for dashboard.py.

    Reads the latest scanner results from SQLite,
    removes items traded today,
    builds a larger balanced AI candidate pool,
    sends it to the OpenAI API,
    saves the advice to osrs_ai_advice.txt,
    saves the feedback into ai_trade_notes,
    and returns the advice text.
    """
    init_db()

    run_info = get_latest_run_info()

    if run_info is None:
        return "No scan history found. Run main.py or collector.py first."

    source_limit = max(int(limit), AI_SOURCE_ROW_LIMIT)

    candidates_df, todays_trades, excluded_items = get_latest_candidates(limit=source_limit)

    if candidates_df.empty:
        todays_summary = format_todays_trade_summary(todays_trades)
        excluded_summary = format_excluded_candidates_summary(excluded_items)

        return (
            "No candidates found in the latest scan after applying filters.\n\n"
            f"{todays_summary}\n\n"
            f"{excluded_summary}"
        )

    if risk_profile not in ("low", "medium", "high"):
        risk_profile = "medium"

    trade_memory = build_trade_ai_context(
        days=30,
        item_limit=15,
        recent_limit=20,
        open_limit=20,
        include_notes=True,
        account=RUNELITE_ACCOUNT
    )

    todays_trade_summary = format_todays_trade_summary(todays_trades)
    excluded_summary = format_excluded_candidates_summary(excluded_items)

    prompt = build_ai_prompt(
        run_info=run_info,
        candidates_df=candidates_df,
        risk_profile=risk_profile,
        trade_memory=trade_memory,
        todays_trade_summary=todays_trade_summary,
        excluded_summary=excluded_summary
    )

    advice = ask_ai_for_advice(prompt)
    save_advice(advice)

    save_ai_feedback(
        title="Advisor feedback",
        feedback=advice,
        tags=f"advisor,my-trades,today-filter,expanded-choices,live-slot-fix,stale-exits,slot-recovery,risk-{risk_profile}"
    )

    return advice


def main():
    print("\n==============================")
    print(" OSRS AI Flip Advisor")
    print("==============================")

    risk_profile = input("Risk profile (low/medium/high): ").lower().strip()

    if risk_profile not in ("low", "medium", "high"):
        print("Invalid risk profile. Defaulting to medium.")
        risk_profile = "medium"

    print("\nSending latest scanner results, My Trades memory, live GE slot analysis, saved AI settings, and today's trade exclusions to AI advisor...")
    print(f"AI choices: quick={QUICK_FLIP_TARGET_COUNT}, overnight={OVERNIGHT_FLIP_TARGET_COUNT}, value={VALUE_FLIP_TARGET_COUNT}")
    print(f"Same-day exclusion: {EXCLUDE_TODAYS_TRADED_ITEMS}")

    advice = generate_ai_advice(
        risk_profile=risk_profile,
        limit=AI_SOURCE_ROW_LIMIT
    )

    print("\n========== AI FLIP ADVICE ==========\n")
    print(advice)

    print(f"\nSaved AI advice to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
