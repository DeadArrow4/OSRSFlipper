import sqlite3
import pandas as pd

DB_FILE = "osrs_flip_scanner.db"


def get_connection():
    return sqlite3.connect(DB_FILE)


def format_gp(value):
    if value is None:
        return "N/A"

    return f"{int(value):,}"


def print_section(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80 + "\n")


def run_query(query, params=None):
    conn = get_connection()

    if params is None:
        params = ()

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    return df


def show_best_recurring_flips(limit=25):
    query = """
        SELECT
            item_name AS Item,
            window_name AS Window,
            COUNT(*) AS Appearances,
            ROUND(AVG(total_profit), 0) AS Avg_Total_Profit,
            ROUND(MAX(total_profit), 0) AS Best_Total_Profit,
            ROUND(AVG(profit_per_item), 2) AS Avg_Profit_Per_Item,
            ROUND(AVG(roi_percent), 2) AS Avg_ROI_Percent,
            ROUND(AVG(volume), 0) AS Avg_Volume,
            ROUND(AVG(score), 2) AS Avg_Score
        FROM scan_results
        WHERE result_type = 'profitable'
        GROUP BY item_id, item_name, window_name
        HAVING Appearances >= 3
        ORDER BY Avg_Score DESC
        LIMIT ?
    """

    df = run_query(query, (limit,))

    print_section("BEST RECURRING FLIPS")

    if df.empty:
        print("Not enough history yet. Let collector.py run longer.")
        return

    print(df.to_string(index=False))


def show_frequent_margin_spikes(limit=25):
    query = """
        SELECT
            item_name AS Item,
            window_name AS Window,
            COUNT(*) AS Spike_Count,
            ROUND(AVG(total_profit), 0) AS Avg_Total_Profit,
            ROUND(MAX(total_profit), 0) AS Best_Total_Profit,
            ROUND(AVG(margin_delta_percent), 2) AS Avg_Margin_Delta_Percent,
            ROUND(MAX(margin_delta_percent), 2) AS Best_Margin_Delta_Percent,
            ROUND(AVG(volume), 0) AS Avg_Volume
        FROM scan_results
        WHERE result_type = 'profitable'
          AND signal IN ('Strong margin spike', 'Above average')
        GROUP BY item_id, item_name, window_name
        ORDER BY Spike_Count DESC, Avg_Margin_Delta_Percent DESC
        LIMIT ?
    """

    df = run_query(query, (limit,))

    print_section("MOST FREQUENT MARGIN SPIKES")

    if df.empty:
        print("No margin spike history yet. This is normal early on.")
        return

    print(df.to_string(index=False))


def show_stable_high_volume_flips(limit=25):
    query = """
        SELECT
            item_name AS Item,
            window_name AS Window,
            COUNT(*) AS Appearances,
            ROUND(AVG(total_profit), 0) AS Avg_Total_Profit,
            ROUND(AVG(profit_per_item), 2) AS Avg_Profit_Per_Item,
            ROUND(AVG(roi_percent), 2) AS Avg_ROI_Percent,
            ROUND(AVG(volume), 0) AS Avg_Volume,
            ROUND(MIN(volume), 0) AS Min_Volume,
            ROUND(AVG(score), 2) AS Avg_Score
        FROM scan_results
        WHERE result_type = 'profitable'
          AND confidence IN ('Medium', 'High')
        GROUP BY item_id, item_name, window_name
        HAVING Appearances >= 3
        ORDER BY Avg_Volume DESC, Avg_Total_Profit DESC
        LIMIT ?
    """

    df = run_query(query, (limit,))

    print_section("STABLE HIGH-VOLUME FLIPS")

    if df.empty:
        print("Not enough medium/high-confidence profitable history yet.")
        return

    print(df.to_string(index=False))


def show_latest_strong_signals(limit=25):
    query = """
        SELECT
            scanned_at AS Scanned_At,
            item_name AS Item,
            window_name AS Window,
            target_buy AS Target_Buy,
            target_sell AS Target_Sell,
            quantity AS Qty,
            total_profit AS Total_Profit,
            roi_percent AS ROI_Percent,
            volume AS Volume,
            confidence AS Confidence,
            hist_samples AS Hist_Samples,
            avg_raw_margin AS Avg_Margin,
            margin_delta_percent AS Margin_Delta_Percent,
            signal AS Signal
        FROM scan_results
        WHERE result_type = 'profitable'
          AND signal IN ('Strong margin spike', 'Above average')
        ORDER BY scanned_at DESC, score DESC
        LIMIT ?
    """

    df = run_query(query, (limit,))

    print_section("LATEST STRONG SIGNALS")

    if df.empty:
        print("No strong current signals found yet.")
        return

    print(df.to_string(index=False))


def show_item_history(item_name, limit=30):
    query = """
        SELECT
            scanned_at AS Scanned_At,
            item_name AS Item,
            window_name AS Window,
            target_buy AS Target_Buy,
            target_sell AS Target_Sell,
            raw_margin AS Raw_Margin,
            profit_per_item AS Profit_Per_Item,
            total_profit AS Total_Profit,
            roi_percent AS ROI_Percent,
            volume AS Volume,
            confidence AS Confidence,
            signal AS Signal
        FROM scan_results
        WHERE item_name LIKE ?
        ORDER BY scanned_at DESC
        LIMIT ?
    """

    df = run_query(query, (f"%{item_name}%", limit))

    print_section(f"ITEM HISTORY: {item_name}")

    if df.empty:
        print(f"No history found for: {item_name}")
        return

    print(df.to_string(index=False))


def show_database_summary():
    query = """
        SELECT
            COUNT(*) AS Total_Rows,
            COUNT(DISTINCT run_id) AS Total_Scan_Runs,
            COUNT(DISTINCT item_id) AS Unique_Items,
            MIN(scanned_at) AS First_Scan,
            MAX(scanned_at) AS Latest_Scan
        FROM scan_results
    """

    df = run_query(query)

    print_section("DATABASE SUMMARY")

    if df.empty:
        print("No database history found.")
        return

    print(df.to_string(index=False))


def export_report_csv():
    query = """
        SELECT
            item_name AS Item,
            window_name AS Window,
            COUNT(*) AS Appearances,
            ROUND(AVG(total_profit), 0) AS Avg_Total_Profit,
            ROUND(MAX(total_profit), 0) AS Best_Total_Profit,
            ROUND(AVG(profit_per_item), 2) AS Avg_Profit_Per_Item,
            ROUND(AVG(roi_percent), 2) AS Avg_ROI_Percent,
            ROUND(AVG(volume), 0) AS Avg_Volume,
            ROUND(AVG(score), 2) AS Avg_Score
        FROM scan_results
        WHERE result_type = 'profitable'
        GROUP BY item_id, item_name, window_name
        HAVING Appearances >= 3
        ORDER BY Avg_Score DESC
    """

    df = run_query(query)

    if df.empty:
        print("No report data to export yet.")
        return

    filename = "osrs_flip_report.csv"
    df.to_csv(filename, index=False)

    print(f"\nExported report to: {filename}")


def main():
    while True:
        print("\n==============================")
        print(" OSRS Flip History Report")
        print("==============================")
        print("1. Database summary")
        print("2. Best recurring flips")
        print("3. Most frequent margin spikes")
        print("4. Stable high-volume flips")
        print("5. Latest strong signals")
        print("6. Search item history")
        print("7. Export recurring flips report to CSV")
        print("8. Exit")

        choice = input("\nChoose an option: ").strip()

        if choice == "1":
            show_database_summary()

        elif choice == "2":
            show_best_recurring_flips()

        elif choice == "3":
            show_frequent_margin_spikes()

        elif choice == "4":
            show_stable_high_volume_flips()

        elif choice == "5":
            show_latest_strong_signals()

        elif choice == "6":
            item_name = input("Enter item name: ").strip()
            show_item_history(item_name)

        elif choice == "7":
            export_report_csv()

        elif choice == "8":
            print("Exiting report.")
            break

        else:
            print("Invalid option. Try again.")


if __name__ == "__main__":
    main()