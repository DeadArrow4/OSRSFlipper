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
from omitted_items import filter_omitted_df, list_omitted_items


from ai_capital_advisor_context import append_capital_context_to_trade_memory
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
        "volume_24h": 0,
        "window_vs_24h_percent": 0,
        "volume_vs_24h_percent": 0,
        "spread_24h_percent": 0,

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
        "market_context_warning",
        "market_momentum",
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
            sr.avg_low_24h,
            sr.avg_high_24h,
            sr.volume_24h,
            sr.window_vs_24h_percent,
            sr.volume_vs_24h_percent,
            sr.market_momentum,
            sr.market_context_warning,
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
    df = filter_omitted_df(df, "item_name")

    if df.empty:
        todays_trades = get_todays_traded_items()
        return df, todays_trades, []

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


def format_omitted_items_summary(max_items=50):
    omitted_items = list_omitted_items(include_restored=False)

    if not omitted_items:
        return "No user-omitted items are active."

    lines = [
        "User-omitted items: never recommend these unless the user explicitly restores them."
    ]

    for index, item in enumerate(omitted_items, start=1):
        if index > max_items:
            lines.append(f"- ...and {len(omitted_items) - max_items} more omitted items.")
            break

        id_text = f"ID {item.get('item_id')}" if item.get("item_id") else "No item ID"
        reason = item.get("reason") or ""
        reason_text = f", reason: {reason}" if reason else ""
        lines.append(f"- {item.get('item_name')} ({id_text}){reason_text}")

    return "\n".join(lines)


MAX_TRADE_MEMORY_CHARS = int(get_setting("ai_trade_memory_chars", 8000))
MAX_AI_PROMPT_CANDIDATES = int(get_setting("ai_prompt_candidate_limit", 35))


def _trim_text(value, max_chars=180):
    text = "" if value is None else str(value)

    if len(text) <= max_chars:
        return text

    return text[:max_chars].rstrip() + "..."


def _trim_block(text, max_chars):
    text = "" if text is None else str(text)

    if len(text) <= max_chars:
        return text

    return (
        text[:max_chars].rstrip()
        + "\n\n[Trimmed for faster AI response. Use My Trades tab for full history.]"
    )


def compact_candidates_for_ai(candidates_df, max_rows=MAX_AI_PROMPT_CANDIDATES):
    # Reduce scanner rows to the fields the AI actually needs.
    if candidates_df is None or candidates_df.empty:
        return []

    preferred_columns = [
        "ai_bucket",
        "item_name",
        "window_name",
        "target_buy",
        "target_sell",
        "quantity",
        "raw_margin",
        "profit_per_item",
        "total_profit",
        "roi_percent",
        "volume",
        "hourly_volume",
        "liquidity_score",
        "liquidity_rating",
        "expected_fill_time",
        "expected_fill_hours",
        "volume_24h",
        "window_vs_24h_percent",
        "volume_vs_24h_percent",
        "market_momentum",
        "market_context_warning",
        "quick_score",
        "overnight_score",
        "recommendation_score",
        "confidence",
        "signal",
        "daily_trend",
        "weekly_trend",
        "trend_confidence",
        "price_warning",
        "margin_warning",
        "trend_warning",
        "flip_category",
        "category_reason",
        "ai_bucket_reason",
    ]

    available_columns = [
        column for column in preferred_columns
        if column in candidates_df.columns
    ]

    work_df = candidates_df[available_columns].head(max_rows).copy()

    numeric_columns = [
        "target_buy",
        "target_sell",
        "quantity",
        "raw_margin",
        "profit_per_item",
        "total_profit",
        "roi_percent",
        "volume",
        "hourly_volume",
        "liquidity_score",
        "expected_fill_hours",
        "quick_score",
        "overnight_score",
        "recommendation_score",
        "volume_24h",
        "window_vs_24h_percent",
        "volume_vs_24h_percent",
    ]

    for column in numeric_columns:
        if column in work_df.columns:
            work_df[column] = pd.to_numeric(work_df[column], errors="coerce").round(2)

    text_columns = [
        "category_reason",
        "ai_bucket_reason",
        "price_warning",
        "margin_warning",
        "trend_warning",
        "market_context_warning",
        "signal",
        "confidence",
    ]

    for column in text_columns:
        if column in work_df.columns:
            work_df[column] = work_df[column].apply(lambda value: _trim_text(value, 180))

    return work_df.fillna("").to_dict("records")


MAX_TRADE_BOARD_AI_ROWS = int(get_setting("ai_trade_board_rows", 12))


def build_trade_board_ai_context(risk_profile="medium", limit=MAX_TRADE_BOARD_AI_ROWS):
    """Build compact Trade Board context for the AI Advisor."""
    try:
        from dashboard_data import get_trade_board_recommendations

        board_df, summary = get_trade_board_recommendations(
            limit=limit,
            risk_profile=risk_profile,
            minimum_profit=None,
        )

        if board_df is None or board_df.empty:
            return {
                "ok": False,
                "error": "Trade Board returned no rows.",
                "summary": summary or {},
                "rows": [],
            }

        preferred_columns = [
            "Action",
            "Item",
            "Window",
            "Buy",
            "Sell",
            "Qty",
            "Capital Needed",
            "Profit/Item",
            "Total Profit",
            "ROI",
            "Profit/1M",
            "Fill",
            "Liquidity",
            "Score",
            "Risk",
            "Confidence",
            "Warning",
            "Reason",
        ]

        available_columns = [
            column for column in preferred_columns
            if column in board_df.columns
        ]

        rows = (
            board_df[available_columns]
            .head(limit)
            .fillna("")
            .to_dict("records")
        )

        return {
            "ok": True,
            "error": "",
            "summary": summary or {},
            "rows": rows,
        }
    except Exception as error:
        return {
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
            "summary": {},
            "rows": [],
        }


def format_trade_board_ai_context(trade_board_context):
    """Format the Trade Board into a compact prompt block."""
    if not trade_board_context:
        return (
            "TRADE BOARD CONTEXT\\n"
            "- Trade Board context was not available for this AI run.\\n"
        )

    if not trade_board_context.get("ok"):
        return (
            "TRADE BOARD CONTEXT\\n"
            f"- Trade Board context failed or returned no rows: {trade_board_context.get('error', 'unknown error')}\\n"
            "- Fall back to scanner candidates, My Trades history, and safety rules.\\n"
        )

    summary = trade_board_context.get("summary") or {}
    rows = trade_board_context.get("rows") or []

    lines = [
        "TRADE BOARD CONTEXT",
        (
            "- Use this as the primary ranked recommendation source. "
            "The Trade Board already applies OSRSFlipper scoring, liquidity, risk, warnings, capital efficiency, and action labels."
        ),
        (
            f"- Latest scan run: {summary.get('latest_run_id', 'n/a')}; "
            f"ranked candidates: {summary.get('candidate_count', 0)}; "
            f"Buy Now: {summary.get('buy_now_count', 0)}; "
            f"Overnight: {summary.get('overnight_count', 0)}; "
            f"Test Small: {summary.get('test_small_count', 0)}; "
            f"Avoid/Wait: {summary.get('avoid_count', 0)}."
        ),
        "- Explain the best choices from this board first before discussing lower-ranked raw scanner candidates.",
        "- Do not blindly copy the board. Explain why a choice is useful, what could go wrong, and what order to test it in.",
        "",
        "Top Trade Board rows:",
    ]

    if not rows:
        lines.append("- No Trade Board rows were available.")
        return "\\n".join(lines)

    for index, row in enumerate(rows, start=1):
        lines.append(
            (
                f"{index}. {row.get('Action', 'n/a')} | "
                f"{row.get('Item', 'n/a')} | "
                f"Window: {row.get('Window', 'n/a')} | "
                f"Buy: {row.get('Buy', 'n/a')} | "
                f"Sell: {row.get('Sell', 'n/a')} | "
                f"Qty: {row.get('Qty', 'n/a')} | "
                f"Capital: {row.get('Capital Needed', 'n/a')} | "
                f"Profit: {row.get('Total Profit', 'n/a')} | "
                f"ROI: {row.get('ROI', 'n/a')} | "
                f"Fill: {row.get('Fill', 'n/a')} | "
                f"Score: {row.get('Score', 'n/a')} | "
                f"Risk: {row.get('Risk', 'n/a')} | "
                f"Confidence: {row.get('Confidence', 'n/a')} | "
                f"Warning: {row.get('Warning', 'n/a')} | "
                f"Reason: {row.get('Reason', 'n/a')}"
            )
        )

    return "\\n".join(lines)


def build_ai_prompt(
    run_info,
    candidates_df,
    risk_profile,
    trade_memory=None,
    todays_trade_summary=None,
    excluded_summary=None,
    omitted_summary=None,
    trade_board_context=None,
):
    compact_candidates = compact_candidates_for_ai(candidates_df)
    candidate_json = pd.DataFrame(compact_candidates).to_json(
        orient="records",
        indent=2
    )

    if trade_memory is None:
        trade_memory = "No local trade memory was provided."

    trade_memory = _trim_block(trade_memory, MAX_TRADE_MEMORY_CHARS)

    if todays_trade_summary is None:
        todays_trade_summary = "No today's-trade summary was provided."

    if excluded_summary is None:
        excluded_summary = "No excluded-candidate summary was provided."

    if omitted_summary is None:
        omitted_summary = "No user-omitted item summary was provided."

    trade_board_context_text = format_trade_board_ai_context(trade_board_context)

    cash_stack = int(run_info["cash_stack"])
    minimum_profit = int(run_info["minimum_profit"])
    run_id = int(run_info["run_id"])
    scanned_at = run_info["scanned_at"]

    return f"""
You are an OSRS Grand Exchange flipping analyst.

Goal:
Give the user the best practical trades to make now. Focus on action, risk, and why each trade is worth trying.

User context:
- Cash stack: {cash_stack:,} gp
- Minimum desired profit: {minimum_profit:,} gp
- Risk profile: {risk_profile}
- Latest scan run: {run_id}
- Latest scan time: {scanned_at}
- Same-day traded item exclusion enabled: {EXCLUDE_TODAYS_TRADED_ITEMS}

Hard rules:
- Do not guarantee profit.
- Use only the supplied scanner data and trade memory.
- Do not invent current prices.
- GE tax is already included in profit_per_item.
- Prefer realistic fills, strong liquidity, stable trend, good ROI, and repeatable profit.
- Avoid or downgrade rows with price_warning, margin_warning, trend_warning, poor liquidity, or weak confidence.
- Do not recommend items already traded today.
- Do not recommend user-omitted items.
- If a candidate was skipped because it was traded today, mention it only in the skipped section.
- Overnight picks must have raw_margin >= {MIN_OVERNIGHT_RAW_MARGIN_PER_ITEM:,}, profit_per_item > 0, and roi_percent >= {MIN_OVERNIGHT_ROI_PERCENT}%.
- For live SELLING offers only, you may suggest accepting a controlled small loss when the position is stale and slot pressure justifies freeing a GE slot.
- For live BUYING offers, suggest canceling or repricing only.

How to decide:
- Best immediate trades should have high quick_score, positive net profit, good liquidity, and short expected fill.
- Best overnight trades should have high overnight_score, enough raw margin per item, positive net/item, acceptable ROI, and stable trend.
- Test-first trades may have good upside but weaker liquidity, warnings, low confidence, or unstable trend.
- Avoid trades with suspicious margins, bad trend, poor liquidity, or low confidence.
- Use the user's trade history to adjust confidence. Repeated wins matter more than one-off wins.

Return Markdown only. Do not use tables.

Use this exact structure:

## Best Trades Right Now
Give 5 to 8 ranked picks. For each:
- Item
- Action: Buy now / Test small / Wait / Avoid
- Buy target
- Sell target
- Quantity
- Expected profit
- ROI
- Fill/liquidity
- Main reason
- Main caution

## Quick Flips
Give up to {QUICK_FLIP_TARGET_COUNT} active quick flips.

## Overnight Flips
Give only qualifying overnight flips. For each show raw margin/item, net profit/item, and ROI.

## Test Small
List candidates that are promising but should start with a small quantity.

## Avoid
List risky candidates and why.

## Current Open Trade / Slot Actions
Use trade memory only. Recommend hold, cancel, reprice, or controlled-loss exit where appropriate.

## My Trade History Feedback
Give:
- What is working
- Repeated risk/mistake
- Best recent item/style pattern
- Worst recent item/style pattern
- Whether open exposure is safe

## Simple Plan
Give a short step-by-step plan for what to buy first, what to leave overnight, and what to avoid.

AI Trade Board context:
{trade_board_context_text}

AI TRADE BOARD INSTRUCTIONS:
- Start the answer with a short Trade Board summary.
- Give the first 3 to 5 actions in priority order.
- Separate Buy Now, Overnight, Test Small, and Avoid / Wait.
- For each recommended trade, include target buy, target sell, quantity, expected profit, confidence, and caution.
- When Trade Board and raw scanner candidates disagree, prefer Trade Board unless there is a clear safety reason not to.
- Keep the answer practical and action-focused.

Today's trade exclusion memory:
{todays_trade_summary}

Excluded scanner candidates:
{excluded_summary}

User-omitted items:
{omitted_summary}

User trade memory:
{trade_memory}

Compact scanner candidates:
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
                "never recommend user-omitted items, "
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
        omitted_summary = format_omitted_items_summary()

        return (
            "No candidates found in the latest scan after applying filters.\n\n"
            f"{todays_summary}\n\n"
            f"{excluded_summary}\n\n"
            f"{omitted_summary}"
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
    omitted_summary = format_omitted_items_summary()

    trade_board_context = build_trade_board_ai_context(
        risk_profile=risk_profile,
        limit=MAX_TRADE_BOARD_AI_ROWS,
    )

    trade_memory = append_capital_context_to_trade_memory(trade_memory)
    
    prompt = build_ai_prompt(
        run_info=run_info,
        candidates_df=candidates_df,
        risk_profile=risk_profile,
        trade_memory=trade_memory,
        todays_trade_summary=todays_trade_summary,
        excluded_summary=excluded_summary,
        omitted_summary=omitted_summary,
        trade_board_context=trade_board_context,)

    advice = ask_ai_for_advice(prompt)
    save_advice(advice)

    save_ai_feedback(
        title="Advisor feedback",
        feedback=advice,
        tags=f"advisor,trade-board,my-trades,today-filter,expanded-choices,live-slot-fix,stale-exits,slot-recovery,risk-{risk_profile}"
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
