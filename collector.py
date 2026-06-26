import time
from datetime import datetime

from api import load_market_data, load_trend_data_for_items
from scanner import parse_gp, scan_market, format_gp
from recommender import apply_recommendations
from trend_analyzer import enrich_rows_with_trends, TREND_DATA_MAX_ITEMS
from database import (
    init_db,
    create_scan_run,
    save_scan_rows,
    enrich_rows_with_history
)

# =========================
# COLLECTOR SETTINGS
# =========================

SCAN_INTERVAL_SECONDS = 300  # 5 minutes

MIN_VOLUME_5M = 1
MIN_VOLUME_1H = 5

MIN_HISTORY_SAMPLES = 3

TOP_WATCHLIST_TO_SAVE = 25

# Only load timeseries trend data for the strongest candidates.
# Do not run trend requests for every item in the game.
MAX_TREND_ITEMS = TREND_DATA_MAX_ITEMS


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


def print_cycle_summary(recent_results, older_results):
    all_results = recent_results + older_results

    if not all_results:
        print("No profitable results this cycle.")
        return

    strong_spikes = [
        row for row in all_results
        if row.get("Signal") == "Strong margin spike"
    ]

    above_average = [
        row for row in all_results
        if row.get("Signal") == "Above average"
    ]

    margin_warnings = [
        row for row in all_results
        if row.get("Margin Warning") and row.get("Margin Warning") != "OK"
    ]

    price_warnings = [
        row for row in all_results
        if row.get("Price Warning") and row.get("Price Warning") != "OK"
    ]

    trend_warnings = [
        row for row in all_results
        if row.get("Trend Warning") and row.get("Trend Warning") != "OK"
    ]

    liquidity_warnings = [
        row for row in all_results
        if row.get("Liquidity Rating") in ("Poor", "Thin")
    ]

    if strong_spikes:
        print("\nStrong margin spikes found:")

        for row in strong_spikes[:10]:
            print(
                f"- {row['Item']} | {row['Window']} | "
                f"Rank {row.get('Window Rank')} | "
                f"Profit {format_gp(row['Total Profit'])} | "
                f"ROI {row['ROI %']}% | "
                f"Margin Delta {row.get('Margin Delta %')}% | "
                f"Fill {row.get('Expected Fill Time')}"
            )

    if above_average:
        print("\nAbove average margins found:")

        for row in above_average[:10]:
            print(
                f"- {row['Item']} | {row['Window']} | "
                f"Rank {row.get('Window Rank')} | "
                f"Profit {format_gp(row['Total Profit'])} | "
                f"ROI {row['ROI %']}% | "
                f"Margin Delta {row.get('Margin Delta %')}% | "
                f"Fill {row.get('Expected Fill Time')}"
            )

    if margin_warnings:
        print("\nMargin warnings:")

        for row in margin_warnings[:10]:
            print(
                f"- {row['Item']} | {row['Window']} | "
                f"Margin Delta {row.get('Margin Delta %')}% | "
                f"{row.get('Margin Warning')}"
            )

    if price_warnings:
        print("\nPrice warnings:")

        for row in price_warnings[:10]:
            print(
                f"- {row['Item']} | {row['Window']} | "
                f"Buy vs Avg Low {row.get('Buy vs Avg Low %')}% | "
                f"Sell vs Avg High {row.get('Sell vs Avg High %')}% | "
                f"{row.get('Price Warning')}"
            )

    if trend_warnings:
        print("\nTrend warnings:")

        for row in trend_warnings[:10]:
            print(
                f"- {row['Item']} | {row['Window']} | "
                f"Daily {row.get('Daily Trend')} | "
                f"Weekly {row.get('Weekly Trend')} | "
                f"7D Position {row.get('Price Position 7D %')}% | "
                f"{row.get('Trend Warning')}"
            )

    if liquidity_warnings:
        print("\nLiquidity warnings:")

        for row in liquidity_warnings[:10]:
            print(
                f"- {row['Item']} | {row['Window']} | "
                f"Qty {row.get('Qty')} | "
                f"1h Volume {row.get('Hourly Volume')} | "
                f"Liquidity {row.get('Liquidity Rating')} | "
                f"Expected Fill {row.get('Expected Fill Time')}"
            )

    if (
        not strong_spikes
        and not above_average
        and not margin_warnings
        and not price_warnings
        and not trend_warnings
        and not liquidity_warnings
    ):
        print("No strong historical signals or warnings this cycle.")


def print_category_summary(recent_results, older_results):
    all_results = recent_results + older_results

    if not all_results:
        return

    categories = {
        "Quick Flip": [],
        "Overnight Flip": [],
        "Watch / Test First": [],
        "Avoid": []
    }

    for row in all_results:
        category = row.get("Flip Category")

        if category in categories:
            categories[category].append(row)

    print("\nQuick / Overnight category summary:")

    for category, rows in categories.items():
        if not rows:
            continue

        print(f"\n{category}:")

        for row in rows[:5]:
            print(
                f"- {row.get('Item')} | {row.get('Window')} | "
                f"Quick {row.get('Quick Score')} | "
                f"Overnight {row.get('Overnight Score')} | "
                f"Fill {row.get('Expected Fill Time')} | "
                f"Trend {row.get('Weekly Trend')} | "
                f"Profit {format_gp(row.get('Total Profit', 0))}"
            )


def run_collection_cycle(cash_stack, minimum_profit, risk_profile):
    print("\n==============================")
    print(" OSRS Auto Collector Cycle")
    print("==============================")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Cash stack: {format_gp(cash_stack)}")
    print(f"Minimum profit: {format_gp(minimum_profit)}")
    print(f"Risk profile: {risk_profile}")

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

    apply_recommendations(
        recent_results,
        risk_profile=risk_profile
    )

    apply_recommendations(
        older_results,
        risk_profile=risk_profile
    )

    apply_recommendations(
        recent_watchlist,
        risk_profile=risk_profile
    )

    apply_recommendations(
        older_watchlist,
        risk_profile=risk_profile
    )

    run_id, scanned_at = create_scan_run(
        cash_stack=cash_stack,
        minimum_profit=minimum_profit
    )

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
        rows=recent_watchlist[:TOP_WATCHLIST_TO_SAVE],
        result_type="watchlist"
    )

    saved_count += save_scan_rows(
        run_id=run_id,
        scanned_at=scanned_at,
        rows=older_watchlist[:TOP_WATCHLIST_TO_SAVE],
        result_type="watchlist"
    )

    print(f"\nSaved {saved_count} rows to SQLite.")

    print_cycle_summary(
        recent_results=recent_results,
        older_results=older_results
    )

    print_category_summary(
        recent_results=recent_results,
        older_results=older_results
    )

    print(f"\nFinished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def main():
    print("\n==============================")
    print(" OSRS GE Auto Collector")
    print("==============================")

    cash_stack = parse_gp(input("Cash stack: "))
    minimum_profit = parse_gp(input("Min profit: "))

    risk_profile = input("Risk profile (low/medium/high): ").lower().strip()

    if risk_profile not in ("low", "medium", "high"):
        print("Invalid risk profile. Defaulting to medium.")
        risk_profile = "medium"

    init_db()

    print("\nCollector started.")
    print("Press CTRL + C to stop.")
    print(f"Scan interval: {SCAN_INTERVAL_SECONDS} seconds")

    while True:
        try:
            run_collection_cycle(
                cash_stack=cash_stack,
                minimum_profit=minimum_profit,
                risk_profile=risk_profile
            )

            print(f"\nWaiting {SCAN_INTERVAL_SECONDS} seconds until next scan...")

            time.sleep(SCAN_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\nCollector stopped by user.")
            break

        except Exception as error:
            print("\nAn error occurred during collection:")
            print(error)
            print(f"Waiting {SCAN_INTERVAL_SECONDS} seconds before retrying...")

            time.sleep(SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
