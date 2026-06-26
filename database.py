import os
import sqlite3
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "osrs_flip_scanner.db")


def get_connection():
    return sqlite3.connect(DB_FILE)


def add_column_if_missing(cursor, table_name, column_name, column_definition):
    cursor.execute(f"PRAGMA table_info({table_name})")
    existing_columns = [row[1] for row in cursor.fetchall()]

    if column_name not in existing_columns:
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scan_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scanned_at TEXT NOT NULL,
            cash_stack INTEGER NOT NULL,
            minimum_profit INTEGER NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scan_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            scanned_at TEXT NOT NULL,

            item_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            window_name TEXT NOT NULL,
            window_rank INTEGER,

            recommendation_rank INTEGER,
            recommendation_score REAL,
            recommendation TEXT,
            risk_level TEXT,
            why TEXT,
            flip_category TEXT,
            category_reason TEXT,

            price_source TEXT,
            target_buy INTEGER NOT NULL,
            target_sell INTEGER NOT NULL,
            avg_low INTEGER,
            avg_high INTEGER,
            latest_low_time INTEGER,
            latest_high_time INTEGER,
            buy_vs_avg_low_percent REAL,
            sell_vs_avg_high_percent REAL,
            price_warning TEXT,

            quantity INTEGER NOT NULL,
            cost INTEGER NOT NULL,
            tax INTEGER NOT NULL,
            raw_margin INTEGER NOT NULL,
            profit_per_item INTEGER NOT NULL,
            total_profit INTEGER NOT NULL,
            roi_percent REAL NOT NULL,
            raw_roi_percent REAL NOT NULL,

            volume INTEGER NOT NULL,
            hourly_volume INTEGER,
            liquidity_score REAL,
            liquidity_rating TEXT,
            expected_fill_hours REAL,
            expected_fill_time TEXT,
            high_volume INTEGER NOT NULL,
            low_volume INTEGER NOT NULL,

            buy_limit INTEGER NOT NULL,
            confidence TEXT NOT NULL,
            score REAL NOT NULL,
            result_type TEXT NOT NULL,

            hist_samples INTEGER DEFAULT 0,
            avg_raw_margin REAL,
            avg_profit_per_item REAL,
            avg_roi_percent REAL,
            avg_volume REAL,
            margin_delta REAL,
            margin_delta_percent REAL,
            margin_warning TEXT,
            signal TEXT,

            daily_trend TEXT,
            weekly_trend TEXT,
            long_term_trend TEXT,
            daily_change_percent REAL,
            weekly_change_percent REAL,
            long_term_change_percent REAL,
            daily_volatility_percent REAL,
            weekly_volatility_percent REAL,
            seven_day_high INTEGER,
            seven_day_low INTEGER,
            price_position_7d_percent REAL,
            trend_confidence TEXT,
            trend_warning TEXT,
            quick_score REAL,
            overnight_score REAL,

            FOREIGN KEY (run_id) REFERENCES scan_runs(id)
        )
    """)

    # Safe migrations for older database files.
    migrations = [
        ("hist_samples", "INTEGER DEFAULT 0"),
        ("avg_raw_margin", "REAL"),
        ("avg_profit_per_item", "REAL"),
        ("avg_roi_percent", "REAL"),
        ("avg_volume", "REAL"),
        ("margin_delta", "REAL"),
        ("margin_delta_percent", "REAL"),
        ("signal", "TEXT"),

        ("price_source", "TEXT"),
        ("avg_low", "INTEGER"),
        ("avg_high", "INTEGER"),
        ("latest_low_time", "INTEGER"),
        ("latest_high_time", "INTEGER"),

        ("window_rank", "INTEGER"),
        ("recommendation_rank", "INTEGER"),
        ("recommendation_score", "REAL"),
        ("recommendation", "TEXT"),
        ("risk_level", "TEXT"),
        ("why", "TEXT"),
        ("flip_category", "TEXT"),
        ("category_reason", "TEXT"),

        ("hourly_volume", "INTEGER"),
        ("liquidity_score", "REAL"),
        ("liquidity_rating", "TEXT"),
        ("expected_fill_hours", "REAL"),
        ("expected_fill_time", "TEXT"),

        ("buy_vs_avg_low_percent", "REAL"),
        ("sell_vs_avg_high_percent", "REAL"),
        ("price_warning", "TEXT"),
        ("margin_warning", "TEXT"),

        # Daily / weekly trend fields
        ("daily_trend", "TEXT"),
        ("weekly_trend", "TEXT"),
        ("long_term_trend", "TEXT"),
        ("daily_change_percent", "REAL"),
        ("weekly_change_percent", "REAL"),
        ("long_term_change_percent", "REAL"),
        ("daily_volatility_percent", "REAL"),
        ("weekly_volatility_percent", "REAL"),
        ("seven_day_high", "INTEGER"),
        ("seven_day_low", "INTEGER"),
        ("price_position_7d_percent", "REAL"),
        ("trend_confidence", "TEXT"),
        ("trend_warning", "TEXT"),
        ("quick_score", "REAL"),
        ("overnight_score", "REAL")
    ]

    for column_name, column_definition in migrations:
        add_column_if_missing(
            cursor,
            "scan_results",
            column_name,
            column_definition
        )

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_results_item
        ON scan_results(item_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_results_window
        ON scan_results(window_name)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_results_scanned_at
        ON scan_results(scanned_at)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_results_item_window
        ON scan_results(item_id, window_name)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_results_run
        ON scan_results(run_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_results_signal
        ON scan_results(signal)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_results_flip_category
        ON scan_results(flip_category)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_results_quick_score
        ON scan_results(quick_score)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_results_overnight_score
        ON scan_results(overnight_score)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_results_trend_warning
        ON scan_results(trend_warning)
    """)

    conn.commit()
    conn.close()


def create_scan_run(cash_stack, minimum_profit):
    conn = get_connection()
    cursor = conn.cursor()

    scanned_at = datetime.now(timezone.utc).isoformat()

    cursor.execute("""
        INSERT INTO scan_runs (
            scanned_at,
            cash_stack,
            minimum_profit
        )
        VALUES (?, ?, ?)
    """, (
        scanned_at,
        cash_stack,
        minimum_profit
    ))

    run_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return run_id, scanned_at


def get_historical_stats(item_id, window_name):
    """
    Gets historical stats for one item and one window.

    Example:
    item_id = Dragon bones ID
    window_name = 5m or 1h
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(*) AS samples,
            AVG(raw_margin) AS avg_raw_margin,
            AVG(profit_per_item) AS avg_profit_per_item,
            AVG(roi_percent) AS avg_roi_percent,
            AVG(volume) AS avg_volume
        FROM scan_results
        WHERE item_id = ?
          AND window_name = ?
          AND result_type IN ('profitable', 'watchlist')
    """, (
        item_id,
        window_name
    ))

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return {
            "samples": 0,
            "avg_raw_margin": None,
            "avg_profit_per_item": None,
            "avg_roi_percent": None,
            "avg_volume": None
        }

    return {
        "samples": row[0] or 0,
        "avg_raw_margin": row[1],
        "avg_profit_per_item": row[2],
        "avg_roi_percent": row[3],
        "avg_volume": row[4]
    }


def classify_signal(row, stats, min_samples=3):
    """
    Creates a human-readable signal based on current margin
    compared to historical average margin.
    """
    samples = stats["samples"]
    avg_margin = stats["avg_raw_margin"]
    avg_volume = stats["avg_volume"]

    current_margin = row["Raw Margin"]
    current_profit_per_item = row["Profit/Item"]
    current_volume = row["Volume"]

    if samples < min_samples or avg_margin is None:
        return "New / Not enough history", None, None

    margin_delta = current_margin - avg_margin

    if avg_margin == 0:
        margin_delta_percent = None
    else:
        margin_delta_percent = (margin_delta / avg_margin) * 100

    if current_profit_per_item <= 0:
        return "Watch only", margin_delta, margin_delta_percent

    if margin_delta_percent is None:
        return "Normal", margin_delta, margin_delta_percent

    volume_ok = True

    if avg_volume is not None and avg_volume > 0:
        volume_ok = current_volume >= avg_volume * 0.50

    if margin_delta_percent >= 75 and volume_ok:
        return "Strong margin spike", margin_delta, margin_delta_percent

    if margin_delta_percent >= 35 and volume_ok:
        return "Above average", margin_delta, margin_delta_percent

    if margin_delta_percent <= -25:
        return "Below average", margin_delta, margin_delta_percent

    return "Normal", margin_delta, margin_delta_percent


def get_margin_warning(margin_delta_percent):
    if margin_delta_percent is None:
        return "OK"

    if margin_delta_percent >= 125:
        return "Margin far above historical average; verify with small test buy/sell."

    if margin_delta_percent >= 75:
        return "Large margin spike; confirm before committing full quantity."

    return "OK"


def enrich_rows_with_history(rows, min_samples=3):
    """
    Adds historical comparison fields to scanner rows.

    This should be called after scanning but before saving the current run,
    so the comparison is based only on previous runs.
    """
    for row in rows:
        stats = get_historical_stats(
            item_id=row["Item ID"],
            window_name=row["Window"]
        )

        signal, margin_delta, margin_delta_percent = classify_signal(
            row=row,
            stats=stats,
            min_samples=min_samples
        )

        row["Hist Samples"] = stats["samples"]

        row["Avg Margin"] = (
            round(stats["avg_raw_margin"], 2)
            if stats["avg_raw_margin"] is not None
            else None
        )

        row["Avg Profit/Item"] = (
            round(stats["avg_profit_per_item"], 2)
            if stats["avg_profit_per_item"] is not None
            else None
        )

        row["Avg ROI %"] = (
            round(stats["avg_roi_percent"], 2)
            if stats["avg_roi_percent"] is not None
            else None
        )

        row["Avg Volume"] = (
            round(stats["avg_volume"], 2)
            if stats["avg_volume"] is not None
            else None
        )

        row["Margin Delta"] = (
            round(margin_delta, 2)
            if margin_delta is not None
            else None
        )

        row["Margin Delta %"] = (
            round(margin_delta_percent, 2)
            if margin_delta_percent is not None
            else None
        )

        row["Margin Warning"] = get_margin_warning(margin_delta_percent)
        row["Signal"] = signal

    return rows


def save_scan_rows(run_id, scanned_at, rows, result_type):
    if not rows:
        return 0

    conn = get_connection()
    cursor = conn.cursor()

    insert_columns = [
        "run_id",
        "scanned_at",

        "item_id",
        "item_name",
        "window_name",
        "window_rank",

        "recommendation_rank",
        "recommendation_score",
        "recommendation",
        "risk_level",
        "why",
        "flip_category",
        "category_reason",

        "price_source",
        "avg_low",
        "avg_high",
        "latest_low_time",
        "latest_high_time",
        "buy_vs_avg_low_percent",
        "sell_vs_avg_high_percent",
        "price_warning",

        "target_buy",
        "target_sell",
        "quantity",
        "cost",
        "tax",
        "raw_margin",
        "profit_per_item",
        "total_profit",
        "roi_percent",
        "raw_roi_percent",

        "volume",
        "hourly_volume",
        "liquidity_score",
        "liquidity_rating",
        "expected_fill_hours",
        "expected_fill_time",
        "high_volume",
        "low_volume",

        "buy_limit",
        "confidence",
        "score",
        "result_type",

        "hist_samples",
        "avg_raw_margin",
        "avg_profit_per_item",
        "avg_roi_percent",
        "avg_volume",
        "margin_delta",
        "margin_delta_percent",
        "margin_warning",
        "signal",

        "daily_trend",
        "weekly_trend",
        "long_term_trend",
        "daily_change_percent",
        "weekly_change_percent",
        "long_term_change_percent",
        "daily_volatility_percent",
        "weekly_volatility_percent",
        "seven_day_high",
        "seven_day_low",
        "price_position_7d_percent",
        "trend_confidence",
        "trend_warning",
        "quick_score",
        "overnight_score"
    ]

    records = []

    for row in rows:
        record = (
            run_id,
            scanned_at,

            row["Item ID"],
            row["Item"],
            row["Window"],
            row.get("Window Rank"),

            row.get("Recommendation Rank"),
            row.get("Recommendation Score"),
            row.get("Recommendation"),
            row.get("Risk Level"),
            row.get("Why"),
            row.get("Flip Category"),
            row.get("Category Reason"),

            row.get("Price Source"),
            row.get("Avg Low"),
            row.get("Avg High"),
            row.get("Latest Low Time"),
            row.get("Latest High Time"),
            row.get("Buy vs Avg Low %"),
            row.get("Sell vs Avg High %"),
            row.get("Price Warning"),

            row["Target Buy"],
            row["Target Sell"],
            row["Qty"],
            row["Cost"],
            row["Tax"],
            row["Raw Margin"],
            row["Profit/Item"],
            row["Total Profit"],
            row["ROI %"],
            row["Raw ROI %"],

            row["Volume"],
            row.get("Hourly Volume"),
            row.get("Liquidity Score"),
            row.get("Liquidity Rating"),
            row.get("Expected Fill Hours"),
            row.get("Expected Fill Time"),
            row["High Volume"],
            row["Low Volume"],

            row["Buy Limit"],
            row["Confidence"],
            row["Score"],
            result_type,

            row.get("Hist Samples", 0),
            row.get("Avg Margin"),
            row.get("Avg Profit/Item"),
            row.get("Avg ROI %"),
            row.get("Avg Volume"),
            row.get("Margin Delta"),
            row.get("Margin Delta %"),
            row.get("Margin Warning"),
            row.get("Signal"),

            row.get("Daily Trend"),
            row.get("Weekly Trend"),
            row.get("Long Term Trend"),
            row.get("Daily Change %"),
            row.get("Weekly Change %"),
            row.get("Long Term Change %"),
            row.get("Daily Volatility %"),
            row.get("Weekly Volatility %"),
            row.get("7D High"),
            row.get("7D Low"),
            row.get("Price Position 7D %"),
            row.get("Trend Confidence"),
            row.get("Trend Warning"),
            row.get("Quick Score"),
            row.get("Overnight Score")
        )

        if len(record) != len(insert_columns):
            raise ValueError(
                f"Column/value mismatch: {len(insert_columns)} columns, "
                f"{len(record)} values."
            )

        records.append(record)

    placeholders = ", ".join(["?"] * len(insert_columns))
    column_names = ", ".join(insert_columns)

    cursor.executemany(
        f"""
        INSERT INTO scan_results (
            {column_names}
        )
        VALUES (
            {placeholders}
        )
        """,
        records
    )

    conn.commit()
    conn.close()

    return len(records)


def get_recent_profitable(limit=20):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
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
        FROM scan_results
        WHERE result_type = 'profitable'
        ORDER BY scanned_at DESC, score DESC
        LIMIT ?
    """, (
        limit,
    ))

    rows = cursor.fetchall()
    conn.close()

    return rows
