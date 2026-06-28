from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DB_NAMES = [
    "osrs_flip_scanner.db",
    "osrs_flipper.db",
    "scanner.db",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    if db_path:
        return Path(db_path).expanduser().resolve()

    base_dir = Path(__file__).resolve().parent

    for name in DEFAULT_DB_NAMES:
        candidate = base_dir / name
        if candidate.exists():
            return candidate

    return base_dir / DEFAULT_DB_NAMES[0]


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    resolved = resolve_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn



def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()

    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    """Add a column to an existing table only when it is missing.

    SQLite CREATE TABLE IF NOT EXISTS does not upgrade existing tables. The
    early 1.2.0 capital foundation created some of these tables before the
    RuneLite telemetry columns existed, so additive migrations are required.
    """

    if not _table_exists(conn, table_name):
        return

    columns = _table_columns(conn, table_name)

    if column_name in columns:
        return

    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def _run_120_schema_migrations(conn: sqlite3.Connection) -> None:
    """Apply additive 1.2.0 schema migrations before indexes are created."""

    _ensure_column(conn, "account_capital_snapshots", "inventory_gp", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "account_capital_snapshots", "bank_gp", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "account_capital_snapshots", "source_path", "TEXT")

    _ensure_column(conn, "open_trade_locks", "slot", "INTEGER")
    _ensure_column(conn, "open_trade_locks", "offer_age_minutes", "INTEGER")
    _ensure_column(conn, "open_trade_locks", "source", "TEXT NOT NULL DEFAULT 'manual'")
    _ensure_column(conn, "open_trade_locks", "source_path", "TEXT")

def ensure_capital_ai_tables(db_path: str | Path | None = None) -> Path:
    resolved = resolve_db_path(db_path)

    with connect(resolved) as conn:
        _run_120_schema_migrations(conn)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS account_capital_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                account_name TEXT NOT NULL DEFAULT 'default',
                raw_gp_available INTEGER NOT NULL,
                inventory_gp INTEGER NOT NULL DEFAULT 0,
                bank_gp INTEGER NOT NULL DEFAULT 0,
                safety_reserve_gp INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                source TEXT NOT NULL DEFAULT 'manual',
                source_path TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_account_capital_snapshots_account_created
            ON account_capital_snapshots(account_name, created_at DESC);

            CREATE TABLE IF NOT EXISTS open_trade_locks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                account_name TEXT NOT NULL DEFAULT 'default',
                item_id INTEGER,
                item_name TEXT NOT NULL,
                slot INTEGER,
                side TEXT NOT NULL DEFAULT 'unknown',
                offer_price INTEGER NOT NULL DEFAULT 0,
                quantity_total INTEGER NOT NULL DEFAULT 0,
                quantity_filled INTEGER NOT NULL DEFAULT 0,
                quantity_remaining INTEGER NOT NULL DEFAULT 0,
                gp_locked INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'open',
                opened_at TEXT,
                offer_age_minutes INTEGER,
                source TEXT NOT NULL DEFAULT 'manual',
                source_path TEXT,
                notes TEXT,
                CHECK (side IN ('buy', 'sell', 'unknown')),
                CHECK (status IN ('open', 'completed', 'cancelled', 'stuck', 'unknown'))
            );

            CREATE INDEX IF NOT EXISTS idx_open_trade_locks_account_status
            ON open_trade_locks(account_name, status, updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_open_trade_locks_item
            ON open_trade_locks(item_name, status, updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_open_trade_locks_slot
            ON open_trade_locks(account_name, slot, status);

            CREATE TABLE IF NOT EXISTS ai_suggestion_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                account_name TEXT NOT NULL DEFAULT 'default',
                item_id INTEGER,
                item_name TEXT NOT NULL,
                suggested_buy_price INTEGER,
                suggested_sell_price INTEGER,
                suggested_quantity INTEGER,
                expected_margin_gp INTEGER,
                expected_roi_pct REAL,
                expected_profit_gp INTEGER,
                recommendation_type TEXT,
                confidence TEXT,
                ai_prompt TEXT,
                ai_response TEXT,
                reason TEXT,
                source_context_json TEXT,
                usable_gp_at_suggestion INTEGER,
                raw_gp_available_at_suggestion INTEGER,
                locked_gp_at_suggestion INTEGER,
                status TEXT NOT NULL DEFAULT 'suggested'
            );

            CREATE INDEX IF NOT EXISTS idx_ai_suggestion_history_account_created
            ON ai_suggestion_history(account_name, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_ai_suggestion_history_item_created
            ON ai_suggestion_history(item_name, created_at DESC);

            CREATE TABLE IF NOT EXISTS ai_suggestion_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                suggestion_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                outcome_status TEXT NOT NULL,
                realized_buy_price INTEGER,
                realized_sell_price INTEGER,
                realized_quantity INTEGER,
                realized_profit_gp INTEGER,
                time_to_buy_min INTEGER,
                time_to_sell_min INTEGER,
                notes TEXT,
                FOREIGN KEY (suggestion_id) REFERENCES ai_suggestion_history(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_ai_suggestion_outcomes_suggestion
            ON ai_suggestion_outcomes(suggestion_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS capital_ai_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runelite_telemetry_imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                imported_at TEXT NOT NULL,
                captured_at TEXT,
                account_name TEXT NOT NULL DEFAULT 'default',
                source_path TEXT NOT NULL,
                inventory_gp INTEGER NOT NULL DEFAULT 0,
                bank_gp INTEGER NOT NULL DEFAULT 0,
                raw_gp_available INTEGER NOT NULL DEFAULT 0,
                active_offer_count INTEGER NOT NULL DEFAULT 0,
                locked_buy_gp INTEGER NOT NULL DEFAULT 0,
                locked_sell_value_gp INTEGER NOT NULL DEFAULT 0,
                usable_gp INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_runelite_telemetry_imports_account_imported
            ON runelite_telemetry_imports(account_name, imported_at DESC);
            """
        )

        defaults = {
            "low_margin_min_gp": "2",
            "low_margin_min_profit_per_slot_gp": "50000",
            "default_safety_reserve_gp": "0",
            "stuck_buy_after_minutes": "60",
            "stuck_sell_after_minutes": "180",
            "max_single_trade_pct_usable_gp": "35",
            "include_bank_gp_in_raw_available": "true",
        }

        for key, value in defaults.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO capital_ai_settings(key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, utc_now_iso()),
            )

    return resolved


def get_setting(key: str, default: str | None = None, db_path: str | Path | None = None) -> str | None:
    ensure_capital_ai_tables(db_path)

    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM capital_ai_settings WHERE key = ?",
            (key,),
        ).fetchone()

    if row:
        return str(row["value"])

    return default


def set_setting(key: str, value: str, db_path: str | Path | None = None) -> None:
    ensure_capital_ai_tables(db_path)

    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO capital_ai_settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, utc_now_iso()),
        )


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def record_capital_snapshot(
    raw_gp_available: int,
    account_name: str = "default",
    safety_reserve_gp: int | None = None,
    notes: str | None = None,
    source: str = "manual",
    source_path: str | None = None,
    inventory_gp: int | None = None,
    bank_gp: int | None = None,
    db_path: str | Path | None = None,
) -> int:
    ensure_capital_ai_tables(db_path)

    if safety_reserve_gp is None:
        safety_reserve_gp = int(get_setting("default_safety_reserve_gp", "0", db_path) or 0)

    if inventory_gp is None:
        inventory_gp = int(raw_gp_available)

    if bank_gp is None:
        bank_gp = 0

    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO account_capital_snapshots(
                created_at,
                account_name,
                raw_gp_available,
                inventory_gp,
                bank_gp,
                safety_reserve_gp,
                notes,
                source,
                source_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now_iso(),
                account_name,
                int(raw_gp_available),
                int(inventory_gp),
                int(bank_gp),
                int(safety_reserve_gp),
                notes,
                source,
                source_path,
            ),
        )

        return int(cur.lastrowid)


def latest_capital_snapshot(
    account_name: str = "default",
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_capital_ai_tables(db_path)

    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM account_capital_snapshots
            WHERE account_name = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (account_name,),
        ).fetchone()

    return dict(row) if row else None


def latest_nonzero_capital_snapshot(
    account_name: str = "default",
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_capital_ai_tables(db_path)

    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM account_capital_snapshots
            WHERE account_name = ?
              AND raw_gp_available > 0
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (account_name,),
        ).fetchone()

    return dict(row) if row else None


def record_open_trade_lock(
    item_name: str,
    side: str,
    offer_price: int,
    quantity_total: int,
    quantity_filled: int = 0,
    account_name: str = "default",
    item_id: int | None = None,
    slot: int | None = None,
    opened_at: str | None = None,
    offer_age_minutes: int | None = None,
    notes: str | None = None,
    source: str = "manual",
    source_path: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    ensure_capital_ai_tables(db_path)

    side = side.lower().strip()

    if side not in {"buy", "sell", "unknown"}:
        raise ValueError("side must be buy, sell, or unknown")

    quantity_total = max(0, int(quantity_total))
    quantity_filled = max(0, min(int(quantity_filled), quantity_total))
    quantity_remaining = max(0, quantity_total - quantity_filled)
    gp_locked = max(0, int(offer_price) * quantity_remaining)
    now = utc_now_iso()

    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO open_trade_locks(
                created_at,
                updated_at,
                account_name,
                item_id,
                item_name,
                slot,
                side,
                offer_price,
                quantity_total,
                quantity_filled,
                quantity_remaining,
                gp_locked,
                status,
                opened_at,
                offer_age_minutes,
                source,
                source_path,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                account_name,
                item_id,
                item_name,
                slot,
                side,
                int(offer_price),
                quantity_total,
                quantity_filled,
                quantity_remaining,
                gp_locked,
                opened_at or now,
                offer_age_minutes,
                source,
                source_path,
                notes,
            ),
        )

        return int(cur.lastrowid)


def replace_runelite_open_trade_locks(
    account_name: str,
    locks: list[dict[str, Any]],
    source_path: str,
    db_path: str | Path | None = None,
) -> int:
    """Replace current RuneLite-sourced open locks for an account.

    Manual locks are not touched. This lets RuneLite become the primary source
    of active GE offers while keeping manual notes/fallback entries separate.
    """

    ensure_capital_ai_tables(db_path)
    now = utc_now_iso()

    # Read these before the write transaction starts. Calling get_setting()
    # inside the write transaction can open a second SQLite connection and
    # raise sqlite3.OperationalError: database is locked.
    stuck_buy_after_minutes = int(get_setting("stuck_buy_after_minutes", "60", db_path) or 60)
    stuck_sell_after_minutes = int(get_setting("stuck_sell_after_minutes", "180", db_path) or 180)

    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE open_trade_locks
            SET status = 'completed',
                updated_at = ?,
                quantity_remaining = 0,
                gp_locked = 0
            WHERE account_name = ?
              AND source = 'runelite'
              AND status IN ('open', 'stuck', 'unknown')
            """,
            (now, account_name),
        )

        inserted = 0

        for lock in locks:
            side = str(lock.get("side") or "unknown").lower().strip()

            if side not in {"buy", "sell", "unknown"}:
                side = "unknown"

            quantity_total = max(0, int(lock.get("quantity_total") or 0))
            quantity_filled = max(0, min(int(lock.get("quantity_filled") or 0), quantity_total))
            quantity_remaining = int(lock.get("quantity_remaining") or (quantity_total - quantity_filled))
            quantity_remaining = max(0, quantity_remaining)

            if quantity_remaining <= 0 and quantity_filled <= 0:
                continue

            offer_price = max(0, int(lock.get("offer_price") or lock.get("price") or 0))
            gp_locked = max(0, offer_price * quantity_remaining)
            age_minutes = lock.get("offer_age_minutes")

            status = "open"

            if age_minutes is not None:
                age_minutes = int(age_minutes)

                if side == "buy":
                    stuck_after = stuck_buy_after_minutes
                    if age_minutes >= stuck_after:
                        status = "stuck"

                elif side == "sell":
                    stuck_after = stuck_sell_after_minutes
                    if age_minutes >= stuck_after:
                        status = "stuck"

            conn.execute(
                """
                INSERT INTO open_trade_locks(
                    created_at,
                    updated_at,
                    account_name,
                    item_id,
                    item_name,
                    slot,
                    side,
                    offer_price,
                    quantity_total,
                    quantity_filled,
                    quantity_remaining,
                    gp_locked,
                    status,
                    opened_at,
                    offer_age_minutes,
                    source,
                    source_path,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'runelite', ?, ?)
                """,
                (
                    now,
                    now,
                    account_name,
                    lock.get("item_id"),
                    str(lock.get("item_name") or "Unknown item"),
                    lock.get("slot"),
                    side,
                    offer_price,
                    quantity_total,
                    quantity_filled,
                    quantity_remaining,
                    gp_locked,
                    status,
                    lock.get("opened_at"),
                    age_minutes,
                    source_path,
                    lock.get("notes"),
                ),
            )
            inserted += 1

        return inserted


def update_open_trade_lock(
    lock_id: int,
    quantity_filled: int | None = None,
    status: str | None = None,
    notes: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    ensure_capital_ai_tables(db_path)

    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM open_trade_locks WHERE id = ?",
            (int(lock_id),),
        ).fetchone()

        if not row:
            raise ValueError(f"No open_trade_locks row found for id {lock_id}")

        new_status = status or row["status"]

        if new_status not in {"open", "completed", "cancelled", "stuck", "unknown"}:
            raise ValueError("status must be open, completed, cancelled, stuck, or unknown")

        new_quantity_filled = row["quantity_filled"] if quantity_filled is None else int(quantity_filled)
        new_quantity_filled = max(0, min(new_quantity_filled, int(row["quantity_total"])))
        quantity_remaining = max(0, int(row["quantity_total"]) - new_quantity_filled)

        if new_status in {"completed", "cancelled"}:
            quantity_remaining = 0

        gp_locked = max(0, int(row["offer_price"]) * quantity_remaining)

        conn.execute(
            """
            UPDATE open_trade_locks
            SET
                updated_at = ?,
                quantity_filled = ?,
                quantity_remaining = ?,
                gp_locked = ?,
                status = ?,
                notes = COALESCE(?, notes)
            WHERE id = ?
            """,
            (
                utc_now_iso(),
                new_quantity_filled,
                quantity_remaining,
                gp_locked,
                new_status,
                notes,
                int(lock_id),
            ),
        )


def list_open_trade_locks(
    account_name: str = "default",
    include_stuck: bool = True,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_capital_ai_tables(db_path)

    statuses = ["open", "unknown"]

    if include_stuck:
        statuses.append("stuck")

    placeholders = ",".join("?" for _ in statuses)

    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM open_trade_locks
            WHERE account_name = ?
              AND status IN ({placeholders})
            ORDER BY updated_at DESC, id DESC
            """,
            [account_name, *statuses],
        ).fetchall()

    return [dict(row) for row in rows]


def summarize_capital_state(
    account_name: str = "default",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    ensure_capital_ai_tables(db_path)

    snapshot = latest_capital_snapshot(account_name, db_path)
    locks = list_open_trade_locks(account_name, include_stuck=True, db_path=db_path)

    raw_gp = int(snapshot["raw_gp_available"]) if snapshot else 0
    inventory_gp = int(snapshot["inventory_gp"]) if snapshot and "inventory_gp" in snapshot else raw_gp
    bank_gp = int(snapshot["bank_gp"]) if snapshot and "bank_gp" in snapshot else 0
    safety_reserve = int(snapshot["safety_reserve_gp"]) if snapshot else 0

    if raw_gp <= 0:
        preserved = latest_nonzero_capital_snapshot(account_name, db_path)
        if preserved:
            raw_gp = int(preserved["raw_gp_available"])
            inventory_gp = int(preserved["inventory_gp"]) if "inventory_gp" in preserved else raw_gp
            bank_gp = int(preserved["bank_gp"]) if "bank_gp" in preserved else 0

    locked_buy_gp = sum(
        int(lock["gp_locked"])
        for lock in locks
        if lock["side"] == "buy" and lock["status"] in {"open", "stuck", "unknown"}
    )

    buy_filled_value_gp = sum(
        int(lock["offer_price"]) * int(lock["quantity_filled"])
        for lock in locks
        if lock["side"] == "buy" and lock["status"] in {"open", "stuck", "unknown"}
    )

    locked_sell_value_gp = sum(
        int(lock["gp_locked"])
        for lock in locks
        if lock["side"] == "sell" and lock["status"] in {"open", "stuck", "unknown"}
    )

    sell_filled_value_gp = sum(
        int(lock["offer_price"]) * int(lock["quantity_filled"])
        for lock in locks
        if lock["side"] == "sell" and lock["status"] in {"open", "stuck", "unknown"}
    )

    usable_gp = max(0, raw_gp - safety_reserve)
    total_tracked_locked_value_gp = locked_buy_gp + buy_filled_value_gp + locked_sell_value_gp + sell_filled_value_gp

    return {
        "account_name": account_name,
        "snapshot": snapshot,
        "raw_gp_available": raw_gp,
        "inventory_gp": inventory_gp,
        "bank_gp": bank_gp,
        "safety_reserve_gp": safety_reserve,
        "locked_buy_gp": locked_buy_gp,
        "buy_filled_value_gp": buy_filled_value_gp,
        "locked_sell_value_gp": locked_sell_value_gp,
        "sell_filled_value_gp": sell_filled_value_gp,
        "total_tracked_locked_value_gp": total_tracked_locked_value_gp,
        "usable_gp": usable_gp,
        "open_locks": locks,
        "open_lock_count": len(locks),
    }


def record_runelite_telemetry_import(
    account_name: str,
    source_path: str,
    payload: dict[str, Any],
    capital_state: dict[str, Any],
    captured_at: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    ensure_capital_ai_tables(db_path)

    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO runelite_telemetry_imports(
                imported_at,
                captured_at,
                account_name,
                source_path,
                inventory_gp,
                bank_gp,
                raw_gp_available,
                active_offer_count,
                locked_buy_gp,
                locked_sell_value_gp,
                usable_gp,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now_iso(),
                captured_at,
                account_name,
                source_path,
                int(capital_state["inventory_gp"]),
                int(capital_state["bank_gp"]),
                int(capital_state["raw_gp_available"]),
                int(capital_state["open_lock_count"]),
                int(capital_state["locked_buy_gp"]),
                int(capital_state["locked_sell_value_gp"]),
                int(capital_state["usable_gp"]),
                json.dumps(payload, sort_keys=True),
            ),
        )

        return int(cur.lastrowid)


def record_ai_suggestion(
    item_name: str,
    suggested_buy_price: int | None = None,
    suggested_sell_price: int | None = None,
    suggested_quantity: int | None = None,
    expected_margin_gp: int | None = None,
    expected_roi_pct: float | None = None,
    expected_profit_gp: int | None = None,
    recommendation_type: str | None = None,
    confidence: str | None = None,
    account_name: str = "default",
    item_id: int | None = None,
    ai_prompt: str | None = None,
    ai_response: str | None = None,
    reason: str | None = None,
    source_context: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> int:
    ensure_capital_ai_tables(db_path)
    capital = summarize_capital_state(account_name, db_path)

    if expected_margin_gp is None and suggested_buy_price is not None and suggested_sell_price is not None:
        expected_margin_gp = int(suggested_sell_price) - int(suggested_buy_price)

    if expected_profit_gp is None and expected_margin_gp is not None and suggested_quantity is not None:
        expected_profit_gp = int(expected_margin_gp) * int(suggested_quantity)

    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO ai_suggestion_history(
                created_at,
                account_name,
                item_id,
                item_name,
                suggested_buy_price,
                suggested_sell_price,
                suggested_quantity,
                expected_margin_gp,
                expected_roi_pct,
                expected_profit_gp,
                recommendation_type,
                confidence,
                ai_prompt,
                ai_response,
                reason,
                source_context_json,
                usable_gp_at_suggestion,
                raw_gp_available_at_suggestion,
                locked_gp_at_suggestion,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'suggested')
            """,
            (
                utc_now_iso(),
                account_name,
                item_id,
                item_name,
                suggested_buy_price,
                suggested_sell_price,
                suggested_quantity,
                expected_margin_gp,
                expected_roi_pct,
                expected_profit_gp,
                recommendation_type,
                confidence,
                ai_prompt,
                ai_response,
                reason,
                json.dumps(source_context or {}, sort_keys=True),
                capital["usable_gp"],
                capital["raw_gp_available"],
                capital["total_tracked_locked_value_gp"],
            ),
        )

        return int(cur.lastrowid)


def record_ai_suggestion_outcome(
    suggestion_id: int,
    outcome_status: str,
    realized_buy_price: int | None = None,
    realized_sell_price: int | None = None,
    realized_quantity: int | None = None,
    realized_profit_gp: int | None = None,
    time_to_buy_min: int | None = None,
    time_to_sell_min: int | None = None,
    notes: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    ensure_capital_ai_tables(db_path)

    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO ai_suggestion_outcomes(
                suggestion_id,
                created_at,
                outcome_status,
                realized_buy_price,
                realized_sell_price,
                realized_quantity,
                realized_profit_gp,
                time_to_buy_min,
                time_to_sell_min,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(suggestion_id),
                utc_now_iso(),
                outcome_status,
                realized_buy_price,
                realized_sell_price,
                realized_quantity,
                realized_profit_gp,
                time_to_buy_min,
                time_to_sell_min,
                notes,
            ),
        )

        conn.execute(
            "UPDATE ai_suggestion_history SET status = ? WHERE id = ?",
            (outcome_status, int(suggestion_id)),
        )

        return int(cur.lastrowid)


def get_recent_ai_suggestions(
    account_name: str = "default",
    item_name: str | None = None,
    limit: int = 25,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_capital_ai_tables(db_path)

    query = """
        SELECT
            s.*,
            (
                SELECT outcome_status
                FROM ai_suggestion_outcomes o
                WHERE o.suggestion_id = s.id
                ORDER BY o.created_at DESC, o.id DESC
                LIMIT 1
            ) AS latest_outcome_status,
            (
                SELECT realized_profit_gp
                FROM ai_suggestion_outcomes o
                WHERE o.suggestion_id = s.id
                ORDER BY o.created_at DESC, o.id DESC
                LIMIT 1
            ) AS latest_realized_profit_gp
        FROM ai_suggestion_history s
        WHERE s.account_name = ?
    """

    params: list[Any] = [account_name]

    if item_name:
        query += " AND LOWER(s.item_name) = LOWER(?)"
        params.append(item_name)

    query += " ORDER BY s.created_at DESC, s.id DESC LIMIT ?"
    params.append(int(limit))

    with connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    return [dict(row) for row in rows]


def score_flip_for_capital(
    item_name: str,
    buy_price: int,
    sell_price: int,
    proposed_quantity: int,
    account_name: str = "default",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    ensure_capital_ai_tables(db_path)

    buy_price = max(0, int(buy_price))
    sell_price = max(0, int(sell_price))
    proposed_quantity = max(0, int(proposed_quantity))
    margin = sell_price - buy_price
    required_gp = buy_price * proposed_quantity
    capital = summarize_capital_state(account_name, db_path)
    usable_gp = int(capital["usable_gp"])

    max_single_trade_pct = float(get_setting("max_single_trade_pct_usable_gp", "35", db_path) or 35)
    max_single_trade_gp = int(usable_gp * (max_single_trade_pct / 100.0))
    low_margin_min_gp = int(get_setting("low_margin_min_gp", "2", db_path) or 2)
    min_profit_per_slot = int(get_setting("low_margin_min_profit_per_slot_gp", "50000", db_path) or 50000)

    suggested_quantity = proposed_quantity

    if buy_price > 0:
        suggested_quantity = min(proposed_quantity, usable_gp // buy_price)

        if max_single_trade_gp > 0:
            suggested_quantity = min(suggested_quantity, max_single_trade_gp // buy_price)

    suggested_quantity = max(0, int(suggested_quantity))
    expected_profit = margin * suggested_quantity

    warnings: list[str] = []
    score = 100.0

    if margin <= 0:
        warnings.append("No positive raw margin.")
        score -= 90

    if margin < low_margin_min_gp:
        warnings.append(
            f"Raw margin is only {margin} GP. Low-margin flips often sit, undercut, or fail to fill."
        )
        score -= 35

    if expected_profit < min_profit_per_slot:
        warnings.append(
            f"Expected profit per GE slot is under {min_profit_per_slot:,} GP."
        )
        score -= 25

    if required_gp > usable_gp:
        warnings.append(
            f"Requested quantity needs {required_gp:,} GP but only {usable_gp:,} GP is currently usable."
        )
        score -= 20

    if suggested_quantity <= 0:
        warnings.append("No affordable quantity after locked capital and safety reserve.")
        score -= 50

    recent_same_item = get_recent_ai_suggestions(
        account_name=account_name,
        item_name=item_name,
        limit=10,
        db_path=db_path,
    )

    bad_recent = [
        row
        for row in recent_same_item
        if str(row.get("latest_outcome_status") or row.get("status") or "").lower()
        in {"failed", "stuck", "cancelled", "loss", "ignored"}
    ]

    if bad_recent:
        warnings.append(
            f"{len(bad_recent)} recent suggestion(s) for this item were marked failed, stuck, cancelled, loss, or ignored."
        )
        score -= min(30, 8 * len(bad_recent))

    score = max(0.0, min(100.0, score))

    return {
        "ok": score >= 50 and suggested_quantity > 0 and margin > 0,
        "score": score,
        "warnings": warnings,
        "suggested_quantity": suggested_quantity,
        "required_gp": buy_price * suggested_quantity,
        "usable_gp": usable_gp,
        "expected_profit_gp": expected_profit,
        "raw_margin_gp": margin,
    }


def format_gp(value: int | float | None) -> str:
    if value is None:
        return "0 GP"

    value = int(value)

    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}m GP"

    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}k GP"

    return f"{value:,} GP"


def print_capital_summary(account_name: str = "default", db_path: str | Path | None = None) -> None:
    state = summarize_capital_state(account_name, db_path)

    print("Capital Summary")
    print("=" * 64)
    print(f"Account:                  {state['account_name']}")
    print(f"Inventory GP:             {format_gp(state['inventory_gp'])}")
    print(f"Bank GP:                  {format_gp(state['bank_gp'])}")
    print(f"Raw GP available:          {format_gp(state['raw_gp_available'])}")
    print(f"Safety reserve:            {format_gp(state['safety_reserve_gp'])}")
    print(f"Waiting in open buy offers: {format_gp(state['locked_buy_gp'])}")
    print(f"Filled buy item value:     {format_gp(state.get('buy_filled_value_gp', 0))}")
    print(f"Locked sell-side value:    {format_gp(state['locked_sell_value_gp'])}")
    print(f"Filled sell GP:            {format_gp(state.get('sell_filled_value_gp', 0))}")
    print(f"Total GE value held:       {format_gp(state.get('total_tracked_locked_value_gp', 0))}")
    print(f"Usable GP:                 {format_gp(state['usable_gp'])}")
    print(f"Open tracked offers:       {state['open_lock_count']}")

    if state["open_locks"]:
        print()
        print("Open Offers / Capital Locks")
        print("-" * 64)

        for lock in state["open_locks"][:20]:
            age = lock.get("offer_age_minutes")
            age_text = f" | age {age}m" if age is not None else ""
            print(
                f"#{lock['id']} slot={lock.get('slot')} {lock['side'].upper():4} "
                f"{lock['item_name']} | "
                f"{lock['quantity_remaining']:,} remaining @ {lock['offer_price']:,} | "
                f"{format_gp(lock['gp_locked'])} | {lock['status']}{age_text}"
            )


def _cmd_init(args: argparse.Namespace) -> None:
    db_path = ensure_capital_ai_tables(args.db)
    print(f"Capital/AI memory tables are ready: {db_path}")


def _cmd_capital(args: argparse.Namespace) -> None:
    row_id = record_capital_snapshot(
        raw_gp_available=args.gp,
        account_name=args.account,
        safety_reserve_gp=args.reserve,
        notes=args.notes,
        db_path=args.db,
    )
    print(f"Recorded capital snapshot #{row_id}.")
    print_capital_summary(args.account, args.db)


def _cmd_open(args: argparse.Namespace) -> None:
    row_id = record_open_trade_lock(
        item_name=args.item,
        side=args.side,
        offer_price=args.price,
        quantity_total=args.quantity,
        quantity_filled=args.filled,
        account_name=args.account,
        notes=args.notes,
        db_path=args.db,
    )
    print(f"Recorded open trade lock #{row_id}.")
    print_capital_summary(args.account, args.db)


def _cmd_summary(args: argparse.Namespace) -> None:
    print_capital_summary(args.account, args.db)


def _cmd_score(args: argparse.Namespace) -> None:
    score = score_flip_for_capital(
        item_name=args.item,
        buy_price=args.buy,
        sell_price=args.sell,
        proposed_quantity=args.quantity,
        account_name=args.account,
        db_path=args.db,
    )

    print("Capital-Aware Candidate Score")
    print("=" * 64)
    print(f"Item:               {args.item}")
    print(f"Buy -> Sell:         {args.buy:,} -> {args.sell:,}")
    print(f"Requested quantity:  {args.quantity:,}")
    print(f"Suggested quantity:  {score['suggested_quantity']:,}")
    print(f"Required GP:         {format_gp(score['required_gp'])}")
    print(f"Usable GP:           {format_gp(score['usable_gp'])}")
    print(f"Expected profit:     {format_gp(score['expected_profit_gp'])}")
    print(f"Score:               {score['score']:.1f}/100")
    print(f"OK:                  {score['ok']}")

    if score["warnings"]:
        print()
        print("Warnings")
        print("-" * 64)

        for warning in score["warnings"]:
            print(f"- {warning}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OSRSFlipper capital-aware AI memory helper")
    parser.add_argument("--db", help="Optional SQLite database path")

    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create capital/AI memory tables")
    init.set_defaults(func=_cmd_init)

    capital = sub.add_parser("capital", help="Record current raw GP available")
    capital.add_argument("--gp", type=int, required=True, help="Raw GP currently available")
    capital.add_argument("--reserve", type=int, default=None, help="Safety reserve to keep unallocated")
    capital.add_argument("--account", default="default")
    capital.add_argument("--notes")
    capital.set_defaults(func=_cmd_capital)

    open_trade = sub.add_parser("open", help="Record an open trade/capital lock")
    open_trade.add_argument("--item", required=True)
    open_trade.add_argument("--side", choices=["buy", "sell", "unknown"], required=True)
    open_trade.add_argument("--price", type=int, required=True)
    open_trade.add_argument("--quantity", type=int, required=True)
    open_trade.add_argument("--filled", type=int, default=0)
    open_trade.add_argument("--account", default="default")
    open_trade.add_argument("--notes")
    open_trade.set_defaults(func=_cmd_open)

    summary = sub.add_parser("summary", help="Show capital summary")
    summary.add_argument("--account", default="default")
    summary.set_defaults(func=_cmd_summary)

    score = sub.add_parser("score", help="Score a candidate flip against available capital")
    score.add_argument("--item", required=True)
    score.add_argument("--buy", type=int, required=True)
    score.add_argument("--sell", type=int, required=True)
    score.add_argument("--quantity", type=int, required=True)
    score.add_argument("--account", default="default")
    score.set_defaults(func=_cmd_score)

    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
