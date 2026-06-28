from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .common import (
    _avg,
    _column_map,
    _connect,
    _first_col,
    _metric_date,
    _safe_float,
    _safe_identifier,
    _stddev,
    _table_exists,
    _utc_now,
)
from .schema import ensure_data_health_schema


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

        selected_cols: list[str] = []

        for column in [
            scanned_col,
            item_name_col,
            item_id_col,
            window_col,
            margin_col,
            total_profit_col,
            profit_per_item_col,
            roi_col,
            volume_col,
            quick_score_col,
            overnight_score_col,
            recommendation_score_col,
        ]:
            if column and column not in selected_cols:
                selected_cols.append(column)

        selected_sql = ", ".join(_safe_identifier(column) for column in selected_cols)
        query = f"SELECT {selected_sql} FROM {_safe_identifier('scan_results')} {where_clause}"

        groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}

        rows_seen = 0
        rows_used = 0
        started_at = time.monotonic()

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
        elapsed_seconds = round(time.monotonic() - started_at, 2)

        return {
            "ok": True,
            "database_path": str(db_path),
            "status": (
                f"Daily item metrics rebuilt. Read {rows_seen:,} scan rows, "
                f"used {rows_used:,}, wrote {len(groups):,} daily metric rows "
                f"in {elapsed_seconds} second(s)."
            ),
            "rows_seen": rows_seen,
            "rows_used": rows_used,
            "metric_rows_written": len(groups),
            "elapsed_seconds": elapsed_seconds,
            "days": days,
            "cutoff_date": cutoff_date,
            "schema_result": schema_result,
        }
    finally:
        conn.close()
