from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_NAMES = ["osrs_flip_scanner.db", "osrs_flipper.db", "scanner.db"]


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


def ensure_capital_ai_tables(db_path: str | Path | None = None) -> Path:
    resolved = resolve_db_path(db_path)
    with connect(resolved) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS account_capital_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                account_name TEXT NOT NULL DEFAULT 'default',
                raw_gp_available INTEGER NOT NULL,
                safety_reserve_gp INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                source TEXT NOT NULL DEFAULT 'manual'
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
                side TEXT NOT NULL DEFAULT 'unknown',
                offer_price INTEGER NOT NULL DEFAULT 0,
                quantity_total INTEGER NOT NULL DEFAULT 0,
                quantity_filled INTEGER NOT NULL DEFAULT 0,
                quantity_remaining INTEGER NOT NULL DEFAULT 0,
                gp_locked INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'open',
                opened_at TEXT,
                notes TEXT,
                CHECK (side IN ('buy', 'sell', 'unknown')),
                CHECK (status IN ('open', 'completed', 'cancelled', 'stuck', 'unknown'))
            );
            CREATE INDEX IF NOT EXISTS idx_open_trade_locks_account_status
            ON open_trade_locks(account_name, status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_open_trade_locks_item
            ON open_trade_locks(item_name, status, updated_at DESC);

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
            """
        )
        defaults = {
            "low_margin_min_gp": "2",
            "low_margin_min_profit_per_slot_gp": "50000",
            "default_safety_reserve_gp": "0",
            "stuck_buy_after_minutes": "60",
            "stuck_sell_after_minutes": "180",
            "max_single_trade_pct_usable_gp": "35",
        }
        for key, value in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO capital_ai_settings(key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, utc_now_iso()),
            )
    return resolved


def get_setting(key: str, default: str = "", db_path: str | Path | None = None) -> str:
    ensure_capital_ai_tables(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT value FROM capital_ai_settings WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else default


def set_setting(key: str, value: str, db_path: str | Path | None = None) -> None:
    ensure_capital_ai_tables(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO capital_ai_settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, utc_now_iso()),
        )


def record_capital_snapshot(raw_gp_available: int, account_name: str = "default", safety_reserve_gp: int | None = None, notes: str | None = None, source: str = "manual", db_path: str | Path | None = None) -> int:
    ensure_capital_ai_tables(db_path)
    if safety_reserve_gp is None:
        safety_reserve_gp = int(get_setting("default_safety_reserve_gp", "0", db_path) or 0)
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO account_capital_snapshots(created_at, account_name, raw_gp_available, safety_reserve_gp, notes, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (utc_now_iso(), account_name, int(raw_gp_available), int(safety_reserve_gp), notes, source),
        )
        return int(cur.lastrowid)


def latest_capital_snapshot(account_name: str = "default", db_path: str | Path | None = None) -> dict[str, Any] | None:
    ensure_capital_ai_tables(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM account_capital_snapshots
            WHERE account_name = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (account_name,),
        ).fetchone()
    return dict(row) if row else None


def record_open_trade_lock(item_name: str, side: str, offer_price: int, quantity_total: int, quantity_filled: int = 0, account_name: str = "default", item_id: int | None = None, opened_at: str | None = None, notes: str | None = None, db_path: str | Path | None = None) -> int:
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
            INSERT INTO open_trade_locks(created_at, updated_at, account_name, item_id, item_name, side, offer_price, quantity_total, quantity_filled, quantity_remaining, gp_locked, status, opened_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (now, now, account_name, item_id, item_name, side, int(offer_price), quantity_total, quantity_filled, quantity_remaining, gp_locked, opened_at or now, notes),
        )
        return int(cur.lastrowid)


def update_open_trade_lock(lock_id: int, quantity_filled: int | None = None, status: str | None = None, notes: str | None = None, db_path: str | Path | None = None) -> None:
    ensure_capital_ai_tables(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM open_trade_locks WHERE id = ?", (int(lock_id),)).fetchone()
        if not row:
            raise ValueError(f"No open_trade_locks row found for id {lock_id}")
        new_status = status or row["status"]
        if new_status not in {"open", "completed", "cancelled", "stuck", "unknown"}:
            raise ValueError("status must be open, completed, cancelled, stuck, or unknown")
        new_filled = row["quantity_filled"] if quantity_filled is None else int(quantity_filled)
        new_filled = max(0, min(new_filled, int(row["quantity_total"])))
        remaining = max(0, int(row["quantity_total"]) - new_filled)
        if new_status in {"completed", "cancelled"}:
            remaining = 0
        locked = max(0, int(row["offer_price"]) * remaining)
        conn.execute(
            """
            UPDATE open_trade_locks
            SET updated_at = ?, quantity_filled = ?, quantity_remaining = ?, gp_locked = ?, status = ?, notes = COALESCE(?, notes)
            WHERE id = ?
            """,
            (utc_now_iso(), new_filled, remaining, locked, new_status, notes, int(lock_id)),
        )


def list_open_trade_locks(account_name: str = "default", include_stuck: bool = True, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    ensure_capital_ai_tables(db_path)
    statuses = ["open", "unknown"] + (["stuck"] if include_stuck else [])
    placeholders = ",".join("?" for _ in statuses)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM open_trade_locks WHERE account_name = ? AND status IN ({placeholders}) ORDER BY updated_at DESC, id DESC",
            [account_name, *statuses],
        ).fetchall()
    return [dict(row) for row in rows]


def summarize_capital_state(account_name: str = "default", db_path: str | Path | None = None) -> dict[str, Any]:
    ensure_capital_ai_tables(db_path)
    snapshot = latest_capital_snapshot(account_name, db_path)
    locks = list_open_trade_locks(account_name, True, db_path)
    raw_gp = int(snapshot["raw_gp_available"]) if snapshot else 0
    reserve = int(snapshot["safety_reserve_gp"]) if snapshot else 0
    locked_buy = sum(int(lock["gp_locked"]) for lock in locks if lock["side"] == "buy")
    locked_sell_value = sum(int(lock["gp_locked"]) for lock in locks if lock["side"] == "sell")
    usable = max(0, raw_gp - reserve - locked_buy)
    return {
        "account_name": account_name,
        "snapshot": snapshot,
        "raw_gp_available": raw_gp,
        "safety_reserve_gp": reserve,
        "locked_buy_gp": locked_buy,
        "locked_sell_value_gp": locked_sell_value,
        "total_tracked_locked_value_gp": locked_buy + locked_sell_value,
        "usable_gp": usable,
        "open_locks": locks,
        "open_lock_count": len(locks),
    }


def record_ai_suggestion(item_name: str, suggested_buy_price: int | None = None, suggested_sell_price: int | None = None, suggested_quantity: int | None = None, expected_margin_gp: int | None = None, expected_roi_pct: float | None = None, expected_profit_gp: int | None = None, recommendation_type: str | None = None, confidence: str | None = None, account_name: str = "default", item_id: int | None = None, ai_prompt: str | None = None, ai_response: str | None = None, reason: str | None = None, source_context: dict[str, Any] | None = None, db_path: str | Path | None = None) -> int:
    ensure_capital_ai_tables(db_path)
    capital = summarize_capital_state(account_name, db_path)
    if expected_margin_gp is None and suggested_buy_price is not None and suggested_sell_price is not None:
        expected_margin_gp = int(suggested_sell_price) - int(suggested_buy_price)
    if expected_profit_gp is None and expected_margin_gp is not None and suggested_quantity is not None:
        expected_profit_gp = int(expected_margin_gp) * int(suggested_quantity)
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO ai_suggestion_history(created_at, account_name, item_id, item_name, suggested_buy_price, suggested_sell_price, suggested_quantity, expected_margin_gp, expected_roi_pct, expected_profit_gp, recommendation_type, confidence, ai_prompt, ai_response, reason, source_context_json, usable_gp_at_suggestion, raw_gp_available_at_suggestion, locked_gp_at_suggestion, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'suggested')
            """,
            (utc_now_iso(), account_name, item_id, item_name, suggested_buy_price, suggested_sell_price, suggested_quantity, expected_margin_gp, expected_roi_pct, expected_profit_gp, recommendation_type, confidence, ai_prompt, ai_response, reason, json.dumps(source_context or {}, sort_keys=True), capital["usable_gp"], capital["raw_gp_available"], capital["total_tracked_locked_value_gp"]),
        )
        return int(cur.lastrowid)


def record_ai_suggestion_outcome(suggestion_id: int, outcome_status: str, realized_buy_price: int | None = None, realized_sell_price: int | None = None, realized_quantity: int | None = None, realized_profit_gp: int | None = None, time_to_buy_min: int | None = None, time_to_sell_min: int | None = None, notes: str | None = None, db_path: str | Path | None = None) -> int:
    ensure_capital_ai_tables(db_path)
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO ai_suggestion_outcomes(suggestion_id, created_at, outcome_status, realized_buy_price, realized_sell_price, realized_quantity, realized_profit_gp, time_to_buy_min, time_to_sell_min, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (int(suggestion_id), utc_now_iso(), outcome_status, realized_buy_price, realized_sell_price, realized_quantity, realized_profit_gp, time_to_buy_min, time_to_sell_min, notes),
        )
        conn.execute("UPDATE ai_suggestion_history SET status = ? WHERE id = ?", (outcome_status, int(suggestion_id)))
        return int(cur.lastrowid)


def get_recent_ai_suggestions(account_name: str = "default", item_name: str | None = None, limit: int = 25, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    ensure_capital_ai_tables(db_path)
    query = """
        SELECT s.*,
               (SELECT outcome_status FROM ai_suggestion_outcomes o WHERE o.suggestion_id = s.id ORDER BY o.created_at DESC, o.id DESC LIMIT 1) AS latest_outcome_status,
               (SELECT realized_profit_gp FROM ai_suggestion_outcomes o WHERE o.suggestion_id = s.id ORDER BY o.created_at DESC, o.id DESC LIMIT 1) AS latest_realized_profit_gp
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


def score_flip_for_capital(item_name: str, buy_price: int, sell_price: int, proposed_quantity: int, account_name: str = "default", db_path: str | Path | None = None) -> dict[str, Any]:
    ensure_capital_ai_tables(db_path)
    buy_price, sell_price, proposed_quantity = max(0, int(buy_price)), max(0, int(sell_price)), max(0, int(proposed_quantity))
    margin = sell_price - buy_price
    capital = summarize_capital_state(account_name, db_path)
    usable = int(capital["usable_gp"])
    max_pct = float(get_setting("max_single_trade_pct_usable_gp", "35", db_path) or 35) / 100.0
    max_trade_gp = int(usable * max_pct)
    suggested_qty = proposed_quantity
    if buy_price > 0:
        suggested_qty = min(proposed_quantity, usable // buy_price, max_trade_gp // buy_price if max_trade_gp > 0 else proposed_quantity)
    suggested_qty = max(0, suggested_qty)
    expected_profit = margin * suggested_qty
    warnings = []
    score = 100.0
    min_margin = int(get_setting("low_margin_min_gp", "2", db_path) or 2)
    min_slot_profit = int(get_setting("low_margin_min_profit_per_slot_gp", "50000", db_path) or 50000)
    if margin <= 0:
        warnings.append("No positive raw margin."); score -= 90
    if margin < min_margin:
        warnings.append(f"Raw margin is only {margin} GP. Low-margin flips often sit, undercut, or fail to fill."); score -= 35
    if expected_profit < min_slot_profit:
        warnings.append(f"Expected profit per GE slot is under {min_slot_profit:,} GP."); score -= 25
    if buy_price * proposed_quantity > usable:
        warnings.append(f"Requested quantity needs {buy_price * proposed_quantity:,} GP but only {usable:,} GP is currently usable."); score -= 20
    if suggested_qty <= 0:
        warnings.append("No affordable quantity after locked capital and safety reserve."); score -= 50
    recent = get_recent_ai_suggestions(account_name, item_name, 10, db_path)
    bad = [r for r in recent if str(r.get("latest_outcome_status") or r.get("status") or "").lower() in {"failed", "stuck", "cancelled", "loss", "ignored"}]
    if bad:
        warnings.append(f"{len(bad)} recent suggestion(s) for this item were marked failed, stuck, cancelled, loss, or ignored."); score -= min(30, 8 * len(bad))
    score = max(0.0, min(100.0, score))
    return {"ok": score >= 50 and suggested_qty > 0 and margin > 0, "score": score, "warnings": warnings, "suggested_quantity": suggested_qty, "required_gp": buy_price * suggested_qty, "usable_gp": usable, "expected_profit_gp": expected_profit, "raw_margin_gp": margin}


def format_gp(value: int | float | None) -> str:
    value = int(value or 0)
    if abs(value) >= 1_000_000: return f"{value / 1_000_000:.2f}m GP"
    if abs(value) >= 1_000: return f"{value / 1_000:.1f}k GP"
    return f"{value:,} GP"


def print_capital_summary(account_name: str = "default", db_path: str | Path | None = None) -> None:
    s = summarize_capital_state(account_name, db_path)
    print("Capital Summary")
    print("=" * 64)
    print(f"Account:                  {s['account_name']}")
    print(f"Raw GP available:          {format_gp(s['raw_gp_available'])}")
    print(f"Safety reserve:            {format_gp(s['safety_reserve_gp'])}")
    print(f"Locked in open buy offers: {format_gp(s['locked_buy_gp'])}")
    print(f"Locked sell-side value:    {format_gp(s['locked_sell_value_gp'])}")
    print(f"Usable GP:                 {format_gp(s['usable_gp'])}")
    print(f"Open tracked locks:        {s['open_lock_count']}")
    for lock in s["open_locks"][:20]:
        print(f"#{lock['id']} {lock['side'].upper():4} {lock['item_name']} | {lock['quantity_remaining']:,} @ {lock['offer_price']:,} | {format_gp(lock['gp_locked'])} | {lock['status']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="OSRSFlipper capital-aware AI memory helper")
    parser.add_argument("--db")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init").set_defaults(func=lambda a: print(f"Capital/AI memory tables are ready: {ensure_capital_ai_tables(a.db)}"))
    capital = sub.add_parser("capital"); capital.add_argument("--gp", type=int, required=True); capital.add_argument("--reserve", type=int, default=None); capital.add_argument("--account", default="default"); capital.add_argument("--notes"); capital.set_defaults(func=lambda a: (print(f"Recorded capital snapshot #{record_capital_snapshot(a.gp, a.account, a.reserve, a.notes, db_path=a.db)}"), print_capital_summary(a.account, a.db)))
    openp = sub.add_parser("open"); openp.add_argument("--item", required=True); openp.add_argument("--side", choices=["buy", "sell", "unknown"], required=True); openp.add_argument("--price", type=int, required=True); openp.add_argument("--quantity", type=int, required=True); openp.add_argument("--filled", type=int, default=0); openp.add_argument("--account", default="default"); openp.add_argument("--notes"); openp.set_defaults(func=lambda a: (print(f"Recorded open trade lock #{record_open_trade_lock(a.item, a.side, a.price, a.quantity, a.filled, a.account, notes=a.notes, db_path=a.db)}"), print_capital_summary(a.account, a.db)))
    update = sub.add_parser("update-open"); update.add_argument("--id", type=int, required=True); update.add_argument("--filled", type=int); update.add_argument("--status", choices=["open", "completed", "cancelled", "stuck", "unknown"]); update.add_argument("--account", default="default"); update.add_argument("--notes"); update.set_defaults(func=lambda a: (update_open_trade_lock(a.id, a.filled, a.status, a.notes, a.db), print_capital_summary(a.account, a.db)))
    summary = sub.add_parser("summary"); summary.add_argument("--account", default="default"); summary.set_defaults(func=lambda a: print_capital_summary(a.account, a.db))
    scorep = sub.add_parser("score"); scorep.add_argument("--item", required=True); scorep.add_argument("--buy", type=int, required=True); scorep.add_argument("--sell", type=int, required=True); scorep.add_argument("--quantity", type=int, required=True); scorep.add_argument("--account", default="default"); scorep.set_defaults(func=lambda a: print(json.dumps(score_flip_for_capital(a.item, a.buy, a.sell, a.quantity, a.account, a.db), indent=2)))
    sugg = sub.add_parser("suggestions"); sugg.add_argument("--account", default="default"); sugg.add_argument("--item"); sugg.add_argument("--limit", type=int, default=25); sugg.set_defaults(func=lambda a: print(json.dumps(get_recent_ai_suggestions(a.account, a.item, a.limit, a.db), indent=2, default=str)))
    args = parser.parse_args(); result = args.func(args)
    return 0 if result is None or isinstance(result, tuple) else int(result)


if __name__ == "__main__":
    raise SystemExit(main())
