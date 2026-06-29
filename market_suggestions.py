from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from account_context import BASE_DIR


DB_FILE = Path(BASE_DIR) / "osrs_flip_scanner.db"
GE_TAX_RATE = 0.02
GE_TAX_CAP_PER_ITEM = 5_000_000
SQLITE_TIMEOUT_SECONDS = 30
SQLITE_BUSY_TIMEOUT_MS = 30000


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _normalize_name(value: Any) -> str:
    return str(value or "").strip().lower()


def ge_tax_per_item(sell_price: Any) -> int:
    sell_price = max(0, _safe_int(sell_price))

    if sell_price <= 0:
        return 0

    return min(int(sell_price * GE_TAX_RATE), GE_TAX_CAP_PER_ITEM)


def latest_sell_suggestion(item_id: Any = None, item_name: str | None = None, db_path: str | Path | None = None) -> dict[str, Any] | None:
    path = Path(db_path or DB_FILE)

    if not path.exists():
        return None

    item_id_value = _safe_int(item_id, 0)
    normalized_name = _normalize_name(item_name)

    if item_id_value <= 0 and not normalized_name:
        return None

    conn = sqlite3.connect(path, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    params: list[Any] = []
    where_parts = [
        "sr.run_id = (SELECT MAX(run_id) FROM scan_results)",
    ]

    if item_id_value > 0:
        where_parts.append("sr.item_id = ?")
        params.append(item_id_value)
    else:
        where_parts.append("LOWER(sr.item_name) = LOWER(?)")
        params.append(str(item_name or "").strip())

    try:
        cursor.execute(
            f"""
            SELECT
                sr.item_id,
                sr.item_name,
                sr.target_buy,
                sr.target_sell,
                sr.avg_high,
                sr.profit_per_item,
                sr.roi_percent,
                sr.expected_fill_hours,
                sr.expected_fill_time,
                sr.liquidity_score,
                sr.window_name,
                sr.price_warning,
                sr.market_context_warning,
                sr.trend_warning,
                sr.scanned_at
            FROM scan_results sr
            WHERE {' AND '.join(where_parts)}
            ORDER BY
                COALESCE(sr.liquidity_score, 0) DESC,
                COALESCE(sr.expected_fill_hours, 9999) ASC,
                COALESCE(sr.recommendation_score, sr.score, 0) DESC,
                COALESCE(sr.window_rank, 9999) ASC
            LIMIT 1
            """,
            params,
        )
        row = cursor.fetchone()
    except Exception:
        row = None
    finally:
        conn.close()

    if not row:
        return None

    target_sell = _safe_int(row["target_sell"])
    avg_high = _safe_int(row["avg_high"])
    recommended_sell = target_sell or avg_high

    if recommended_sell <= 0:
        return None

    tax_each = ge_tax_per_item(recommended_sell)

    return {
        "item_id": _safe_int(row["item_id"], item_id_value),
        "item_name": row["item_name"] or item_name or "",
        "recommended_sell": recommended_sell,
        "target_buy": _safe_int(row["target_buy"]),
        "target_sell": target_sell,
        "avg_high": avg_high,
        "tax_each": tax_each,
        "profit_per_item": _safe_int(row["profit_per_item"]),
        "roi_percent": _safe_float(row["roi_percent"]),
        "expected_fill_hours": _safe_float(row["expected_fill_hours"]),
        "expected_fill_time": row["expected_fill_time"] or "",
        "liquidity_score": _safe_float(row["liquidity_score"]),
        "window_name": row["window_name"] or "",
        "price_warning": row["price_warning"] or "",
        "market_context_warning": row["market_context_warning"] or "",
        "trend_warning": row["trend_warning"] or "",
        "scanned_at": row["scanned_at"] or "",
    }


def latest_hour_sell_suggestion(item_id: Any = None, item_name: str | None = None, db_path: str | Path | None = None) -> dict[str, Any] | None:
    path = Path(db_path or DB_FILE)

    if not path.exists():
        return None

    item_id_value = _safe_int(item_id, 0)
    normalized_name = _normalize_name(item_name)

    if item_id_value <= 0 and not normalized_name:
        return None

    params: list[Any] = []
    if item_id_value > 0:
        where = "item_id = ?"
        params.append(item_id_value)
    else:
        where = "LOWER(item_name) = LOWER(?)"
        params.append(str(item_name or "").strip())

    conn = sqlite3.connect(path, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute(
            f"""
            SELECT
                item_id,
                item_name,
                latest_low,
                latest_high,
                avg_low_1h,
                avg_high_1h,
                volume_1h,
                high_volume_1h,
                low_volume_1h,
                captured_at
            FROM market_price_snapshots
            WHERE {where}
            ORDER BY captured_at DESC, id DESC
            LIMIT 1
            """,
            params,
        )
        row = cursor.fetchone()
    except Exception:
        row = None
    finally:
        conn.close()

    if not row:
        return None

    avg_low_1h = _safe_int(row["avg_low_1h"])
    avg_high_1h = _safe_int(row["avg_high_1h"])
    latest_high = _safe_int(row["latest_high"])
    latest_low = _safe_int(row["latest_low"])
    recommended_sell = avg_high_1h or latest_high or avg_low_1h or latest_low

    if recommended_sell <= 0:
        return None

    return {
        "item_id": _safe_int(row["item_id"], item_id_value),
        "item_name": row["item_name"] or item_name or "",
        "recommended_sell": recommended_sell,
        "avg_low_1h": avg_low_1h,
        "avg_high_1h": avg_high_1h,
        "latest_low": latest_low,
        "latest_high": latest_high,
        "volume_1h": _safe_int(row["volume_1h"]),
        "high_volume_1h": _safe_int(row["high_volume_1h"]),
        "low_volume_1h": _safe_int(row["low_volume_1h"]),
        "tax_each": ge_tax_per_item(recommended_sell),
        "window_name": "1h high/low",
        "scanned_at": row["captured_at"] or "",
    }


def buy_exit_estimate(
    item_id: Any = None,
    item_name: str | None = None,
    buy_price: Any = None,
    quantity: Any = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    suggestion = latest_sell_suggestion(item_id=item_id, item_name=item_name, db_path=db_path)
    buy_each = _safe_int(buy_price)
    qty = max(0, _safe_int(quantity))

    if not suggestion:
        return {
            "recommended_sell": 0,
            "tax_each": 0,
            "estimated_net_each": 0,
            "estimated_total_profit": 0,
            "suggestion": None,
        }

    sell_each = _safe_int(suggestion.get("recommended_sell"))
    tax_each = ge_tax_per_item(sell_each)
    estimated_net_each = sell_each - tax_each - buy_each if buy_each > 0 else _safe_int(suggestion.get("profit_per_item"))
    estimated_total_profit = estimated_net_each * qty if qty > 0 else 0

    return {
        "recommended_sell": sell_each,
        "tax_each": tax_each,
        "estimated_net_each": estimated_net_each,
        "estimated_total_profit": estimated_total_profit,
        "suggestion": suggestion,
    }
