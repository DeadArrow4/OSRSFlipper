from __future__ import annotations

import math
import os
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DB_CANDIDATES = [
    "osrs_flip_scanner.db",
    "osrs_flips.db",
    "flips.db",
    "osrsflipper.db",
    "osrs_flipper.db",
    "data/osrs_flip_scanner.db",
    "data/osrs_flips.db",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _connect() -> tuple[sqlite3.Connection, Path]:
    env_path = os.environ.get("OSRSFLIPPER_DB") or os.environ.get("OSRS_DB_PATH")
    candidates: list[Path] = []

    if env_path:
        candidates.append(Path(env_path))

    for name in DB_CANDIDATES:
        candidates.append(BASE_DIR / name)

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            conn = sqlite3.connect(candidate)
            conn.row_factory = sqlite3.Row
            return conn, candidate

    db_files = sorted(
        [p for p in BASE_DIR.rglob("*.db") if "backup" not in str(p).lower()],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )

    if db_files:
        conn = sqlite3.connect(db_files[0])
        conn.row_factory = sqlite3.Row
        return conn, db_files[0]

    raise FileNotFoundError("Could not find an OSRSFlipper SQLite database.")


def _fetchone(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = _fetchone(conn, sql, params)
    if row is None:
        return None
    return row[0]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        _scalar(
            conn,
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        )
    )


def _table_names(conn: sqlite3.Connection) -> list[str]:
    return [
        row["name"]
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    ]


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if not _table_exists(conn, table):
        return []

    return [
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({_safe_identifier(table)})").fetchall()
    ]


def _column_map(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    return {name.lower(): name for name in _columns(conn, table)}


def _index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    return bool(
        _scalar(
            conn,
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=? LIMIT 1",
            (index_name,),
        )
    )


def _existing_index_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if not _table_exists(conn, table):
        return []

    out = []
    for index_row in conn.execute(f"PRAGMA index_list({_safe_identifier(table)})").fetchall():
        index_name = index_row["name"]
        cols = [
            col["name"]
            for col in conn.execute(f"PRAGMA index_info({_safe_identifier(index_name)})").fetchall()
        ]
        out.append(", ".join(cols))
    return out


def _create_index_if_columns(
    conn: sqlite3.Connection,
    index_name: str,
    table: str,
    columns: list[str],
) -> dict[str, Any]:
    table_columns = set(_columns(conn, table))

    row = {
        "index": index_name,
        "table": table,
        "columns": ", ".join(columns),
        "status": "",
    }

    if not _table_exists(conn, table):
        row["status"] = "skipped: table missing"
        return row

    missing = [column for column in columns if column not in table_columns]

    if missing:
        row["status"] = f"skipped: missing {', '.join(missing)}"
        return row

    sql_columns = ", ".join(_safe_identifier(column) for column in columns)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS {_safe_identifier(index_name)} "
        f"ON {_safe_identifier(table)} ({sql_columns})"
    )
    row["status"] = "created or already existed"
    return row


def _recommended_index_specs(conn: sqlite3.Connection) -> list[tuple[str, str, list[str]]]:
    specs: list[tuple[str, str, list[str]]] = [
        ("idx_scan_results_run_id", "scan_results", ["run_id"]),
        ("idx_scan_results_scanned_at", "scan_results", ["scanned_at"]),
        ("idx_daily_item_metrics_item_date", "daily_item_metrics", ["item_name", "metric_date"]),
        ("idx_daily_item_metrics_date_score", "daily_item_metrics", ["metric_date", "avg_recommendation_score"]),
    ]

    scan_cols = set(_columns(conn, "scan_results"))

    if {"item_id", "item_name", "scanned_at"}.issubset(scan_cols):
        specs.append(("idx_scan_results_item_time", "scan_results", ["item_id", "item_name", "scanned_at"]))
    elif {"item_name", "scanned_at"}.issubset(scan_cols):
        specs.append(("idx_scan_results_item_time", "scan_results", ["item_name", "scanned_at"]))

    if {"item_id", "window_name", "scanned_at"}.issubset(scan_cols):
        specs.append(("idx_scan_results_item_window_time", "scan_results", ["item_id", "window_name", "scanned_at"]))
    elif {"item_name", "window_name", "scanned_at"}.issubset(scan_cols):
        specs.append(("idx_scan_results_item_window_time", "scan_results", ["item_name", "window_name", "scanned_at"]))

    completed_cols = set(_columns(conn, "completed_trades"))
    if {"app_username", "osrs_account_name", "sell_time"}.issubset(completed_cols):
        specs.append(("idx_completed_trades_account_sell_time", "completed_trades", ["app_username", "osrs_account_name", "sell_time"]))
    elif "sell_time" in completed_cols:
        specs.append(("idx_completed_trades_sell_time", "completed_trades", ["sell_time"]))

    trade_event_cols = set(_columns(conn, "trade_events"))
    if {"app_username", "osrs_account_name", "remaining_quantity", "traded_at"}.issubset(trade_event_cols):
        specs.append(("idx_trade_events_account_open", "trade_events", ["app_username", "osrs_account_name", "remaining_quantity", "traded_at"]))
    elif "traded_at" in trade_event_cols:
        specs.append(("idx_trade_events_traded_at", "trade_events", ["traded_at"]))

    return specs


def ensure_data_health_schema() -> dict[str, Any]:
    conn, db_path = _connect()

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_item_metrics (
                metric_date TEXT NOT NULL,
                item_id TEXT NOT NULL DEFAULT '',
                item_name TEXT NOT NULL,
                window_name TEXT NOT NULL DEFAULT 'default',
                scan_count INTEGER NOT NULL DEFAULT 0,
                profitable_count INTEGER NOT NULL DEFAULT 0,
                avg_margin REAL,
                avg_total_profit REAL,
                avg_profit_per_item REAL,
                avg_roi REAL,
                avg_volume REAL,
                avg_quick_score REAL,
                avg_overnight_score REAL,
                avg_recommendation_score REAL,
                min_margin REAL,
                max_margin REAL,
                margin_volatility REAL,
                first_seen_at TEXT,
                last_seen_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (metric_date, item_id, item_name, window_name)
            )
            """
        )

        index_results = []

        for index_name, table, columns in _recommended_index_specs(conn):
            index_results.append(_create_index_if_columns(conn, index_name, table, columns))

        conn.commit()

        return {
            "ok": True,
            "database_path": str(db_path),
            "status": f"Data health schema/index check complete. {len(index_results)} index checks ran.",
            "index_results": index_results,
        }
    finally:
        conn.close()


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None

    text = str(value).strip()
    if not text:
        return None

    if text.replace(".", "", 1).isdigit():
        try:
            number = float(text)
            # Old School RuneScape GE timestamps in this project appear as epoch seconds.
            if number > 1000000000:
                return datetime.fromtimestamp(number, tz=timezone.utc)
        except Exception:
            pass

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        pass

    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _metric_date(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    if parsed:
        return parsed.date().isoformat()

    text = str(value or "").strip()
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]

    return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None

    try:
        result = float(str(value).replace(",", "").strip())
    except Exception:
        return None

    if math.isnan(result) or math.isinf(result):
        return None

    return result


def _first_col(cmap: dict[str, str], names: list[str]) -> str | None:
    for name in names:
        if name.lower() in cmap:
            return cmap[name.lower()]

    for lower_name, real_name in cmap.items():
        for name in names:
            if name.lower() in lower_name:
                return real_name

    return None


def _avg(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None]

    if not clean:
        return None

    return sum(clean) / len(clean)


def _stddev(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None]

    if len(clean) < 2:
        return 0.0 if len(clean) == 1 else None

    return statistics.pstdev(clean)


def rebuild_daily_item_metrics(days: int | None = 120) -> dict[str, Any]:
    schema_result = ensure_data_health_schema()
    conn, db_path = _connect()

    try:
        if not _table_exists(conn, "scan_results"):
            return {
                "ok": False,
                "status": "scan_results table was not found.",
                "database_path": str(db_path),
                "schema_result": schema_result,
            }

        cmap = _column_map(conn, "scan_results")

        scanned_col = _first_col(cmap, ["scanned_at", "created_at", "timestamp", "run_at"])
        item_name_col = _first_col(cmap, ["item_name", "name", "item"])
        item_id_col = _first_col(cmap, ["item_id"])
        window_col = _first_col(cmap, ["window_name", "time_window", "flip_window", "strategy_window"])

        margin_col = _first_col(cmap, ["margin", "raw_margin", "profit_per_item", "expected_margin"])
        total_profit_col = _first_col(cmap, ["total_profit", "expected_total_profit", "profit"])
        profit_per_item_col = _first_col(cmap, ["profit_per_item", "margin"])
        roi_col = _first_col(cmap, ["roi", "roi_percent", "return_percent"])
        volume_col = _first_col(cmap, ["volume", "daily_volume", "high_volume", "low_volume"])
        quick_score_col = _first_col(cmap, ["quick_score", "quick_flip_score"])
        overnight_score_col = _first_col(cmap, ["overnight_score"])
        recommendation_score_col = _first_col(cmap, ["recommendation_score", "trade_score", "score"])

        if not scanned_col or not item_name_col:
            return {
                "ok": False,
                "status": "scan_results needs scanned_at and item_name/name columns before daily metrics can be built.",
                "database_path": str(db_path),
                "schema_result": schema_result,
            }

        where_clause = f"WHERE {_safe_identifier(scanned_col)} IS NOT NULL"
        params: list[Any] = []

        cutoff_date = None

        if days:
            days_int = max(1, min(int(days), 3650))
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days_int)
            cutoff_date = cutoff_dt.date().isoformat()
            where_clause += f" AND substr(CAST({_safe_identifier(scanned_col)} AS TEXT), 1, 10) >= ?"
            params.append(cutoff_date)

        query = f"SELECT * FROM {_safe_identifier('scan_results')} {where_clause}"

        groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}

        rows_seen = 0
        rows_used = 0

        for row in conn.execute(query, tuple(params)):
            rows_seen += 1
            scanned_at = row[scanned_col]
            metric_date = _metric_date(scanned_at)

            if not metric_date:
                continue

            item_name = str(row[item_name_col] or "").strip()

            if not item_name:
                continue

            item_id = str(row[item_id_col] or "").strip() if item_id_col else ""
            window_name = str(row[window_col] or "default").strip() if window_col else "default"
            window_name = window_name or "default"

            key = (metric_date, item_id, item_name, window_name)

            if key not in groups:
                groups[key] = {
                    "scan_count": 0,
                    "profitable_count": 0,
                    "margins": [],
                    "total_profits": [],
                    "profit_per_item": [],
                    "rois": [],
                    "volumes": [],
                    "quick_scores": [],
                    "overnight_scores": [],
                    "recommendation_scores": [],
                    "first_seen_at": str(scanned_at),
                    "last_seen_at": str(scanned_at),
                }

            group = groups[key]
            group["scan_count"] += 1
            rows_used += 1

            margin = _safe_float(row[margin_col]) if margin_col else None
            total_profit = _safe_float(row[total_profit_col]) if total_profit_col else None
            profit_per_item = _safe_float(row[profit_per_item_col]) if profit_per_item_col else margin
            roi = _safe_float(row[roi_col]) if roi_col else None
            volume = _safe_float(row[volume_col]) if volume_col else None
            quick_score = _safe_float(row[quick_score_col]) if quick_score_col else None
            overnight_score = _safe_float(row[overnight_score_col]) if overnight_score_col else None
            recommendation_score = _safe_float(row[recommendation_score_col]) if recommendation_score_col else None

            if margin is not None:
                group["margins"].append(margin)

            if total_profit is not None:
                group["total_profits"].append(total_profit)

            if profit_per_item is not None:
                group["profit_per_item"].append(profit_per_item)

            if roi is not None:
                group["rois"].append(roi)

            if volume is not None:
                group["volumes"].append(volume)

            if quick_score is not None:
                group["quick_scores"].append(quick_score)

            if overnight_score is not None:
                group["overnight_scores"].append(overnight_score)

            if recommendation_score is not None:
                group["recommendation_scores"].append(recommendation_score)

            if (margin is not None and margin > 0) or (total_profit is not None and total_profit > 0):
                group["profitable_count"] += 1

            scanned_text = str(scanned_at)
            if scanned_text < str(group["first_seen_at"]):
                group["first_seen_at"] = scanned_text
            if scanned_text > str(group["last_seen_at"]):
                group["last_seen_at"] = scanned_text

        if cutoff_date:
            conn.execute("DELETE FROM daily_item_metrics WHERE metric_date >= ?", (cutoff_date,))
        else:
            conn.execute("DELETE FROM daily_item_metrics")

        now = _utc_now()

        insert_sql = """
        INSERT OR REPLACE INTO daily_item_metrics (
            metric_date,
            item_id,
            item_name,
            window_name,
            scan_count,
            profitable_count,
            avg_margin,
            avg_total_profit,
            avg_profit_per_item,
            avg_roi,
            avg_volume,
            avg_quick_score,
            avg_overnight_score,
            avg_recommendation_score,
            min_margin,
            max_margin,
            margin_volatility,
            first_seen_at,
            last_seen_at,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        for (metric_date, item_id, item_name, window_name), group in groups.items():
            margins = group["margins"]

            conn.execute(
                insert_sql,
                (
                    metric_date,
                    item_id,
                    item_name,
                    window_name,
                    int(group["scan_count"]),
                    int(group["profitable_count"]),
                    _avg(group["margins"]),
                    _avg(group["total_profits"]),
                    _avg(group["profit_per_item"]),
                    _avg(group["rois"]),
                    _avg(group["volumes"]),
                    _avg(group["quick_scores"]),
                    _avg(group["overnight_scores"]),
                    _avg(group["recommendation_scores"]),
                    min(margins) if margins else None,
                    max(margins) if margins else None,
                    _stddev(margins),
                    group["first_seen_at"],
                    group["last_seen_at"],
                    now,
                    now,
                ),
            )

        conn.commit()

        return {
            "ok": True,
            "database_path": str(db_path),
            "status": (
                f"Daily item metrics rebuilt. Read {rows_seen:,} scan rows, "
                f"used {rows_used:,}, wrote {len(groups):,} daily metric rows."
            ),
            "rows_seen": rows_seen,
            "rows_used": rows_used,
            "metric_rows_written": len(groups),
            "days": days,
            "cutoff_date": cutoff_date,
            "schema_result": schema_result,
        }
    finally:
        conn.close()


def _table_count_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    out = []

    for table in _table_names(conn):
        try:
            count = _scalar(conn, f"SELECT COUNT(*) FROM {_safe_identifier(table)}")
        except Exception as exc:
            count = f"error: {exc}"

        out.append({"Table": table, "Rows": count})

    out.sort(key=lambda row: int(row["Rows"]) if isinstance(row["Rows"], int) else -1, reverse=True)
    return out


def _time_coverage_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    candidates = [
        ("scan_results", "scanned_at"),
        ("scan_runs", "scanned_at"),
        ("completed_trades", "buy_time"),
        ("completed_trades", "sell_time"),
        ("trade_events", "traded_at"),
        ("daily_item_metrics", "metric_date"),
    ]

    out = []

    for table, column in candidates:
        if not _table_exists(conn, table) or column not in _columns(conn, table):
            out.append(
                {
                    "Table": table,
                    "Time Column": column,
                    "Rows": 0,
                    "Days": 0,
                    "Oldest": "",
                    "Newest": "",
                    "Status": "missing",
                }
            )
            continue

        try:
            table_sql = _safe_identifier(table)
            col_sql = _safe_identifier(column)

            row = _fetchone(
                conn,
                f"""
                SELECT
                    COUNT({col_sql}) AS rows_with_value,
                    COUNT(DISTINCT substr(CAST({col_sql} AS TEXT), 1, 10)) AS distinct_days,
                    MIN({col_sql}) AS oldest_value,
                    MAX({col_sql}) AS newest_value
                FROM {table_sql}
                WHERE {col_sql} IS NOT NULL
                  AND TRIM(CAST({col_sql} AS TEXT)) <> ''
                """,
            )

            days = row["distinct_days"] if row else 0

            out.append(
                {
                    "Table": table,
                    "Time Column": column,
                    "Rows": row["rows_with_value"] if row else 0,
                    "Days": days,
                    "Oldest": row["oldest_value"] if row else "",
                    "Newest": row["newest_value"] if row else "",
                    "Status": "ok" if days else "no data",
                }
            )
        except Exception as exc:
            out.append(
                {
                    "Table": table,
                    "Time Column": column,
                    "Rows": 0,
                    "Days": 0,
                    "Oldest": "",
                    "Newest": "",
                    "Status": f"error: {type(exc).__name__}",
                }
            )

    return out


def _index_status_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    out = []

    for index_name, table, columns in _recommended_index_specs(conn):
        table_cols = set(_columns(conn, table))
        missing = [column for column in columns if column not in table_cols]

        if not _table_exists(conn, table):
            status = "table missing"
        elif missing:
            status = f"missing columns: {', '.join(missing)}"
        elif _index_exists(conn, index_name):
            status = "exists"
        else:
            status = "missing"

        out.append(
            {
                "Index": index_name,
                "Table": table,
                "Columns": ", ".join(columns),
                "Status": status,
            }
        )

    return out


def _daily_metric_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "daily_item_metrics"):
        return [
            {
                "Metric": "daily_item_metrics",
                "Value": "missing",
                "Notes": "Click Apply Data Schema / Indexes.",
            }
        ]

    row = _fetchone(
        conn,
        """
        SELECT
            COUNT(*) AS metric_rows,
            COUNT(DISTINCT metric_date) AS metric_days,
            MIN(metric_date) AS oldest_date,
            MAX(metric_date) AS newest_date,
            COUNT(DISTINCT item_name) AS item_count
        FROM daily_item_metrics
        """
    )

    top_rows = conn.execute(
        """
        SELECT
            item_name,
            COUNT(*) AS days_seen,
            ROUND(AVG(avg_margin), 2) AS avg_margin,
            ROUND(AVG(avg_recommendation_score), 2) AS avg_score,
            ROUND(AVG(margin_volatility), 2) AS avg_margin_volatility
        FROM daily_item_metrics
        GROUP BY item_name
        ORDER BY avg_score DESC, days_seen DESC
        LIMIT 10
        """
    ).fetchall()

    out = [
        {
            "Metric": "Rows",
            "Value": row["metric_rows"] if row else 0,
            "Notes": "Daily item/window aggregate rows.",
        },
        {
            "Metric": "Days",
            "Value": row["metric_days"] if row else 0,
            "Notes": f"{row['oldest_date'] if row else ''} -> {row['newest_date'] if row else ''}",
        },
        {
            "Metric": "Items",
            "Value": row["item_count"] if row else 0,
            "Notes": "Distinct item names in daily metrics.",
        },
    ]

    for top in top_rows:
        out.append(
            {
                "Metric": top["item_name"],
                "Value": top["days_seen"],
                "Notes": (
                    f"avg margin={top['avg_margin']}, "
                    f"avg score={top['avg_score']}, "
                    f"margin volatility={top['avg_margin_volatility']}"
                ),
            }
        )

    return out


def _growth_summary(conn: sqlite3.Connection, db_path: Path) -> dict[str, Any]:
    size_mb = round(db_path.stat().st_size / 1024 / 1024, 2) if db_path.exists() else 0.0

    scan_rows = 0
    scan_days = 0
    scan_runs = 0
    avg_rows_per_run = 0

    if _table_exists(conn, "scan_results"):
        scan_rows = int(_scalar(conn, "SELECT COUNT(*) FROM scan_results") or 0)

        if "scanned_at" in _columns(conn, "scan_results"):
            scan_days = int(
                _scalar(
                    conn,
                    """
                    SELECT COUNT(DISTINCT substr(CAST(scanned_at AS TEXT), 1, 10))
                    FROM scan_results
                    WHERE scanned_at IS NOT NULL
                      AND TRIM(CAST(scanned_at AS TEXT)) <> ''
                    """
                )
                or 0
            )

    if _table_exists(conn, "scan_runs"):
        scan_runs = int(_scalar(conn, "SELECT COUNT(*) FROM scan_runs") or 0)

    recent_run_counts = []
    if _table_exists(conn, "scan_results") and "run_id" in _columns(conn, "scan_results"):
        recent_run_counts = [
            int(row["row_count"])
            for row in conn.execute(
                """
                SELECT run_id, COUNT(*) AS row_count
                FROM scan_results
                GROUP BY run_id
                ORDER BY CAST(run_id AS INTEGER) DESC
                LIMIT 50
                """
            ).fetchall()
        ]

    if recent_run_counts:
        avg_rows_per_run = round(sum(recent_run_counts) / len(recent_run_counts), 1)

    rows_per_day = round(scan_rows / scan_days, 1) if scan_days else 0
    estimated_mb_per_day = round(size_mb / scan_days, 2) if scan_days else 0
    estimated_mb_per_month = round(estimated_mb_per_day * 30, 2) if scan_days else 0

    return {
        "database_size_mb": size_mb,
        "scan_rows": scan_rows,
        "scan_days": scan_days,
        "scan_runs": scan_runs,
        "avg_rows_per_run": avg_rows_per_run,
        "rows_per_day": rows_per_day,
        "estimated_mb_per_day": estimated_mb_per_day,
        "estimated_mb_per_month": estimated_mb_per_month,
    }


def build_data_health_snapshot() -> dict[str, Any]:
    conn, db_path = _connect()

    try:
        growth = _growth_summary(conn, db_path)
        tables = _table_count_rows(conn)
        time_coverage = _time_coverage_rows(conn)
        index_status = _index_status_rows(conn)
        daily_metrics = _daily_metric_rows(conn)

        missing_indexes = sum(1 for row in index_status if row["Status"] == "missing")
        daily_metric_rows = 0

        if _table_exists(conn, "daily_item_metrics"):
            daily_metric_rows = int(_scalar(conn, "SELECT COUNT(*) FROM daily_item_metrics") or 0)

        status = (
            f"Data Health loaded. DB={growth['database_size_mb']} MB, "
            f"scan_results={growth['scan_rows']:,} rows across {growth['scan_days']} scan day(s), "
            f"daily metrics={daily_metric_rows:,} rows, missing indexes={missing_indexes}."
        )

        cards = [
            {"Title": "Database", "Value": f"{growth['database_size_mb']} MB", "Detail": str(db_path.name)},
            {"Title": "Scan Rows", "Value": f"{growth['scan_rows']:,}", "Detail": f"{growth['scan_days']} scan day(s)"},
            {"Title": "Scan Runs", "Value": f"{growth['scan_runs']:,}", "Detail": f"avg {growth['avg_rows_per_run']} rows/run"},
            {"Title": "Rows / Day", "Value": f"{growth['rows_per_day']:,}", "Detail": "raw scan_results growth"},
            {"Title": "Est. DB / Month", "Value": f"{growth['estimated_mb_per_month']} MB", "Detail": "rough current pace"},
            {"Title": "Daily Metrics", "Value": f"{daily_metric_rows:,}", "Detail": "aggregate rows"},
            {"Title": "Missing Indexes", "Value": str(missing_indexes), "Detail": "recommended index status"},
        ]

        return {
            "ok": True,
            "status": status,
            "database_path": str(db_path),
            "cards": cards,
            "tables": tables,
            "time_coverage": time_coverage,
            "index_status": index_status,
            "daily_metrics": daily_metrics,
            "growth": growth,
        }
    finally:
        conn.close()

def _trend_value(current_value: float | None, previous_value: float | None) -> tuple[float | None, str]:
    if current_value is None or previous_value is None:
        return None, "not enough data"

    delta = current_value - previous_value

    if abs(delta) < 0.01:
        return delta, "flat"

    return delta, "up" if delta > 0 else "down"


def build_data_trend_snapshot(limit: int = 25) -> dict[str, Any]:
    conn, db_path = _connect()

    try:
        if not _table_exists(conn, "daily_item_metrics"):
            return {
                "ok": False,
                "status": "daily_item_metrics is missing. Click Apply Data Schema / Indexes, then Rebuild Daily Item Metrics.",
                "readiness": [
                    {
                        "Signal": "Daily metrics",
                        "Available": "missing",
                        "Target": "created table",
                        "Status": "not ready",
                        "Notes": "daily_item_metrics table has not been created yet.",
                    }
                ],
                "top_trends": [],
            }

        total_rows = int(_scalar(conn, "SELECT COUNT(*) FROM daily_item_metrics") or 0)
        distinct_days = int(_scalar(conn, "SELECT COUNT(DISTINCT metric_date) FROM daily_item_metrics") or 0)
        distinct_items = int(_scalar(conn, "SELECT COUNT(DISTINCT item_name) FROM daily_item_metrics") or 0)
        newest_date = _scalar(conn, "SELECT MAX(metric_date) FROM daily_item_metrics")
        oldest_date = _scalar(conn, "SELECT MIN(metric_date) FROM daily_item_metrics")

        readiness = []

        def add_readiness(signal: str, available: Any, target: Any, status: str, notes: str) -> None:
            readiness.append(
                {
                    "Signal": signal,
                    "Available": available,
                    "Target": target,
                    "Status": status,
                    "Notes": notes,
                }
            )

        add_readiness(
            "Daily aggregate rows",
            f"{total_rows:,}",
            "> 0",
            "ready" if total_rows > 0 else "not ready",
            "Rows in daily_item_metrics.",
        )
        add_readiness(
            "Distinct metric days",
            distinct_days,
            "7+",
            "ready" if distinct_days >= 7 else "building",
            f"{oldest_date or ''} -> {newest_date or ''}. Short-term trend scoring improves at 7+ days.",
        )
        add_readiness(
            "30-day trend window",
            distinct_days,
            "30+",
            "ready" if distinct_days >= 30 else "building",
            "Needed for stronger medium-term direction and stability signals.",
        )
        add_readiness(
            "90-day trend window",
            distinct_days,
            "90+",
            "ready" if distinct_days >= 90 else "building",
            "Needed before treating monthly/seasonal trend predictions as meaningful.",
        )
        add_readiness(
            "Distinct items",
            f"{distinct_items:,}",
            "100+",
            "ready" if distinct_items >= 100 else "building",
            "More items give the dashboard better comparison/ranking context.",
        )

        if total_rows <= 0:
            return {
                "ok": True,
                "status": "Trend readiness loaded, but daily_item_metrics has no rows yet.",
                "readiness": readiness,
                "top_trends": [],
            }

        raw_rows = conn.execute(
            """
            WITH per_item AS (
                SELECT
                    item_name,
                    COUNT(DISTINCT metric_date) AS days_seen,
                    MIN(metric_date) AS first_date,
                    MAX(metric_date) AS last_date,
                    AVG(avg_margin) AS avg_margin_all,
                    AVG(avg_roi) AS avg_roi_all,
                    AVG(avg_volume) AS avg_volume_all,
                    AVG(avg_recommendation_score) AS avg_score_all,
                    AVG(margin_volatility) AS avg_margin_volatility,
                    SUM(scan_count) AS scan_count_total
                FROM daily_item_metrics
                GROUP BY item_name
            ),
            first_day AS (
                SELECT d.item_name, AVG(d.avg_margin) AS first_margin, AVG(d.avg_recommendation_score) AS first_score
                FROM daily_item_metrics d
                JOIN per_item p
                  ON p.item_name = d.item_name
                 AND p.first_date = d.metric_date
                GROUP BY d.item_name
            ),
            last_day AS (
                SELECT d.item_name, AVG(d.avg_margin) AS last_margin, AVG(d.avg_recommendation_score) AS last_score
                FROM daily_item_metrics d
                JOIN per_item p
                  ON p.item_name = d.item_name
                 AND p.last_date = d.metric_date
                GROUP BY d.item_name
            )
            SELECT
                p.item_name,
                p.days_seen,
                p.first_date,
                p.last_date,
                ROUND(p.avg_margin_all, 2) AS avg_margin,
                ROUND(p.avg_roi_all, 2) AS avg_roi,
                ROUND(p.avg_volume_all, 2) AS avg_volume,
                ROUND(p.avg_score_all, 2) AS avg_score,
                ROUND(p.avg_margin_volatility, 2) AS margin_volatility,
                p.scan_count_total,
                ROUND(f.first_margin, 2) AS first_margin,
                ROUND(l.last_margin, 2) AS last_margin,
                ROUND(f.first_score, 2) AS first_score,
                ROUND(l.last_score, 2) AS last_score
            FROM per_item p
            LEFT JOIN first_day f ON f.item_name = p.item_name
            LEFT JOIN last_day l ON l.item_name = p.item_name
            WHERE p.days_seen >= 2
            ORDER BY p.days_seen DESC, p.avg_score_all DESC
            LIMIT 500
            """
        ).fetchall()

        trend_rows = []

        for row in raw_rows:
            margin_delta, margin_direction = _trend_value(row["last_margin"], row["first_margin"])
            score_delta, score_direction = _trend_value(row["last_score"], row["first_score"])

            margin_delta_value = round(margin_delta, 2) if margin_delta is not None else None
            score_delta_value = round(score_delta, 2) if score_delta is not None else None

            days_seen = int(row["days_seen"] or 0)
            scan_count_total = int(row["scan_count_total"] or 0)
            avg_score = row["avg_score"] if row["avg_score"] is not None else 0
            margin_volatility = row["margin_volatility"] if row["margin_volatility"] is not None else 0

            readiness_weight = min(days_seen / 7, 1.0)
            score_component = float(avg_score or 0)
            margin_component = max(float(margin_delta_value or 0), 0) / 100
            score_delta_component = max(float(score_delta_value or 0), 0)
            volatility_penalty = min(abs(float(margin_volatility or 0)) / 1000, 25)
            scan_weight = min(scan_count_total / 25, 10)

            trend_score = round(
                readiness_weight
                * (
                    (score_component * 0.45)
                    + (score_delta_component * 0.30)
                    + (margin_component * 0.15)
                    + (scan_weight * 0.10)
                    - volatility_penalty
                ),
                2,
            )

            trend_rows.append(
                {
                    "Item": row["item_name"],
                    "Days Seen": days_seen,
                    "First Date": row["first_date"],
                    "Last Date": row["last_date"],
                    "Trend Score": trend_score,
                    "Avg Score": row["avg_score"],
                    "Score Δ": score_delta_value,
                    "Score Direction": score_direction,
                    "Avg Margin": row["avg_margin"],
                    "Margin Δ": margin_delta_value,
                    "Margin Direction": margin_direction,
                    "Margin Volatility": row["margin_volatility"],
                    "Total Scans": scan_count_total,
                }
            )

        trend_rows.sort(key=lambda item: (item["Trend Score"], item["Days Seen"], item["Total Scans"]), reverse=True)
        trend_rows = trend_rows[: max(1, min(int(limit or 25), 100))]

        status = (
            f"Trend readiness loaded from daily_item_metrics. "
            f"{total_rows:,} metric rows, {distinct_days} day(s), {distinct_items:,} item(s). "
            f"Top trend rows shown: {len(trend_rows)}."
        )

        return {
            "ok": True,
            "status": status,
            "readiness": readiness,
            "top_trends": trend_rows,
        }
    finally:
        conn.close()

def _date_minus_days(date_text: str | None, days: int) -> str | None:
    parsed = _parse_datetime(date_text)

    if not parsed:
        return None

    return (parsed - timedelta(days=max(1, int(days)))).date().isoformat()


def build_item_trend_explorer_snapshot(item_query: str | None = None, days: int = 90) -> dict[str, Any]:
    conn, db_path = _connect()

    try:
        if not _table_exists(conn, "daily_item_metrics"):
            return {
                "ok": False,
                "status": "daily_item_metrics is missing. Open Admin > Data Health, click Apply Data Schema / Indexes, then Rebuild Daily Item Metrics.",
                "matched_item": "",
                "summary_cards": [],
                "rows": [],
                "matches": [],
            }

        total_rows = int(_scalar(conn, "SELECT COUNT(*) FROM daily_item_metrics") or 0)

        if total_rows <= 0:
            return {
                "ok": False,
                "status": "daily_item_metrics has no rows yet. Open Admin > Data Health and click Rebuild Daily Item Metrics.",
                "matched_item": "",
                "summary_cards": [],
                "rows": [],
                "matches": [],
            }

        safe_days = max(1, min(int(days or 90), 3650))
        query_text = str(item_query or "").strip()

        if query_text:
            like = f"%{query_text.lower()}%"
            prefix = f"{query_text.lower()}%"
            match_rows = conn.execute(
                """
                SELECT
                    item_name,
                    COUNT(DISTINCT metric_date) AS days_seen,
                    COUNT(*) AS metric_rows,
                    ROUND(AVG(avg_margin), 2) AS avg_margin,
                    ROUND(AVG(avg_recommendation_score), 2) AS avg_score,
                    MAX(metric_date) AS newest_date
                FROM daily_item_metrics
                WHERE LOWER(item_name) LIKE ?
                GROUP BY item_name
                ORDER BY
                    CASE
                        WHEN LOWER(item_name) = ? THEN 0
                        WHEN LOWER(item_name) LIKE ? THEN 1
                        ELSE 2
                    END,
                    days_seen DESC,
                    avg_score DESC
                LIMIT 15
                """,
                (like, query_text.lower(), prefix),
            ).fetchall()
        else:
            match_rows = conn.execute(
                """
                SELECT
                    item_name,
                    COUNT(DISTINCT metric_date) AS days_seen,
                    COUNT(*) AS metric_rows,
                    ROUND(AVG(avg_margin), 2) AS avg_margin,
                    ROUND(AVG(avg_recommendation_score), 2) AS avg_score,
                    MAX(metric_date) AS newest_date
                FROM daily_item_metrics
                GROUP BY item_name
                ORDER BY days_seen DESC, avg_score DESC, avg_margin DESC
                LIMIT 15
                """
            ).fetchall()

        matches = [
            {
                "Item": row["item_name"],
                "Days Seen": row["days_seen"],
                "Metric Rows": row["metric_rows"],
                "Avg Margin": row["avg_margin"],
                "Avg Score": row["avg_score"],
                "Newest Date": row["newest_date"],
            }
            for row in match_rows
        ]

        if not match_rows:
            return {
                "ok": False,
                "status": f"No daily metrics matched {query_text!r}. Try a broader item name.",
                "matched_item": "",
                "summary_cards": [],
                "rows": [],
                "matches": [],
            }

        matched_item = match_rows[0]["item_name"]
        newest_date = _scalar(
            conn,
            "SELECT MAX(metric_date) FROM daily_item_metrics WHERE item_name = ?",
            (matched_item,),
        )
        cutoff = _date_minus_days(newest_date, safe_days) if newest_date else None

        params: list[Any] = [matched_item]
        where = "WHERE item_name = ?"

        if cutoff:
            where += " AND metric_date >= ?"
            params.append(cutoff)

        metric_rows = conn.execute(
            f"""
            SELECT
                metric_date,
                SUM(scan_count) AS scan_count,
                SUM(profitable_count) AS profitable_count,
                ROUND(AVG(avg_margin), 2) AS avg_margin,
                ROUND(AVG(avg_total_profit), 2) AS avg_total_profit,
                ROUND(AVG(avg_profit_per_item), 2) AS avg_profit_per_item,
                ROUND(AVG(avg_roi), 2) AS avg_roi,
                ROUND(AVG(avg_volume), 2) AS avg_volume,
                ROUND(AVG(avg_quick_score), 2) AS avg_quick_score,
                ROUND(AVG(avg_overnight_score), 2) AS avg_overnight_score,
                ROUND(AVG(avg_recommendation_score), 2) AS avg_recommendation_score,
                ROUND(AVG(margin_volatility), 2) AS margin_volatility,
                MIN(min_margin) AS min_margin,
                MAX(max_margin) AS max_margin
            FROM daily_item_metrics
            {where}
            GROUP BY metric_date
            ORDER BY metric_date
            """,
            tuple(params),
        ).fetchall()

        rows = [
            {
                "Metric Date": row["metric_date"],
                "Scan Count": row["scan_count"],
                "Profitable Count": row["profitable_count"],
                "Avg Margin": row["avg_margin"],
                "Avg Total Profit": row["avg_total_profit"],
                "Avg Profit / Item": row["avg_profit_per_item"],
                "Avg ROI": row["avg_roi"],
                "Avg Volume": row["avg_volume"],
                "Quick Score": row["avg_quick_score"],
                "Overnight Score": row["avg_overnight_score"],
                "Recommendation Score": row["avg_recommendation_score"],
                "Margin Volatility": row["margin_volatility"],
                "Min Margin": row["min_margin"],
                "Max Margin": row["max_margin"],
            }
            for row in metric_rows
        ]

        if not rows:
            return {
                "ok": False,
                "status": f"{matched_item} matched, but no rows were found in the selected {safe_days}-day window.",
                "matched_item": matched_item,
                "summary_cards": [],
                "rows": [],
                "matches": matches,
            }

        first = rows[0]
        last = rows[-1]

        margin_delta, margin_direction = _trend_value(last.get("Avg Margin"), first.get("Avg Margin"))
        score_delta, score_direction = _trend_value(last.get("Recommendation Score"), first.get("Recommendation Score"))

        total_scans = sum(int(row.get("Scan Count") or 0) for row in rows)
        total_profitable = sum(int(row.get("Profitable Count") or 0) for row in rows)
        avg_score = _avg([_safe_float(row.get("Recommendation Score")) for row in rows])
        avg_margin = _avg([_safe_float(row.get("Avg Margin")) for row in rows])
        avg_volatility = _avg([_safe_float(row.get("Margin Volatility")) for row in rows])

        best_row = max(rows, key=lambda row: _safe_float(row.get("Recommendation Score")) or -999999)

        summary_cards = [
            {
                "Title": "Matched Item",
                "Value": matched_item,
                "Detail": f"{len(matches)} match(es), {len(rows)} metric day(s)",
            },
            {
                "Title": "Date Range",
                "Value": f"{first.get('Metric Date')} -> {last.get('Metric Date')}",
                "Detail": f"selected window: {safe_days} day(s)",
            },
            {
                "Title": "Avg Margin",
                "Value": round(avg_margin, 2) if avg_margin is not None else "n/a",
                "Detail": f"delta {round(margin_delta, 2) if margin_delta is not None else 'n/a'} ({margin_direction})",
            },
            {
                "Title": "Avg Score",
                "Value": round(avg_score, 2) if avg_score is not None else "n/a",
                "Detail": f"delta {round(score_delta, 2) if score_delta is not None else 'n/a'} ({score_direction})",
            },
            {
                "Title": "Total Scans",
                "Value": f"{total_scans:,}",
                "Detail": f"profitable observations: {total_profitable:,}",
            },
            {
                "Title": "Margin Volatility",
                "Value": round(avg_volatility, 2) if avg_volatility is not None else "n/a",
                "Detail": "lower is usually more stable",
            },
            {
                "Title": "Best Score Day",
                "Value": best_row.get("Metric Date"),
                "Detail": f"score {best_row.get('Recommendation Score')}",
            },
        ]

        status = (
            f"Loaded trend explorer for {matched_item}. "
            f"{len(rows)} daily point(s), {total_scans:,} total scan observations, "
            f"margin direction={margin_direction}, score direction={score_direction}."
        )

        if query_text and matched_item.lower() != query_text.lower():
            status += f" Search {query_text!r} matched closest item {matched_item!r}."

        return {
            "ok": True,
            "status": status,
            "matched_item": matched_item,
            "summary_cards": summary_cards,
            "rows": rows,
            "matches": matches,
        }
    finally:
        conn.close()

def _date_only(value: Any) -> str | None:
    parsed = _parse_datetime(value)

    if parsed:
        return parsed.date().isoformat()

    text = str(value or "").strip()

    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]

    return None


def _hours_since(value: Any) -> float | None:
    parsed = _parse_datetime(value)

    if not parsed:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600)


def build_metrics_automation_snapshot(max_age_hours: int = 12) -> dict[str, Any]:
    conn, db_path = _connect()

    try:
        checks: list[dict[str, Any]] = []

        def add_check(check: str, value: Any, status: str, notes: str) -> None:
            checks.append(
                {
                    "Check": check,
                    "Value": value,
                    "Status": status,
                    "Notes": notes,
                }
            )

        scan_rows = 0
        scan_latest = None
        scan_latest_date = None
        metric_rows = 0
        metric_latest_date = None
        metric_updated_at = None
        stale_days = None

        if _table_exists(conn, "scan_results"):
            scan_rows = int(_scalar(conn, "SELECT COUNT(*) FROM scan_results") or 0)
            if "scanned_at" in _columns(conn, "scan_results"):
                scan_latest = _scalar(conn, "SELECT MAX(scanned_at) FROM scan_results")
                scan_latest_date = _date_only(scan_latest)

        if _table_exists(conn, "daily_item_metrics"):
            metric_rows = int(_scalar(conn, "SELECT COUNT(*) FROM daily_item_metrics") or 0)
            metric_latest_date = _scalar(conn, "SELECT MAX(metric_date) FROM daily_item_metrics")
            if "updated_at" in _columns(conn, "daily_item_metrics"):
                metric_updated_at = _scalar(conn, "SELECT MAX(updated_at) FROM daily_item_metrics")

        if scan_latest_date and metric_latest_date:
            try:
                stale_days = (
                    datetime.strptime(scan_latest_date, "%Y-%m-%d").date()
                    - datetime.strptime(str(metric_latest_date)[:10], "%Y-%m-%d").date()
                ).days
            except Exception:
                stale_days = None

        updated_age_hours = _hours_since(metric_updated_at)
        max_age = max(1, int(max_age_hours or 12))

        if not _table_exists(conn, "daily_item_metrics"):
            freshness_status = "schema missing"
            freshness_notes = "Click Apply Data Schema / Indexes before refreshing metrics."
        elif metric_rows <= 0:
            freshness_status = "empty"
            freshness_notes = "Click Rebuild Daily Item Metrics or Refresh Stale Metrics."
        elif stale_days is not None and stale_days > 0:
            freshness_status = "stale"
            freshness_notes = f"daily_item_metrics is {stale_days} day(s) behind scan_results."
        elif updated_age_hours is not None and updated_age_hours > max_age:
            freshness_status = "aging"
            freshness_notes = f"Metrics were last rebuilt about {round(updated_age_hours, 1)} hour(s) ago."
        else:
            freshness_status = "current"
            freshness_notes = "daily_item_metrics appears current enough for trend views."

        add_check("scan_results rows", f"{scan_rows:,}", "ok" if scan_rows else "missing", "Raw scanner observations.")
        add_check("latest scan date", scan_latest_date or "", "ok" if scan_latest_date else "missing", str(scan_latest or ""))
        add_check("daily_item_metrics rows", f"{metric_rows:,}", "ok" if metric_rows else "empty", "Aggregate rows used by Data Health and Item Trends.")
        add_check("latest metric date", metric_latest_date or "", "ok" if metric_latest_date else "missing", "Newest daily aggregate date.")
        add_check(
            "metrics updated age",
            "n/a" if updated_age_hours is None else f"{round(updated_age_hours, 1)} hours",
            "ok" if updated_age_hours is not None and updated_age_hours <= max_age else "aging",
            f"Target age <= {max_age} hours.",
        )
        add_check(
            "freshness",
            freshness_status,
            "ready" if freshness_status == "current" else "needs attention",
            freshness_notes,
        )

        return {
            "ok": True,
            "database_path": str(db_path),
            "checks": checks,
            "scan_rows": scan_rows,
            "scan_latest_date": scan_latest_date,
            "metric_rows": metric_rows,
            "metric_latest_date": metric_latest_date,
            "metric_updated_at": metric_updated_at,
            "stale_days": stale_days,
            "updated_age_hours": updated_age_hours,
            "freshness_status": freshness_status,
            "needs_refresh": freshness_status in {"schema missing", "empty", "stale", "aging"},
        }
    finally:
        conn.close()


def refresh_daily_metrics_if_stale(
    max_age_hours: int = 12,
    rebuild_days: int = 14,
    force: bool = False,
) -> dict[str, Any]:
    schema_result = ensure_data_health_schema()
    before = build_metrics_automation_snapshot(max_age_hours=max_age_hours)

    stale_days = before.get("stale_days")
    metric_rows = int(before.get("metric_rows") or 0)
    needs_refresh = bool(before.get("needs_refresh"))

    should_refresh = bool(force or needs_refresh)

    if not should_refresh:
        return {
            "ok": True,
            "refreshed": False,
            "status": "Daily metrics are current enough; no rebuild was needed.",
            "before": before,
            "after": before,
            "schema_result": schema_result,
        }

    safe_days = max(1, min(int(rebuild_days or 14), 3650))

    if stale_days is not None and stale_days > 0:
        safe_days = max(safe_days, min(int(stale_days) + 3, 3650))

    if metric_rows <= 0:
        safe_days = max(safe_days, 120)

    rebuild_result = rebuild_daily_item_metrics(days=safe_days)
    after = build_metrics_automation_snapshot(max_age_hours=max_age_hours)

    return {
        "ok": bool(rebuild_result.get("ok", False)),
        "refreshed": True,
        "status": (
            f"Stale daily metrics refresh complete. "
            f"Rebuilt last {safe_days} day(s). {rebuild_result.get('status', '')}"
        ),
        "before": before,
        "after": after,
        "schema_result": schema_result,
        "rebuild_result": rebuild_result,
        "rebuild_days": safe_days,
    }

def _format_mb(value: float | None) -> str:
    if value is None:
        return "n/a"

    return f"{round(float(value), 2)} MB"


def build_retention_preview_snapshot(retention_days: int | str | None = 90) -> dict[str, Any]:
    conn, db_path = _connect()

    try:
        if not _table_exists(conn, "scan_results"):
            return {
                "ok": False,
                "status": "scan_results table was not found. No retention preview is available.",
                "rows": [
                    {
                        "Metric": "scan_results",
                        "Value": "missing",
                        "Notes": "No raw scanner table was found.",
                    }
                ],
            }

        if "scanned_at" not in _columns(conn, "scan_results"):
            return {
                "ok": False,
                "status": "scan_results.scanned_at was not found. No retention preview is available.",
                "rows": [
                    {
                        "Metric": "scan_results.scanned_at",
                        "Value": "missing",
                        "Notes": "Retention preview requires scanned_at.",
                    }
                ],
            }

        try:
            days_int = int(retention_days or 0)
        except Exception:
            days_int = 0

        days_int = max(0, min(days_int, 3650))

        total_rows = int(_scalar(conn, "SELECT COUNT(*) FROM scan_results") or 0)
        oldest_scan = _scalar(conn, "SELECT MIN(scanned_at) FROM scan_results WHERE scanned_at IS NOT NULL AND TRIM(CAST(scanned_at AS TEXT)) <> ''")
        newest_scan = _scalar(conn, "SELECT MAX(scanned_at) FROM scan_results WHERE scanned_at IS NOT NULL AND TRIM(CAST(scanned_at AS TEXT)) <> ''")
        distinct_days = int(
            _scalar(
                conn,
                """
                SELECT COUNT(DISTINCT substr(CAST(scanned_at AS TEXT), 1, 10))
                FROM scan_results
                WHERE scanned_at IS NOT NULL
                  AND TRIM(CAST(scanned_at AS TEXT)) <> ''
                """
            )
            or 0
        )

        db_size_mb = round(db_path.stat().st_size / 1024 / 1024, 2) if db_path.exists() else 0.0

        if days_int <= 0:
            rows = [
                {
                    "Metric": "Retention mode",
                    "Value": "Keep forever",
                    "Notes": "No rows would be removed.",
                },
                {
                    "Metric": "scan_results rows",
                    "Value": f"{total_rows:,}",
                    "Notes": "All raw scan rows would be retained.",
                },
                {
                    "Metric": "Scan date coverage",
                    "Value": f"{distinct_days} day(s)",
                    "Notes": f"{oldest_scan or ''} -> {newest_scan or ''}",
                },
                {
                    "Metric": "Database size",
                    "Value": _format_mb(db_size_mb),
                    "Notes": "Preview only. Database is not changed.",
                },
            ]

            return {
                "ok": True,
                "status": "Retention preview: Keep forever selected. No raw scan rows would be removed.",
                "rows": rows,
                "would_delete_rows": 0,
                "would_keep_rows": total_rows,
                "retention_days": days_int,
                "cutoff_date": "",
            }

        newest_date = _date_only(newest_scan)
        cutoff_date = _date_minus_days(newest_date, days_int) if newest_date else None

        if not cutoff_date:
            return {
                "ok": False,
                "status": "Retention preview could not determine a cutoff date from the newest scan.",
                "rows": [
                    {
                        "Metric": "Newest scan",
                        "Value": newest_scan or "",
                        "Notes": "Could not parse newest scan date.",
                    }
                ],
            }

        delete_rows = int(
            _scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM scan_results
                WHERE scanned_at IS NOT NULL
                  AND substr(CAST(scanned_at AS TEXT), 1, 10) < ?
                """,
                (cutoff_date,),
            )
            or 0
        )
        keep_rows = max(total_rows - delete_rows, 0)

        newest_deleted_scan = None
        oldest_retained_scan = None

        if delete_rows:
            newest_deleted_scan = _scalar(
                conn,
                """
                SELECT MAX(scanned_at)
                FROM scan_results
                WHERE scanned_at IS NOT NULL
                  AND substr(CAST(scanned_at AS TEXT), 1, 10) < ?
                """,
                (cutoff_date,),
            )

        if keep_rows:
            oldest_retained_scan = _scalar(
                conn,
                """
                SELECT MIN(scanned_at)
                FROM scan_results
                WHERE scanned_at IS NOT NULL
                  AND substr(CAST(scanned_at AS TEXT), 1, 10) >= ?
                """,
                (cutoff_date,),
            )

        delete_pct = round((delete_rows / total_rows) * 100, 2) if total_rows else 0.0
        keep_pct = round((keep_rows / total_rows) * 100, 2) if total_rows else 0.0

        estimated_raw_scan_mb = None
        estimated_deleted_mb = None
        estimated_remaining_mb = None

        if total_rows:
            # This is intentionally conservative/rough. SQLite file size will
            # not fully shrink until vacuum/backup compaction, so call it impact,
            # not guaranteed immediate disk savings.
            estimated_raw_scan_mb = db_size_mb * min(1.0, total_rows / max(total_rows, 1))
            estimated_deleted_mb = db_size_mb * (delete_rows / total_rows)
            estimated_remaining_mb = max(db_size_mb - estimated_deleted_mb, 0)

        rows = [
            {
                "Metric": "Retention mode",
                "Value": f"Keep last {days_int} day(s)",
                "Notes": "Preview only. No rows are deleted.",
            },
            {
                "Metric": "Cutoff date",
                "Value": cutoff_date,
                "Notes": f"Rows before this date would be candidates for cleanup.",
            },
            {
                "Metric": "scan_results rows",
                "Value": f"{total_rows:,}",
                "Notes": f"{distinct_days} scan day(s): {oldest_scan or ''} -> {newest_scan or ''}",
            },
            {
                "Metric": "Rows that would be removed",
                "Value": f"{delete_rows:,}",
                "Notes": f"{delete_pct}% of scan_results.",
            },
            {
                "Metric": "Rows that would be retained",
                "Value": f"{keep_rows:,}",
                "Notes": f"{keep_pct}% of scan_results.",
            },
            {
                "Metric": "Newest deleted scan",
                "Value": newest_deleted_scan or "",
                "Notes": "Newest raw scan row that would be removed.",
            },
            {
                "Metric": "Oldest retained scan",
                "Value": oldest_retained_scan or "",
                "Notes": "Oldest raw scan row that would remain.",
            },
            {
                "Metric": "Current database size",
                "Value": _format_mb(db_size_mb),
                "Notes": str(db_path.name),
            },
            {
                "Metric": "Estimated impacted size",
                "Value": _format_mb(estimated_deleted_mb),
                "Notes": "Rough estimate. SQLite may require VACUUM/backup compaction to reclaim file space.",
            },
            {
                "Metric": "Safety",
                "Value": "Preview only",
                "Notes": "This release phase does not delete, vacuum, or compact anything.",
            },
        ]

        status = (
            f"Retention preview complete. Keep last {days_int} day(s): "
            f"{delete_rows:,} scan_results row(s) would be removable and {keep_rows:,} would remain. "
            "No rows were deleted."
        )

        if delete_rows == 0:
            status = (
                f"Retention preview complete. Keep last {days_int} day(s): no raw scan rows are old enough to remove. "
                "No rows were deleted."
            )

        return {
            "ok": True,
            "status": status,
            "rows": rows,
            "would_delete_rows": delete_rows,
            "would_keep_rows": keep_rows,
            "delete_pct": delete_pct,
            "keep_pct": keep_pct,
            "retention_days": days_int,
            "cutoff_date": cutoff_date,
            "estimated_deleted_mb": estimated_deleted_mb,
            "estimated_remaining_mb": estimated_remaining_mb,
        }
    finally:
        conn.close()
