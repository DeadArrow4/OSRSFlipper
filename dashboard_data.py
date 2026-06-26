"""
Data, database, status, export, and maintenance helpers for the OSRSFlipper dashboard.
"""
import os
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from account_context import get_account_scope
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
    """
    Run the health check against the real C:\OSRSFlipper project folder.

    This intentionally loads C:\OSRSFlipper\health_check.py by exact file path
    instead of using a normal `import health_check`, because a test install or
    an already-running dashboard process can otherwise reuse the wrong module.
    """
    import importlib.util

    health_check_path = Path(r"C:\OSRSFlipper\health_check.py")

    if not health_check_path.exists():
        return (
            f"Health check failed: expected file not found: {health_check_path}",
            str(health_check_path)
        )

    spec = importlib.util.spec_from_file_location(
        "osrsflipper_real_health_check",
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
