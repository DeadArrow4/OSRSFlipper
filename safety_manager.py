import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from account_context import BASE_DIR
from omitted_items import filter_omitted_df
from settings_manager import get_setting, set_setting, ensure_default_settings


DB_FILE = BASE_DIR / "osrs_flip_scanner.db"
REPORT_FILE = BASE_DIR / "logs" / "safety_review.csv"


def get_connection():
    return sqlite3.connect(DB_FILE)


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def normalize_name(name):
    return str(name or "").strip().lower().replace(" ", "_").replace("-", "_")


def pick(row, *names, default=None):
    """
    Safely reads a value from a pandas Series using several possible column names.
    """
    normalized = {normalize_name(col): col for col in row.index}

    for name in names:
        key = normalize_name(name)

        if key in normalized:
            value = row.get(normalized[key])

            if pd.notna(value):
                return value

    return default


def as_float(value, default=0.0):
    try:
        if value is None:
            return default

        text = str(value).replace(",", "").replace("gp", "").replace("%", "").strip()

        if not text:
            return default

        return float(text)
    except Exception:
        return default


def as_int(value, default=0):
    try:
        return int(as_float(value, default=default))
    except Exception:
        return default


def get_latest_run_id():
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT MAX(run_id) FROM scan_results")
        value = cursor.fetchone()[0]
    except Exception:
        value = None

    conn.close()

    return value


def load_latest_scan_rows(limit=500):
    latest_run_id = get_latest_run_id()

    if latest_run_id is None:
        return pd.DataFrame()

    conn = get_connection()

    try:
        df = pd.read_sql_query(
            """
            SELECT *
            FROM scan_results
            WHERE run_id = ?
            """,
            conn,
            params=(latest_run_id,)
        )
    finally:
        conn.close()

    if df.empty:
        return df

    df = filter_omitted_df(df, "item_name")

    if df.empty:
        return df

    # Prefer high-score rows, but stay flexible if columns are missing.
    sort_columns = []

    for column in [
        "recommendation_score",
        "quick_score",
        "overnight_score",
        "total_profit",
        "roi_percent",
        "profit"
    ]:
        if column in df.columns:
            sort_columns.append(column)

    if sort_columns:
        df = df.sort_values(by=sort_columns, ascending=False)

    return df.head(int(limit or 500))


def estimate_ge_tax_per_item(sell_price):
    sell_price = max(0, as_int(sell_price, 0))

    if sell_price <= 0:
        return 0

    # OSRS GE tax: 2%, capped at 5m per item in current project logic.
    # Kept local to avoid depending on trade_tracker internals.
    return min(int(sell_price * 0.02), 5_000_000)


def classify_cash_exposure(total_cost, cash_stack):
    if cash_stack <= 0:
        return "Unknown"

    percent = (total_cost / cash_stack) * 100

    if percent >= 50:
        return "Very high"

    if percent >= 25:
        return "High"

    if percent >= 10:
        return "Medium"

    return "Low"


def build_risk_flags(row, test_quantity, total_cost, cash_stack):
    flags = []

    liquidity_rating = str(
        pick(row, "Liquidity Rating", "liquidity_rating", default="")
    ).lower()

    expected_fill_hours = as_float(
        pick(row, "Expected Fill Hours", "expected_fill_hours", default=0),
        0
    )

    trend_warning = str(
        pick(row, "Trend Warning", "trend_warning", default="")
    ).strip()

    daily_trend = str(
        pick(row, "Daily Trend", "daily_trend", default="")
    ).lower()

    weekly_trend = str(
        pick(row, "Weekly Trend", "weekly_trend", default="")
    ).lower()

    roi = as_float(
        pick(row, "ROI %", "roi_percent", "roi", default=0),
        0
    )

    margin = as_float(
        pick(row, "Raw Margin", "raw_margin", "margin", "profit_per_item", default=0),
        0
    )

    buy_price = as_float(
        pick(row, "Buy Price", "Target Buy", "target_buy", "low", "latest_low", "buy_price", default=0),
        0
    )

    if "low" in liquidity_rating or "thin" in liquidity_rating:
        flags.append("Low liquidity")

    if expected_fill_hours >= 8:
        flags.append("Slow expected fill")

    if trend_warning and trend_warning.lower() not in ("none", "ok", "nan"):
        flags.append(trend_warning)

    if "down" in daily_trend and "down" in weekly_trend:
        flags.append("Daily and weekly trend both down")

    if roi < 1:
        flags.append("Low ROI")

    if margin <= 0:
        flags.append("No positive raw margin")

    if buy_price <= 0:
        flags.append("Missing buy price")

    if cash_stack > 0:
        exposure_percent = (total_cost / cash_stack) * 100

        if exposure_percent > as_float(get_setting("max_single_item_cash_percent", 10.0), 10.0):
            flags.append("Exceeds per-item cash exposure setting")

    if test_quantity <= 0:
        flags.append("No safe test quantity")

    return flags


def safety_verdict(flags, recommendation, category):
    text = f"{recommendation} {category}".lower()

    hard_flags = [
        "no positive raw margin",
        "missing buy price",
        "no safe test quantity"
    ]

    if any(flag.lower() in hard_flags for flag in flags):
        return "Avoid"

    if "avoid" in text:
        return "Avoid"

    if len(flags) >= 3:
        return "Watch / Test Tiny"

    if len(flags) >= 1:
        return "Test First"

    return "Safer Test"


def suggested_test_quantity(row, cash_stack):
    max_cash_percent = as_float(get_setting("max_single_item_cash_percent", 10.0), 10.0)
    max_test_quantity_setting = as_int(get_setting("max_test_quantity", 25), 25)

    buy_price = as_float(
        pick(row, "Buy Price", "Target Buy", "target_buy", "low", "latest_low", "buy_price", default=0),
        0
    )

    buy_limit = as_int(
        pick(row, "Limit", "Buy Limit", "buy_limit", "ge_limit", default=0),
        0
    )

    if buy_price <= 0 or cash_stack <= 0:
        return 0

    cash_budget = cash_stack * (max_cash_percent / 100.0)
    affordable_qty = int(cash_budget // buy_price)

    if buy_limit > 0:
        limit_test_qty = max(1, int(buy_limit * 0.05))
    else:
        limit_test_qty = max_test_quantity_setting

    qty = min(
        max_test_quantity_setting,
        max(1, affordable_qty),
        max(1, limit_test_qty)
    )

    return max(0, qty)


def review_scan_row(row, cash_stack):
    item_name = pick(row, "Item", "Item Name", "item_name", "name", default="Unknown item")
    item_id = pick(row, "Item ID", "item_id", "id", default="")

    buy_price = as_float(
        pick(row, "Buy Price", "Target Buy", "target_buy", "low", "latest_low", "buy_price", default=0),
        0
    )

    sell_price = as_float(
        pick(row, "Sell Price", "Target Sell", "target_sell", "high", "latest_high", "sell_price", default=0),
        0
    )

    raw_margin = as_float(
        pick(row, "Raw Margin", "raw_margin", "margin", default=sell_price - buy_price),
        sell_price - buy_price
    )

    ge_tax = estimate_ge_tax_per_item(sell_price)
    net_margin = raw_margin - ge_tax

    roi = 0.0

    if buy_price > 0:
        roi = (net_margin / buy_price) * 100

    recommendation = str(
        pick(row, "Recommendation", "recommendation", default="")
    )

    category = str(
        pick(row, "Flip Category", "flip_category", "category", default="")
    )

    test_qty = suggested_test_quantity(row, cash_stack)
    total_cost = test_qty * buy_price
    projected_test_profit = test_qty * net_margin

    flags = build_risk_flags(row, test_qty, total_cost, cash_stack)
    verdict = safety_verdict(flags, recommendation, category)

    return {
        "Safety Verdict": verdict,
        "Item": item_name,
        "Item ID": item_id,
        "Category": category,
        "Recommendation": recommendation,
        "Suggested Test Qty": int(test_qty),
        "Buy Price": int(buy_price),
        "Sell Price": int(sell_price),
        "Raw Margin": int(raw_margin),
        "GE Tax/Item": int(ge_tax),
        "Net Margin/Item": int(net_margin),
        "Net ROI %": round(roi, 2),
        "Test Cost": int(total_cost),
        "Projected Test Profit": int(projected_test_profit),
        "Cash Exposure": classify_cash_exposure(total_cost, cash_stack),
        "Liquidity": pick(row, "Liquidity Rating", "liquidity_rating", default=""),
        "Expected Fill": pick(row, "Expected Fill Time", "expected_fill_time", default=""),
        "Daily Trend": pick(row, "Daily Trend", "daily_trend", default=""),
        "Weekly Trend": pick(row, "Weekly Trend", "weekly_trend", default=""),
        "Flags": "; ".join(flags) if flags else "None",
    }


def build_safety_review(limit=100):
    ensure_default_settings()

    cash_stack = as_float(get_setting("cash_stack", 0), 0)
    source_limit = max(100, int(limit or 100) * 3)
    df = load_latest_scan_rows(limit=source_limit)

    if df.empty:
        return pd.DataFrame()

    rows = []

    for _, row in df.iterrows():
        reviewed = review_scan_row(row, cash_stack)

        # Keep useful rows; avoid overwhelming with obvious avoids unless high ranked.
        rows.append(reviewed)

    result = pd.DataFrame(rows)

    if result.empty:
        return result

    verdict_order = {
        "Safer Test": 0,
        "Test First": 1,
        "Watch / Test Tiny": 2,
        "Avoid": 3
    }

    result["_verdict_order"] = result["Safety Verdict"].map(verdict_order).fillna(9)
    result = result.sort_values(
        by=["_verdict_order", "Projected Test Profit", "Net ROI %"],
        ascending=[True, False, False]
    )
    result = result.drop(columns=["_verdict_order"])

    return result.head(int(limit or 100))


def write_safety_review(limit=100):
    REPORT_FILE.parent.mkdir(exist_ok=True)
    df = build_safety_review(limit=limit)
    df.to_csv(REPORT_FILE, index=False, encoding="utf-8-sig")
    return REPORT_FILE, df


def main():
    parser = argparse.ArgumentParser(
        description="Generate OSRSFlipper trade safety review."
    )

    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--csv", action="store_true")

    args = parser.parse_args()

    path, df = write_safety_review(limit=args.limit)

    print("\n==============================")
    print(" Trade Safety Review")
    print("==============================")
    print(f"Rows: {len(df)}")
    print(f"CSV: {path}")
    print()

    if df.empty:
        print("No latest scan rows found. Run collector/main scanner first.")
        return

    print(df.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
