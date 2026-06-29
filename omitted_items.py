from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from account_context import BASE_DIR, get_account_scope


DB_FILE = Path(BASE_DIR) / "osrs_flip_scanner.db"
SQLITE_TIMEOUT_SECONDS = 30
SQLITE_BUSY_TIMEOUT_MS = 30000


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_item_name(item_name: Any) -> str:
    return str(item_name or "").strip().lower()


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except Exception:
        return None


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    return conn


def init_omitted_items_db() -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS omitted_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_username TEXT NOT NULL,
            osrs_account_name TEXT NOT NULL,
            item_id INTEGER,
            item_name TEXT NOT NULL,
            normalized_item_name TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL,
            restored_at TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_omitted_items_account_name_active
        ON omitted_items(app_username, osrs_account_name, normalized_item_name)
        WHERE restored_at IS NULL
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_omitted_items_account_active
        ON omitted_items(app_username, osrs_account_name, restored_at, item_name)
        """
    )

    conn.commit()
    conn.close()


def omit_item(item_name: str, item_id: Any = None, reason: str | None = None) -> dict[str, Any]:
    init_omitted_items_db()
    item_name = str(item_name or "").strip()
    normalized = _normalize_item_name(item_name)

    if not normalized:
        raise ValueError("Choose an item to omit.")

    scope = get_account_scope()
    item_id_value = _safe_int(item_id)
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO omitted_items (
            app_username,
            osrs_account_name,
            item_id,
            item_name,
            normalized_item_name,
            reason,
            created_at,
            restored_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(app_username, osrs_account_name, normalized_item_name)
        WHERE restored_at IS NULL
        DO UPDATE SET
            item_id = COALESCE(excluded.item_id, omitted_items.item_id),
            item_name = excluded.item_name,
            reason = excluded.reason
        """,
        (
            scope["app_username"],
            scope["osrs_account_name"],
            item_id_value,
            item_name,
            normalized,
            str(reason or "").strip(),
            _now_utc(),
        ),
    )

    conn.commit()
    conn.close()

    return {
        "item_name": item_name,
        "item_id": item_id_value,
        "account": scope,
    }


def restore_omitted_item(item_name: str | None = None, row_id: Any = None) -> int:
    init_omitted_items_db()
    scope = get_account_scope()
    conn = get_connection()
    cursor = conn.cursor()
    params: list[Any] = [_now_utc(), scope["app_username"], scope["osrs_account_name"]]

    where = "app_username = ? AND osrs_account_name = ? AND restored_at IS NULL"

    if row_id not in (None, ""):
        where += " AND id = ?"
        params.append(_safe_int(row_id))
    else:
        normalized = _normalize_item_name(item_name)

        if not normalized:
            conn.close()
            return 0

        where += " AND normalized_item_name = ?"
        params.append(normalized)

    cursor.execute(
        f"""
        UPDATE omitted_items
        SET restored_at = ?
        WHERE {where}
        """,
        params,
    )

    count = int(cursor.rowcount or 0)
    conn.commit()
    conn.close()
    return count


def list_omitted_items(include_restored: bool = False) -> list[dict[str, Any]]:
    init_omitted_items_db()
    scope = get_account_scope()
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    where = "app_username = ? AND osrs_account_name = ?"
    if not include_restored:
        where += " AND restored_at IS NULL"

    cursor.execute(
        f"""
        SELECT
            id,
            item_id,
            item_name,
            reason,
            created_at,
            restored_at
        FROM omitted_items
        WHERE {where}
        ORDER BY restored_at IS NOT NULL, item_name COLLATE NOCASE
        """,
        (scope["app_username"], scope["osrs_account_name"]),
    )

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_omitted_item_names() -> set[str]:
    return {
        _normalize_item_name(row.get("item_name"))
        for row in list_omitted_items(include_restored=False)
        if _normalize_item_name(row.get("item_name"))
    }


def filter_omitted_df(df: pd.DataFrame | None, item_column: str = "item_name") -> pd.DataFrame:
    if df is None or df.empty or item_column not in df.columns:
        return df

    omitted = get_omitted_item_names()

    if not omitted:
        return df

    mask = ~df[item_column].fillna("").astype(str).str.strip().str.lower().isin(omitted)
    return df[mask].copy()


def is_item_omitted(item_name: str | None) -> bool:
    normalized = _normalize_item_name(item_name)
    return bool(normalized and normalized in get_omitted_item_names())
