from __future__ import annotations

import sqlite3
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from account_context import BASE_DIR, get_account_scope


DB_FILE = Path(BASE_DIR) / "osrs_flip_scanner.db"
SQLITE_TIMEOUT_SECONDS = 30
SQLITE_BUSY_TIMEOUT_MS = 30000
OVERNIGHT_INTENT = "overnight"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_utc_text() -> str:
    return _now_utc().isoformat()


def _default_overnight_expires_at() -> str:
    local_now = datetime.now().astimezone()
    tomorrow = local_now.date() + timedelta(days=1)
    local_expiry = datetime.combine(tomorrow, time(hour=12), tzinfo=local_now.tzinfo)
    return local_expiry.astimezone(timezone.utc).isoformat()


def _normalize_item_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _safe_int(value: Any, default: int = 0) -> int:
    text = str(value or "").strip().replace(",", "").replace("gp", "").strip()

    try:
        return int(float(text))
    except Exception:
        return default


def _offer_price(row: dict[str, Any]) -> int:
    side = str(row.get("Side") or "").strip().lower()

    if side == "buy":
        return _safe_int(row.get("Buy Price") or row.get("Buy"))

    if side == "sell":
        return _safe_int(row.get("Sell Price") or row.get("Sell"))

    return _safe_int(row.get("Price") or row.get("Buy Price") or row.get("Sell Price"))


def _offer_slot(row: dict[str, Any]) -> str:
    value = row.get("Slot")
    if value in (None, ""):
        return ""
    return str(value).strip()


def _offer_side(row: dict[str, Any]) -> str:
    return str(row.get("Side") or "").strip().lower()


def _offer_item(row: dict[str, Any]) -> str:
    return str(row.get("Item") or "").strip()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    return conn


def init_offer_intents_db() -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS offer_intents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_username TEXT NOT NULL,
            osrs_account_name TEXT NOT NULL,
            item_name TEXT NOT NULL,
            normalized_item_name TEXT NOT NULL,
            side TEXT NOT NULL,
            slot TEXT,
            price INTEGER,
            intent TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            cleared_at TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_offer_intents_account_active
        ON offer_intents(app_username, osrs_account_name, cleared_at, expires_at)
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_offer_intents_offer_match
        ON offer_intents(
            app_username,
            osrs_account_name,
            normalized_item_name,
            side,
            slot,
            price,
            cleared_at
        )
        """
    )

    conn.commit()
    conn.close()


def _base_match_where(row: dict[str, Any]) -> tuple[str, list[Any]]:
    scope = get_account_scope()
    item_name = _offer_item(row)
    normalized = _normalize_item_name(item_name)
    side = _offer_side(row)
    slot = _offer_slot(row)
    price = _offer_price(row)

    where = """
        app_username = ?
        AND osrs_account_name = ?
        AND normalized_item_name = ?
        AND side = ?
        AND cleared_at IS NULL
    """
    params: list[Any] = [
        scope["app_username"],
        scope["osrs_account_name"],
        normalized,
        side,
    ]

    if slot:
        where += " AND slot = ?"
        params.append(slot)

    if price > 0:
        where += " AND price = ?"
        params.append(price)

    return where, params


def mark_offer_overnight(row: dict[str, Any], note: str | None = None) -> dict[str, Any]:
    init_offer_intents_db()
    item_name = _offer_item(row)
    normalized = _normalize_item_name(item_name)
    side = _offer_side(row)

    if not normalized or not side:
        raise ValueError("Select a current offer row first.")

    expires_at = _default_overnight_expires_at()
    clear_offer_intent(row)

    scope = get_account_scope()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO offer_intents (
            app_username,
            osrs_account_name,
            item_name,
            normalized_item_name,
            side,
            slot,
            price,
            intent,
            note,
            created_at,
            expires_at,
            cleared_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            scope["app_username"],
            scope["osrs_account_name"],
            item_name,
            normalized,
            side,
            _offer_slot(row),
            _offer_price(row),
            OVERNIGHT_INTENT,
            str(note or "Marked from Flip Plan").strip(),
            _now_utc_text(),
            expires_at,
        ),
    )

    conn.commit()
    conn.close()

    return {
        "item_name": item_name,
        "side": side,
        "intent": OVERNIGHT_INTENT,
        "expires_at": expires_at,
    }


def clear_offer_intent(row: dict[str, Any]) -> int:
    init_offer_intents_db()
    where, params = _base_match_where(row)
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        f"""
        UPDATE offer_intents
        SET cleared_at = ?
        WHERE {where}
        """,
        [_now_utc_text(), *params],
    )

    count = int(cursor.rowcount or 0)
    conn.commit()
    conn.close()
    return count


def get_offer_intent(row: dict[str, Any]) -> dict[str, Any] | None:
    init_offer_intents_db()
    where, params = _base_match_where(row)
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        f"""
        SELECT
            id,
            item_name,
            side,
            slot,
            price,
            intent,
            note,
            created_at,
            expires_at
        FROM offer_intents
        WHERE {where}
          AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        [*params, _now_utc_text()],
    )

    record = cursor.fetchone()
    conn.close()
    return dict(record) if record else None
