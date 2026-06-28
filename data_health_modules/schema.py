from __future__ import annotations

import sqlite3
from typing import Any

from .common import _columns, _connect, _safe_identifier, _table_exists


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
