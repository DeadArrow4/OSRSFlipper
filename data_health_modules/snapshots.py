from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .common import (
    _columns,
    _connect,
    _fetchone,
    _index_exists,
    _safe_identifier,
    _scalar,
    _table_exists,
    _table_names,
)
from .schema import _recommended_index_specs


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
