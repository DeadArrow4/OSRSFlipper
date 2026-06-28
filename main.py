import os
from datetime import datetime

import pandas as pd

from api import load_market_data, load_trend_data_for_items
from capital_budget import get_effective_cash_stack
from scanner import parse_gp, scan_market, format_gp
from recommender import apply_recommendations
from trend_analyzer import enrich_rows_with_trends, TREND_DATA_MAX_ITEMS
from account_context import BASE_DIR
from database import (
    init_db,
    create_scan_run,
    save_scan_rows,
    get_recent_profitable,
    enrich_rows_with_history
)

# =========================
# SETTINGS
# =========================

TOP_RESULTS = 25

MIN_VOLUME_5M = 1
MIN_VOLUME_1H = 5

MIN_HISTORY_SAMPLES = 3

# Only load timeseries trend data for the strongest candidates.
# Do not run trend requests for every item in the game.
MAX_TREND_ITEMS = TREND_DATA_MAX_ITEMS

DISPLAY_COLUMNS = [
    "Recommendation",
    "Recommendation Score",
    "Risk Level",
    "Flip Category",
    "Category Reason",

    "Recommendation Rank",
    "Window Rank",
    "Item",
    "Window",
    "Price Source",

    "Target Buy",
    "Target Sell",
    "Avg Low",
    "Avg High",

    "Buy vs Avg Low %",
    "Sell vs Avg High %",
    "Price Warning",

    "Qty",
    "Cost",
    "Profit/Item",
    "Total Profit",
    "ROI %",

    "Volume",
    "Hourly Volume",
    "Liquidity Score",
    "Liquidity Rating",
    "Expected Fill Time",

    "Daily Trend",
    "Weekly Trend",
    "Long Term Trend",
    "Daily Change %",
    "Weekly Change %",
    "Long Term Change %",
    "Daily Volatility %",
    "Weekly Volatility %",
    "Price Position 7D %",
    "Trend Confidence",
    "Trend Warning",
    "Quick Score",
    "Overnight Score",

    "Confidence",
    "Hist Samples",
    "Avg Margin",
    "Margin Delta %",
    "Margin Warning",
    "Signal",

    "Score",
    "Why"
]


def print_table(title, rows, fallback_rows=None):
    print(f"\n========== {title} ==========\n")

    if rows:
        df = pd.DataFrame(rows)

        display_columns = [
            column for column in DISPLAY_COLUMNS
            if column in df.columns
        ]

        display_df = df[display_columns]

        print(display_df.head(TOP_RESULTS).to_string(index=False))
        return df

    print("No tax-profitable flips found in this list.")

    if fallback_rows:
        print("\nShowing watchlist items with positive raw spread instead:\n")
        df = pd.DataFrame(fallback_rows)

        display_columns = [
            column for column in DISPLAY_COLUMNS
            if column in df.columns
        ]

        display_df = df[display_columns]

        print(display_df.head(TOP_RESULTS).to_string(index=False))
        return df

    return pd.DataFrame()


def save_csv_safely(df, filename):
    """
    Saves CSV safely.

    If the file is open in Excel and cannot be overwritten,
    saves a timestamped backup instead.
    """
    if df.empty:
        print(f"No rows to save for {filename}.")
        return None

    target_path = os.path.join(str(BASE_DIR), filename)

    try:
        df.to_csv(target_path, index=False)
        return target_path

    except PermissionError:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = filename.replace(".csv", f"_{timestamp}.csv")
        backup_path = os.path.join(str(BASE_DIR), backup_name)

        df.to_csv(backup_path, index=False)

        print(f"\nCould not overwrite {filename}.")
        print("It may be open in Excel.")
        print(f"Saved backup instead: {backup_path}")

        return backup_path


def get_top_candidate_item_ids(row_groups, max_items=50):
    """
    Gets item IDs for the strongest current candidates.

    We only load trend/timeseries data for these items because item timeseries
    requires separate API calls per item.
    """
    candidate_rows = []

    for rows in row_groups:
        candidate_rows.extend(rows)

    if not candidate_rows:
        return []

    candidate_rows.sort(
        key=lambda row: (
            row.get("Score", 0),
            row.get("Total Profit", 0),
            row.get("Liquidity Score", 0),
            row.get("Volume", 0)
        ),
        reverse=True
    )

    item_ids = []

    for row in candidate_rows:
        item_id = row.get("Item ID")

        if item_id is None:
            continue

        if item_id not in item_ids:
            item_ids.append(item_id)

        if len(item_ids) >= max_items:
            break

    return item_ids


def enrich_all_rows_with_trends(row_groups):
    """
    Loads trend data for top candidates and applies trend scoring.
    """
    item_ids = get_top_candidate_item_ids(
        row_groups=row_groups,
        max_items=MAX_TREND_ITEMS
    )

    if not item_ids:
        print("No candidates available for trend analysis.")
        return

    trend_data = load_trend_data_for_items(
        item_ids=item_ids,
        max_items=MAX_TREND_ITEMS
    )

    for rows in row_groups:
        enrich_rows_with_trends(
            rows=rows,
            trend_data_by_item=trend_data
        )


def print_signal_summary(rows):
    if not rows:
        return

    strong_spikes = [
        row for row in rows
        if row.get("Signal") == "Strong margin spike"
    ]

    above_average = [
        row for row in rows
        if row.get("Signal") == "Above average"
    ]

    margin_warnings = [
        row for row in rows
        if row.get("Margin Warning") and row.get("Margin Warning") != "OK"
    ]

    price_warnings = [
        row for row in rows
        if row.get("Price Warning") and row.get("Price Warning") != "OK"
    ]

    trend_warnings = [
        row for row in rows
        if row.get("Trend Warning") and row.get("Trend Warning") != "OK"
    ]

    liquidity_warnings = [
        row for row in rows
        if row.get("Liquidity Rating") in ("Poor", "Thin")
    ]

    if (
        not strong_spikes
        and not above_average
        and not margin_warnings
        and not price_warnings
        and not trend_warnings
        and not liquidity_warnings
    ):
        return

    print("\n========== WARNINGS / SIGNALS ==========\n")

    if strong_spikes:
        print("Strong margin spikes:\n")

        for row in strong_spikes[:10]:
            print(
                f"{row['Item']} | {row['Window']} | "
                f"Rank {row.get('Window Rank')} | "
                f"Profit {format_gp(row['Total Profit'])} | "
                f"ROI {row['ROI %']}% | "
                f"Margin vs avg {row.get('Margin Delta %')}% | "
                f"Fill {row.get('Expected Fill Time')}"
            )

    if above_average:
        print("\nAbove average margins:\n")

        for row in above_average[:10]:
            print(
                f"{row['Item']} | {row['Window']} | "
                f"Rank {row.get('Window Rank')} | "
                f"Profit {format_gp(row['Total Profit'])} | "
                f"ROI {row['ROI %']}% | "
                f"Margin vs avg {row.get('Margin Delta %')}% | "
                f"Fill {row.get('Expected Fill Time')}"
            )

    if margin_warnings:
        print("\nMargin warnings:\n")

        for row in margin_warnings[:10]:
            print(
                f"{row['Item']} | {row['Window']} | "
                f"Margin Delta {row.get('Margin Delta %')}% | "
                f"{row.get('Margin Warning')}"
            )

    if price_warnings:
        print("\nPrice warnings:\n")

        for row in price_warnings[:10]:
            print(
                f"{row['Item']} | {row['Window']} | "
                f"Buy vs Avg Low {row.get('Buy vs Avg Low %')}% | "
                f"Sell vs Avg High {row.get('Sell vs Avg High %')}% | "
                f"{row.get('Price Warning')}"
            )

    if trend_warnings:
        print("\nTrend warnings:\n")

        for row in trend_warnings[:10]:
            print(
                f"{row['Item']} | {row['Window']} | "
                f"Daily {row.get('Daily Trend')} | "
                f"Weekly {row.get('Weekly Trend')} | "
                f"7D Position {row.get('Price Position 7D %')}% | "
                f"{row.get('Trend Warning')}"
            )

    if liquidity_warnings:
        print("\nLiquidity warnings:\n")

        for row in liquidity_warnings[:10]:
            print(
                f"{row['Item']} | {row['Window']} | "
                f"Qty {row.get('Qty')} | "
                f"1h Volume {row.get('Hourly Volume')} | "
                f"Liquidity {row.get('Liquidity Rating')} | "
                f"Expected Fill {row.get('Expected Fill Time')}"
            )


def print_category_summary(rows):
    if not rows:
        return

    categories = {
        "Quick Flip": [],
        "Overnight Flip": [],
        "Watch / Test First": [],
        "Avoid": []
    }

    for row in rows:
        category = row.get("Flip Category")

        if category in categories:
            categories[category].append(row)

    print("\n========== QUICK / OVERNIGHT SUMMARY ==========\n")

    for category, category_rows in categories.items():
        if not category_rows:
            continue

        print(f"{category}:")

        for row in category_rows[:5]:
            print(
                f"- {row.get('Item')} | {row.get('Window')} | "
                f"Quick {row.get('Quick Score')} | "
                f"Overnight {row.get('Overnight Score')} | "
                f"Fill {row.get('Expected Fill Time')} | "
                f"Trend {row.get('Weekly Trend')} | "
                f"Profit {format_gp(row.get('Total Profit', 0))}"
            )

        print()


def print_recent_database_rows():
    recent_rows = get_recent_profitable(limit=10)

    if not recent_rows:
        return

    print("\n========== RECENT DATABASE HISTORY ==========\n")

    for row in recent_rows:
        (
            scanned_at,
            item_name,
            window_name,
            target_buy,
            target_sell,
            quantity,
            total_profit,
            roi_percent,
            volume,
            confidence,
            hist_samples,
            avg_raw_margin,
            margin_delta_percent,
            signal
        ) = row

        print(
            f"{scanned_at} | {window_name} | {item_name} | "
            f"Buy {format_gp(target_buy)} | Sell {format_gp(target_sell)} | "
            f"Qty {quantity} | Profit {format_gp(total_profit)} | "
            f"ROI {roi_percent}% | Volume {volume} | {confidence} | "
            f"Hist Samples {hist_samples} | "
            f"Avg Margin {avg_raw_margin} | "
            f"Delta {margin_delta_percent}% | "
            f"{signal}"
        )


def main():
    print("\n==============================")
    print(" OSRS GE Flip Scanner")
    print("==============================")

    manual_cash_stack = parse_gp(input("Cash stack: "))
    budget = get_effective_cash_stack(manual_cash_stack)
    cash_stack = int(budget.get("cash_stack", manual_cash_stack))
    print(
        "Effective scanner budget: "
        f"{format_gp(cash_stack)} "
        f"({budget.get('source')}; manual cap {format_gp(budget.get('manual_cash_stack', manual_cash_stack))})"
    )
    minimum_profit = parse_gp(input("Min profit: "))

    risk_profile = input("Risk profile (low/medium/high): ").lower().strip()

    if risk_profile not in ("low", "medium", "high"):
        print("Invalid risk profile. Defaulting to medium.")
        risk_profile = "medium"

    init_db()

    latest_data, recent_data, older_data, item_lookup = load_market_data()

    recent_results, recent_watchlist = scan_market(
        price_data=recent_data,
        item_lookup=item_lookup,
        window_name="5m",
        min_volume=MIN_VOLUME_5M,
        cash_stack=cash_stack,
        minimum_profit=minimum_profit,
        latest_data=latest_data,
        use_latest=True,
        hourly_data=older_data
    )

    older_results, older_watchlist = scan_market(
        price_data=older_data,
        item_lookup=item_lookup,
        window_name="1h",
        min_volume=MIN_VOLUME_1H,
        cash_stack=cash_stack,
        minimum_profit=minimum_profit,
        latest_data=latest_data,
        use_latest=True,
        hourly_data=older_data
    )

    # Add historical analysis before saving this run.
    # This prevents the current scan from comparing against itself.
    enrich_rows_with_history(
        recent_results,
        min_samples=MIN_HISTORY_SAMPLES
    )

    enrich_rows_with_history(
        older_results,
        min_samples=MIN_HISTORY_SAMPLES
    )

    enrich_rows_with_history(
        recent_watchlist,
        min_samples=MIN_HISTORY_SAMPLES
    )

    enrich_rows_with_history(
        older_watchlist,
        min_samples=MIN_HISTORY_SAMPLES
    )

    # Add daily / weekly trend analysis before recommendations.
    # This gives the recommender and AI better quick/overnight context.
    enrich_all_rows_with_trends([
        recent_results,
        older_results,
        recent_watchlist,
        older_watchlist
    ])

    apply_recommendations(recent_results, risk_profile=risk_profile)
    apply_recommendations(older_results, risk_profile=risk_profile)
    apply_recommendations(recent_watchlist, risk_profile=risk_profile)
    apply_recommendations(older_watchlist, risk_profile=risk_profile)

    recent_df = print_table(
        "RECENT FLIPS - 5 MINUTE MARKET",
        recent_results,
        recent_watchlist
    )

    older_df = print_table(
        "OLDER / STABLE FLIPS - 1 HOUR MARKET",
        older_results,
        older_watchlist
    )

    print_signal_summary(recent_results + older_results)
    print_category_summary(recent_results + older_results)

    run_id, scanned_at = create_scan_run(
        cash_stack=cash_stack,
        minimum_profit=minimum_profit
    )

    recent_csv = save_csv_safely(recent_df, "osrs_recent_flips.csv")
    older_csv = save_csv_safely(older_df, "osrs_older_flips.csv")

    saved_count = 0

    saved_count += save_scan_rows(
        run_id=run_id,
        scanned_at=scanned_at,
        rows=recent_results,
        result_type="profitable"
    )

    saved_count += save_scan_rows(
        run_id=run_id,
        scanned_at=scanned_at,
        rows=older_results,
        result_type="profitable"
    )

    saved_count += save_scan_rows(
        run_id=run_id,
        scanned_at=scanned_at,
        rows=recent_watchlist[:TOP_RESULTS],
        result_type="watchlist"
    )

    saved_count += save_scan_rows(
        run_id=run_id,
        scanned_at=scanned_at,
        rows=older_watchlist[:TOP_RESULTS],
        result_type="watchlist"
    )

    print("\n========== SAVE SUMMARY ==========\n")

    if recent_csv:
        print(f"Saved recent flips to: {recent_csv}")

    if older_csv:
        print(f"Saved older flips to:  {older_csv}")

    print(f"Saved {saved_count} rows to SQLite database.")
    print(f"Database file: {BASE_DIR / 'osrs_flip_scanner.db'}")

    print_recent_database_rows()


if __name__ == "__main__":
    main()
