import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from account_context import BASE_DIR as APP_BASE_DIR, get_account_scope

BASE_DIR = str(APP_BASE_DIR)
DB_FILE = os.path.join(BASE_DIR, "osrs_flip_scanner.db")

RUNELITE_STATE_PATH = Path(APP_BASE_DIR) / "runtime" / "runelite_state.json"

GE_SLOT_COUNT = 8

# GE tax settings used for estimates only.
GE_TAX_RATE = 0.02
GE_TAX_CAP_PER_ITEM = 5_000_000

# Stale-position rules for AI context.
STALE_BUY_OFFER_HOURS = 6
STALE_SELL_OFFER_HOURS = 12
STALE_OVERNIGHT_HOURS = 24
STALE_CRITICAL_HOURS = 48

# Loss acceptance guardrails.
MAX_SMALL_LOSS_PERCENT = 2.0
MAX_MEDIUM_LOSS_PERCENT = 5.0


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    return sqlite3.connect(DB_FILE)


def table_exists(cursor, table_name):
    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
    """, (table_name,))

    return cursor.fetchone() is not None


def init_ai_trade_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_trade_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_username TEXT NOT NULL DEFAULT 'default',
            osrs_account_name TEXT NOT NULL DEFAULT 'default',
            created_at TEXT NOT NULL,
            title TEXT NOT NULL,
            feedback TEXT NOT NULL,
            tags TEXT
        )
    """)

    # Migrate existing ai_trade_notes table.
    cursor.execute("PRAGMA table_info(ai_trade_notes)")
    note_columns = [row[1] for row in cursor.fetchall()]

    if "app_username" not in note_columns:
        cursor.execute("ALTER TABLE ai_trade_notes ADD COLUMN app_username TEXT NOT NULL DEFAULT 'default'")

    if "osrs_account_name" not in note_columns:
        cursor.execute("ALTER TABLE ai_trade_notes ADD COLUMN osrs_account_name TEXT NOT NULL DEFAULT 'default'")

    scope = get_account_scope()

    cursor.execute("""
        UPDATE ai_trade_notes
        SET app_username = ?,
            osrs_account_name = ?
        WHERE app_username = 'default'
          AND osrs_account_name = 'default'
    """, (
        scope["app_username"],
        scope["osrs_account_name"]
    ))

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_ai_trade_notes_account_created_at
        ON ai_trade_notes(app_username, osrs_account_name, created_at)
    """)

    conn.commit()
    conn.close()


def safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(float(value))
    except Exception:
        return default


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def format_gp(value):
    value = safe_int(value)
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,} gp"


def format_percent(value):
    value = safe_float(value)
    return f"{value:.2f}%"


def parse_datetime(value):
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    if text.replace(".", "", 1).isdigit():
        number = float(text)

        if number > 10_000_000_000:
            number = number / 1000

        return datetime.fromtimestamp(number, timezone.utc)

    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        parsed = datetime.fromisoformat(text)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except Exception:
        return None


def hours_since(value):
    parsed = parse_datetime(value)

    if parsed is None:
        return None

    delta = datetime.now(timezone.utc) - parsed
    return max(delta.total_seconds() / 3600, 0)


def ge_tax_per_item(sell_price):
    sell_price = safe_int(sell_price)

    if sell_price <= 0:
        return 0

    return min(int(sell_price * GE_TAX_RATE), GE_TAX_CAP_PER_ITEM)


def save_ai_feedback(title, feedback, tags="advisor"):
    init_ai_trade_db()

    title = str(title or "AI trade feedback").strip()
    feedback = str(feedback or "").strip()
    tags = str(tags or "").strip()

    if not feedback:
        return None

    scope = get_account_scope()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO ai_trade_notes (
            app_username,
            osrs_account_name,
            created_at,
            title,
            feedback,
            tags
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        scope["app_username"],
        scope["osrs_account_name"],
        now_utc(),
        title,
        feedback,
        tags
    ))

    note_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return note_id


def get_recent_ai_feedback(limit=5, max_chars=3500):
    init_ai_trade_db()

    scope = get_account_scope()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT created_at, title, feedback, tags
        FROM ai_trade_notes
        WHERE app_username = ?
          AND osrs_account_name = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
    """, (
        scope["app_username"],
        scope["osrs_account_name"],
        limit
    ))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return "No previous AI trade feedback has been saved yet."

    parts = []

    for created_at, title, feedback, tags in rows:
        clean_feedback = str(feedback or "").strip()

        if len(clean_feedback) > 700:
            clean_feedback = clean_feedback[:700].rstrip() + "..."

        parts.append(
            f"- {created_at} | {title} | tags: {tags or 'none'}\n"
            f"  Feedback: {clean_feedback}"
        )

    text = "\n".join(parts)

    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n..."

    return text


def get_completed_trade_summary(cursor, since_iso=None):
    scope = get_account_scope()

    where_parts = [
        "app_username = ?",
        "osrs_account_name = ?"
    ]

    params = [
        scope["app_username"],
        scope["osrs_account_name"]
    ]

    if since_iso:
        where_parts.append("sell_time >= ?")
        params.append(since_iso)

    where_clause = "WHERE " + " AND ".join(where_parts)

    cursor.execute(f"""
        SELECT
            COUNT(*) AS completed_count,
            COALESCE(SUM(total_profit), 0) AS total_profit,
            COALESCE(AVG(roi_percent), 0) AS avg_roi,
            COALESCE(MAX(total_profit), 0) AS best_trade,
            COALESCE(MIN(total_profit), 0) AS worst_trade,
            COALESCE(SUM(CASE WHEN total_profit > 0 THEN 1 ELSE 0 END), 0) AS wins,
            COALESCE(SUM(CASE WHEN total_profit < 0 THEN 1 ELSE 0 END), 0) AS losses,
            COALESCE(AVG(net_profit_each), 0) AS avg_net_each
        FROM completed_trades
        {where_clause}
    """, params)

    row = cursor.fetchone()

    if row is None:
        return {
            "completed_count": 0,
            "total_profit": 0,
            "avg_roi": 0.0,
            "best_trade": 0,
            "worst_trade": 0,
            "wins": 0,
            "losses": 0,
            "avg_net_each": 0
        }

    return {
        "completed_count": safe_int(row[0]),
        "total_profit": safe_int(row[1]),
        "avg_roi": safe_float(row[2]),
        "best_trade": safe_int(row[3]),
        "worst_trade": safe_int(row[4]),
        "wins": safe_int(row[5]),
        "losses": safe_int(row[6]),
        "avg_net_each": safe_float(row[7])
    }

def get_item_performance(cursor, since_iso=None, limit=15):
    scope = get_account_scope()

    where_parts = [
        "app_username = ?",
        "osrs_account_name = ?"
    ]

    params = [
        scope["app_username"],
        scope["osrs_account_name"]
    ]

    if since_iso:
        where_parts.append("sell_time >= ?")
        params.append(since_iso)

    where_clause = "WHERE " + " AND ".join(where_parts)
    params.append(limit)

    cursor.execute(f"""
        SELECT
            item_name,
            COUNT(*) AS flips,
            COALESCE(SUM(quantity), 0) AS total_qty,
            COALESCE(SUM(total_profit), 0) AS item_profit,
            COALESCE(AVG(roi_percent), 0) AS avg_roi,
            COALESCE(AVG(net_profit_each), 0) AS avg_net_each,
            COALESCE(MIN(total_profit), 0) AS worst_trade,
            COALESCE(MAX(total_profit), 0) AS best_trade
        FROM completed_trades
        {where_clause}
        GROUP BY item_id, item_name
        ORDER BY item_profit DESC
        LIMIT ?
    """, params)

    return cursor.fetchall()

def get_worst_items(cursor, since_iso=None, limit=10):
    scope = get_account_scope()

    where_parts = [
        "app_username = ?",
        "osrs_account_name = ?"
    ]

    params = [
        scope["app_username"],
        scope["osrs_account_name"]
    ]

    if since_iso:
        where_parts.append("sell_time >= ?")
        params.append(since_iso)

    where_clause = "WHERE " + " AND ".join(where_parts)
    params.append(limit)

    cursor.execute(f"""
        SELECT
            item_name,
            COUNT(*) AS flips,
            COALESCE(SUM(total_profit), 0) AS item_profit,
            COALESCE(AVG(roi_percent), 0) AS avg_roi,
            COALESCE(MIN(total_profit), 0) AS worst_trade
        FROM completed_trades
        {where_clause}
        GROUP BY item_id, item_name
        HAVING item_profit < 0
        ORDER BY item_profit ASC
        LIMIT ?
    """, params)

    return cursor.fetchall()

def get_recent_completed(cursor, limit=20):
    scope = get_account_scope()

    cursor.execute("""
        SELECT
            sell_time,
            item_name,
            quantity,
            buy_price_each,
            sell_price_each,
            raw_margin_each,
            tax_each,
            net_profit_each,
            total_profit,
            roi_percent
        FROM completed_trades
        WHERE app_username = ?
          AND osrs_account_name = ?
        ORDER BY sell_time DESC, id DESC
        LIMIT ?
    """, (
        scope["app_username"],
        scope["osrs_account_name"],
        limit
    ))

    return cursor.fetchall()

def get_unmatched_inventory_rows(cursor, limit=20):
    """
    Local unmatched buys are a ledger/inventory estimate only.

    IMPORTANT:
    These rows are NOT current GE slots and should never be described as
    currently buying/selling unless the live OSRSFlipper RuneLite telemetry lastOffers section also
    shows the item in BUYING or SELLING state.
    """
    scope = get_account_scope()

    cursor.execute("""
        SELECT
            traded_at,
            item_id,
            item_name,
            price_each,
            remaining_quantity,
            price_each * remaining_quantity AS open_value,
            source,
            status
        FROM trade_events
        WHERE app_username = ?
          AND osrs_account_name = ?
          AND side = 'BUY'
          AND remaining_quantity > 0
        ORDER BY open_value DESC, traded_at DESC
        LIMIT ?
    """, (
        scope["app_username"],
        scope["osrs_account_name"],
        limit
    ))

    return cursor.fetchall()

def get_unmatched_inventory_summary(cursor):
    scope = get_account_scope()

    cursor.execute("""
        SELECT
            COUNT(*) AS unmatched_count,
            COALESCE(SUM(price_each * remaining_quantity), 0) AS unmatched_value,
            COALESCE(MAX(price_each * remaining_quantity), 0) AS largest_unmatched
        FROM trade_events
        WHERE app_username = ?
          AND osrs_account_name = ?
          AND side = 'BUY'
          AND remaining_quantity > 0
    """, (
        scope["app_username"],
        scope["osrs_account_name"]
    ))

    row = cursor.fetchone()

    if row is None:
        return {
            "unmatched_count": 0,
            "unmatched_value": 0,
            "largest_unmatched": 0
        }

    return {
        "unmatched_count": safe_int(row[0]),
        "unmatched_value": safe_int(row[1]),
        "largest_unmatched": safe_int(row[2])
    }

def get_latest_market_exit_estimate(cursor, item_id, item_name):
    if not table_exists(cursor, "scan_results"):
        return None

    params = []
    where = ""

    if item_id is not None:
        where = "sr.item_id = ?"
        params.append(item_id)
    else:
        where = "LOWER(sr.item_name) = LOWER(?)"
        params.append(item_name)

    cursor.execute(f"""
        SELECT
            sr.item_id,
            sr.item_name,
            sr.target_buy,
            sr.target_sell,
            sr.avg_low,
            sr.avg_high,
            sr.price_warning,
            sr.market_context_warning,
            sr.trend_warning,
            sr.market_momentum,
            sr.daily_trend,
            sr.weekly_trend,
            sr.long_term_trend,
            sr.expected_fill_hours,
            sr.liquidity_score,
            sr.window_name,
            sr.scanned_at
        FROM scan_results sr
        WHERE sr.run_id = (
            SELECT MAX(run_id)
            FROM scan_results
        )
          AND {where}
        ORDER BY
            sr.liquidity_score DESC,
            sr.expected_fill_hours ASC,
            sr.window_rank ASC
        LIMIT 1
    """, params)

    row = cursor.fetchone()

    if not row:
        return None

    (
        market_item_id,
        market_item_name,
        target_buy,
        target_sell,
        avg_low,
        avg_high,
        price_warning,
        market_context_warning,
        trend_warning,
        market_momentum,
        daily_trend,
        weekly_trend,
        long_term_trend,
        expected_fill_hours,
        liquidity_score,
        window_name,
        scanned_at
    ) = row

    target_buy = safe_int(target_buy)
    target_sell = safe_int(target_sell)
    avg_low = safe_int(avg_low)
    avg_high = safe_int(avg_high)

    fast_exit_price = target_buy or avg_low or target_sell or avg_high
    patient_exit_price = target_sell or avg_high or fast_exit_price

    return {
        "item_id": market_item_id,
        "item_name": market_item_name,
        "fast_exit_price": fast_exit_price,
        "patient_exit_price": patient_exit_price,
        "target_buy": target_buy,
        "target_sell": target_sell,
        "avg_low": avg_low,
        "avg_high": avg_high,
        "price_warning": price_warning or "",
        "market_context_warning": market_context_warning or "",
        "trend_warning": trend_warning or "",
        "market_momentum": market_momentum or "",
        "daily_trend": daily_trend or "",
        "weekly_trend": weekly_trend or "",
        "long_term_trend": long_term_trend or "",
        "expected_fill_hours": safe_float(expected_fill_hours, 999),
        "liquidity_score": safe_float(liquidity_score, 0),
        "window_name": window_name or "",
        "scanned_at": scanned_at or ""
    }


def get_weighted_cost_basis(cursor, item_id, item_name):
    """
    Estimates cost basis from local unmatched buys for the current account.

    This is only used for active SELLING offers. It does not prove the item
    is currently being bought or sold.
    """
    scope = get_account_scope()
    params = [
        scope["app_username"],
        scope["osrs_account_name"]
    ]

    if item_id is not None:
        where = "item_id = ?"
        params.append(item_id)
    else:
        where = "LOWER(item_name) = LOWER(?)"
        params.append(item_name)

    cursor.execute(f"""
        SELECT
            COALESCE(SUM(price_each * remaining_quantity), 0) AS total_cost,
            COALESCE(SUM(remaining_quantity), 0) AS total_qty
        FROM trade_events
        WHERE app_username = ?
          AND osrs_account_name = ?
          AND side = 'BUY'
          AND remaining_quantity > 0
          AND {where}
    """, params)

    row = cursor.fetchone()

    if not row:
        return None

    total_cost = safe_int(row[0])
    total_qty = safe_int(row[1])

    if total_qty <= 0:
        return None

    return {
        "avg_buy_price": int(total_cost / total_qty),
        "quantity_basis": total_qty,
        "total_cost_basis": total_cost
    }

def locate_runelite_telemetry_file(account=None):
    return RUNELITE_STATE_PATH


def load_runelite_telemetry_json(account=None):
    target_file = locate_runelite_telemetry_file(account=account)

    if not target_file.exists():
        return None, None, f"No OSRSFlipper RuneLite telemetry JSON file found at {target_file}"

    try:
        from runelite_telemetry_control import build_runelite_telemetry_status

        status = build_runelite_telemetry_status(target_file)
        if not status.get("ready"):
            return target_file, None, f"OSRSFlipper RuneLite telemetry is not ready: {status.get('problem') or 'unknown'}"
    except Exception:
        pass

    try:
        data = json.loads(target_file.read_text(encoding="utf-8-sig"))
        return target_file, data, None
    except Exception as error:
        return target_file, None, str(error)


def build_item_name_map(data):
    item_names = {}

    if not isinstance(data, dict):
        return item_names

    for trade in data.get("trades", []):
        if not isinstance(trade, dict):
            continue

        item_id = trade.get("id")
        item_name = trade.get("name")

        if item_id is not None and item_name:
            item_names[safe_int(item_id)] = item_name

    return item_names


def get_live_ge_slot_usage(account=None):
    """
    Reads the live OSRSFlipper RuneLite telemetry lastOffers section to
    estimate current GE slot usage.

    Only lastOffers with state BUYING or SELLING are treated as live/current
    GE slot blockers.

    Historical unmatched buys in trade_events are not treated as live slots.
    """
    target_file, data, error = load_runelite_telemetry_json(account=account)

    if data is None:
        return {
            "available": False,
            "file": str(target_file) if target_file else None,
            "active_slots": 0,
            "free_slots": GE_SLOT_COUNT,
            "offers": [],
            "error": error
        }

    last_offers = data.get("lastOffers", {})
    item_names = build_item_name_map(data)

    offers = []
    active_slots = 0

    if isinstance(last_offers, dict):
        for slot, offer in last_offers.items():
            if not isinstance(offer, dict):
                continue

            state = str(offer.get("st", "")).upper()
            item_id = safe_int(offer.get("id"), None)
            item_name = offer.get("name") or item_names.get(item_id, f"Item ID {item_id}")
            is_buy = bool(offer.get("b"))
            price = safe_int(offer.get("p"), 0)
            completed_qty = safe_int(offer.get("cQIT"), 0)
            total_qty = safe_int(offer.get("tQIT"), 0)
            remaining_qty = max(total_qty - completed_qty, 0)
            trade_started_at = offer.get("tradeStartedAt") or offer.get("t")
            held_hours = hours_since(trade_started_at)

            is_active_slot = state in ("BUYING", "SELLING")

            if is_active_slot:
                active_slots += 1

            offers.append({
                "slot": str(slot),
                "uuid": offer.get("uuid"),
                "state": state,
                "item_id": item_id,
                "item_name": item_name,
                "is_buy": is_buy,
                "price": price,
                "completed_qty": completed_qty,
                "total_qty": total_qty,
                "remaining_qty": remaining_qty,
                "trade_started_at": trade_started_at,
                "held_hours": held_hours,
                "is_active_slot": is_active_slot
            })

    return {
        "available": True,
        "file": str(target_file),
        "active_slots": active_slots,
        "free_slots": max(GE_SLOT_COUNT - active_slots, 0),
        "offers": offers
    }


def classify_live_buy_offer(held_hours, slot_pressure):
    if held_hours is None:
        return "Review manually - unknown offer age"

    if held_hours >= STALE_OVERNIGHT_HOURS and slot_pressure:
        return "Cancel or reprice buy offer - stale and using a GE slot"

    if held_hours >= STALE_BUY_OFFER_HOURS:
        return "Review buy price - offer has been sitting for several hours"

    return "No slot recovery needed yet"


def classify_live_sell_offer(held_hours, loss_percent, estimated_fast_profit_total, slot_pressure):
    if held_hours is None:
        return "Review manually - unknown offer age"

    if estimated_fast_profit_total is not None and estimated_fast_profit_total >= 0 and held_hours >= STALE_SELL_OFFER_HOURS:
        return "Reprice to realistic sell - stale but fast-exit estimate is profitable"

    if held_hours >= STALE_CRITICAL_HOURS:
        if loss_percent is not None and loss_percent <= MAX_MEDIUM_LOSS_PERCENT:
            return "Controlled loss candidate - very stale live sell offer and loss appears moderate"
        return "Very stale live sell offer, but estimated loss is large or unknown; review manually"

    if held_hours >= STALE_OVERNIGHT_HOURS:
        if loss_percent is not None and loss_percent <= MAX_SMALL_LOSS_PERCENT:
            return "Controlled loss candidate - stale overnight live sell offer and small estimated loss"
        if slot_pressure and loss_percent is not None and loss_percent <= MAX_MEDIUM_LOSS_PERCENT:
            return "Possible controlled loss candidate - stale live sell offer and slot pressure is high"
        return "Stale live sell offer - reprice first; loss may be too large"

    if held_hours >= STALE_SELL_OFFER_HOURS and slot_pressure:
        if loss_percent is not None and loss_percent <= MAX_SMALL_LOSS_PERCENT:
            return "Possible slot-recovery exit - live sell offer is stale and loss is small"
        return "Live sell offer is aging; review price before accepting loss"

    return "No slot recovery needed yet"


def get_live_slot_recovery_analysis(cursor, account=None):
    """
    Analyzes only live RuneLite GE slots from lastOffers.

    This fixes the false-positive issue where old local unmatched buys were
    treated as currently buying/selling. They are no longer used for slot
    pressure or current loss-cut advice.
    """
    live_slots = get_live_ge_slot_usage(account=account)

    active_slots = live_slots.get("active_slots", 0)
    free_slots = live_slots.get("free_slots", GE_SLOT_COUNT)
    slot_pressure = active_slots >= 6 or free_slots <= 2

    active_offers = [
        offer for offer in live_slots.get("offers", [])
        if offer.get("is_active_slot")
    ]

    analyzed = []

    for offer in active_offers:
        state = offer.get("state")
        item_id = offer.get("item_id")
        item_name = offer.get("item_name")
        offer_price = safe_int(offer.get("price"))
        remaining_qty = safe_int(offer.get("remaining_qty"))
        total_qty = safe_int(offer.get("total_qty"))
        completed_qty = safe_int(offer.get("completed_qty"))
        held = offer.get("held_hours")
        slot = offer.get("slot")

        market = get_latest_market_exit_estimate(cursor, item_id, item_name)

        if state == "BUYING":
            action = classify_live_buy_offer(held, slot_pressure)

            analyzed.append({
                "type": "LIVE_BUY_OFFER",
                "slot": slot,
                "state": state,
                "item_id": item_id,
                "item_name": item_name,
                "offer_price": offer_price,
                "remaining_qty": remaining_qty,
                "total_qty": total_qty,
                "completed_qty": completed_qty,
                "held_hours": held,
                "open_value": offer_price * remaining_qty,
                "fast_exit_price": None,
                "patient_exit_price": None,
                "estimated_fast_profit_total": None,
                "estimated_patient_profit_total": None,
                "loss_percent": None,
                "action": action,
                "market": market
            })

        elif state == "SELLING":
            cost_basis = get_weighted_cost_basis(cursor, item_id, item_name)

            fast_exit_price = None
            patient_exit_price = offer_price
            estimated_fast_profit_total = None
            estimated_patient_profit_total = None
            loss_percent = None
            avg_buy_price = None

            if market:
                fast_exit_price = safe_int(market.get("fast_exit_price")) or None
                patient_exit_price = offer_price or safe_int(market.get("patient_exit_price")) or fast_exit_price

            if cost_basis and remaining_qty > 0:
                avg_buy_price = safe_int(cost_basis.get("avg_buy_price"))

                if fast_exit_price:
                    fast_net_each = fast_exit_price - ge_tax_per_item(fast_exit_price)
                    estimated_fast_profit_total = (fast_net_each - avg_buy_price) * remaining_qty

                if patient_exit_price:
                    patient_net_each = patient_exit_price - ge_tax_per_item(patient_exit_price)
                    estimated_patient_profit_total = (patient_net_each - avg_buy_price) * remaining_qty

                open_cost = avg_buy_price * remaining_qty

                if open_cost > 0 and estimated_fast_profit_total is not None and estimated_fast_profit_total < 0:
                    loss_percent = abs(estimated_fast_profit_total) / open_cost * 100
                else:
                    loss_percent = 0.0

            action = classify_live_sell_offer(
                held_hours=held,
                loss_percent=loss_percent,
                estimated_fast_profit_total=estimated_fast_profit_total,
                slot_pressure=slot_pressure
            )

            analyzed.append({
                "type": "LIVE_SELL_OFFER",
                "slot": slot,
                "state": state,
                "item_id": item_id,
                "item_name": item_name,
                "offer_price": offer_price,
                "remaining_qty": remaining_qty,
                "total_qty": total_qty,
                "completed_qty": completed_qty,
                "held_hours": held,
                "open_value": offer_price * remaining_qty,
                "avg_buy_price": avg_buy_price,
                "fast_exit_price": fast_exit_price,
                "patient_exit_price": patient_exit_price,
                "estimated_fast_profit_total": estimated_fast_profit_total,
                "estimated_patient_profit_total": estimated_patient_profit_total,
                "loss_percent": loss_percent,
                "action": action,
                "market": market
            })

    analyzed.sort(
        key=lambda item: (
            item.get("type") != "LIVE_SELL_OFFER",
            "controlled loss" not in str(item.get("action", "")).lower(),
            -(item.get("held_hours") or 0)
        )
    )

    return {
        "slot_usage": live_slots,
        "slot_pressure": slot_pressure,
        "positions": analyzed
    }


def build_live_slot_recovery_text(slot_analysis, max_positions=12):
    slot_usage = slot_analysis.get("slot_usage", {})
    positions = slot_analysis.get("positions", [])
    slot_pressure = slot_analysis.get("slot_pressure", False)

    lines = []

    lines.append("LIVE GE SLOT ANALYSIS FROM OSRSFLIPPER RUNELITE TELEMETRY lastOffers")
    lines.append(f"- GE slots available in OSRS: {GE_SLOT_COUNT}")
    lines.append(f"- Live RuneLite slot data available: {slot_usage.get('available', False)}")

    if slot_usage.get("file"):
        lines.append(f"- RuneLite file checked: {slot_usage.get('file')}")

    if slot_usage.get("error"):
        lines.append(f"- RuneLite slot read error: {slot_usage.get('error')}")

    lines.append(f"- Active live GE slots: {slot_usage.get('active_slots', 0)}")
    lines.append(f"- Free live GE slots: {slot_usage.get('free_slots', GE_SLOT_COUNT)}")
    lines.append(f"- Slot pressure high: {slot_pressure}")
    lines.append("")
    lines.append(
        "Important: Only items listed in this LIVE GE SLOT ANALYSIS are current GE-slot blockers. "
        "Local unmatched buy history is not the same thing as a current buy or sell offer."
    )
    lines.append("")

    if not positions:
        lines.append("No active BUYING or SELLING offers were found in OSRSFlipper RuneLite telemetry lastOffers.")
        return "\n".join(lines)

    lines.append("Active live GE offers to review:")

    for index, pos in enumerate(positions, start=1):
        if index > max_positions:
            lines.append(f"- ...and {len(positions) - max_positions} more active GE offers.")
            break

        held_text = "unknown"
        if pos.get("held_hours") is not None:
            held_text = f"{pos['held_hours']:.1f}h"

        state = pos.get("state")
        item_name = pos.get("item_name")
        slot = pos.get("slot")
        remaining_qty = safe_int(pos.get("remaining_qty"))
        total_qty = safe_int(pos.get("total_qty"))
        completed_qty = safe_int(pos.get("completed_qty"))
        offer_price = safe_int(pos.get("offer_price"))

        if state == "BUYING":
            lines.append(
                f"- Slot {slot} | {item_name} | LIVE BUYING offer | held {held_text} | "
                f"offer price {offer_price:,} | remaining buy qty {remaining_qty:,}/{total_qty:,} | "
                f"filled qty {completed_qty:,}"
            )
            lines.append(
                f"  Slot recovery action: {pos.get('action')}. "
                "This is a buy offer, so loss-cut selling does not apply; consider canceling or repricing if stale."
            )

        elif state == "SELLING":
            fast_exit = pos.get("fast_exit_price")
            patient_exit = pos.get("patient_exit_price")
            fast_total = pos.get("estimated_fast_profit_total")
            patient_total = pos.get("estimated_patient_profit_total")
            loss_percent = pos.get("loss_percent")
            avg_buy = pos.get("avg_buy_price")

            fast_exit_text = f"{fast_exit:,}" if fast_exit else "unknown"
            patient_exit_text = f"{patient_exit:,}" if patient_exit else "unknown"
            fast_total_text = "unknown" if fast_total is None else format_gp(fast_total)
            patient_total_text = "unknown" if patient_total is None else format_gp(patient_total)
            loss_percent_text = "unknown" if loss_percent is None else format_percent(loss_percent)
            avg_buy_text = "unknown" if avg_buy is None else f"{safe_int(avg_buy):,}"

            market = pos.get("market") or {}

            lines.append(
                f"- Slot {slot} | {item_name} | LIVE SELLING offer | held {held_text} | "
                f"offer price {offer_price:,} | remaining sell qty {remaining_qty:,}/{total_qty:,} | "
                f"filled qty {completed_qty:,}"
            )
            lines.append(
                f"  Cost basis estimate: avg buy {avg_buy_text}. "
                f"Fast-exit estimate: sell {fast_exit_text}, est P/L {fast_total_text}, loss % {loss_percent_text}."
            )
            lines.append(
                f"  Patient/offer estimate: sell {patient_exit_text}, est P/L {patient_total_text}."
            )
            lines.append(
                f"  Liquidity {market.get('liquidity_score', 'unknown')}, expected fill {market.get('expected_fill_hours', 'unknown')}h, "
                f"trend warning: {market.get('trend_warning', '') or 'OK'}, "
                f"market warning: {market.get('market_context_warning', '') or 'OK'}, "
                f"price warning: {market.get('price_warning', '') or 'OK'}"
            )
            lines.append(f"  Slot recovery action: {pos.get('action')}")

    return "\n".join(lines)


def build_unmatched_inventory_text(cursor, limit=12):
    summary = get_unmatched_inventory_summary(cursor)
    rows = get_unmatched_inventory_rows(cursor, limit=limit)

    lines = []
    lines.append("LOCAL UNMATCHED BUY HISTORY / POSSIBLE INVENTORY")
    lines.append(
        "Important: These are local ledger rows where a BUY has not been matched to a SELL. "
        "They are not automatically current GE offers and must not be described as currently buying or selling."
    )
    lines.append(f"- Unmatched local buy rows: {summary['unmatched_count']}")
    lines.append(f"- Local unmatched value estimate: {format_gp(summary['unmatched_value'])}")
    lines.append(f"- Largest local unmatched row: {format_gp(summary['largest_unmatched'])}")

    if not rows:
        lines.append("- No unmatched local buy rows found.")
        return "\n".join(lines)

    lines.append("Largest local unmatched rows, for inventory/history context only:")

    for row in rows:
        traded_at, item_id, item_name, price_each, remaining_quantity, open_value, source, status = row
        lines.append(
            f"- {traded_at} | {item_name} | remaining qty {safe_int(remaining_quantity):,} | "
            f"buy price {safe_int(price_each):,} | value {format_gp(open_value)} | source {source} | status {status}"
        )

    return "\n".join(lines)


def build_trade_ai_context(
    days=30,
    item_limit=15,
    recent_limit=20,
    open_limit=20,
    include_notes=True,
    account=None
):
    init_ai_trade_db()

    conn = get_connection()
    cursor = conn.cursor()

    if not table_exists(cursor, "completed_trades") or not table_exists(cursor, "trade_events"):
        conn.close()
        return (
            "Trade tracking tables are not initialized yet. "
            "Run: python trade_tracker.py init"
        )

    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since_dt.isoformat()

    lifetime = get_completed_trade_summary(cursor)
    recent = get_completed_trade_summary(cursor, since_iso=since_iso)

    top_items = get_item_performance(
        cursor,
        since_iso=since_iso,
        limit=item_limit
    )

    worst_items = get_worst_items(
        cursor,
        since_iso=since_iso,
        limit=10
    )

    recent_trades = get_recent_completed(
        cursor,
        limit=recent_limit
    )

    live_slot_analysis = get_live_slot_recovery_analysis(
        cursor=cursor,
        account=account
    )

    unmatched_inventory_text = build_unmatched_inventory_text(
        cursor=cursor,
        limit=open_limit
    )

    conn.close()

    lines = []

    scope = get_account_scope()

    lines.append("LOCAL TRADE MEMORY FROM OSRSFLIPPER")
    lines.append("")
    lines.append(f"Local app user: {scope['app_username']}")
    lines.append(f"OSRS/RuneLite account: {scope['osrs_account_name']}")
    lines.append(f"Window analyzed: last {days} days plus lifetime summary.")
    lines.append("")

    lines.append("Lifetime realized performance:")
    lines.append(f"- Completed matched flips: {lifetime['completed_count']}")
    lines.append(f"- Total realized P/L: {format_gp(lifetime['total_profit'])}")
    lines.append(f"- Average ROI: {format_percent(lifetime['avg_roi'])}")
    lines.append(f"- Average net profit/item: {format_gp(lifetime['avg_net_each'])}")
    lines.append(f"- Best trade: {format_gp(lifetime['best_trade'])}")
    lines.append(f"- Worst trade: {format_gp(lifetime['worst_trade'])}")
    lines.append(f"- Wins / losses: {lifetime['wins']} wins, {lifetime['losses']} losses")
    lines.append("")

    lines.append(f"Recent realized performance, last {days} days:")
    lines.append(f"- Completed matched flips: {recent['completed_count']}")
    lines.append(f"- Total realized P/L: {format_gp(recent['total_profit'])}")
    lines.append(f"- Average ROI: {format_percent(recent['avg_roi'])}")
    lines.append(f"- Average net profit/item: {format_gp(recent['avg_net_each'])}")
    lines.append(f"- Best recent trade: {format_gp(recent['best_trade'])}")
    lines.append(f"- Worst recent trade: {format_gp(recent['worst_trade'])}")
    lines.append(f"- Recent wins / losses: {recent['wins']} wins, {recent['losses']} losses")
    lines.append("")

    lines.append(build_live_slot_recovery_text(live_slot_analysis))
    lines.append("")

    lines.append(unmatched_inventory_text)
    lines.append("")

    lines.append(f"Best-performing items in the last {days} days:")
    if top_items:
        for row in top_items:
            item_name, flips, total_qty, item_profit, avg_roi, avg_net_each, worst_trade, best_trade = row
            lines.append(
                f"- {item_name}: {flips} flips, qty {safe_int(total_qty):,}, "
                f"P/L {format_gp(item_profit)}, avg ROI {format_percent(avg_roi)}, "
                f"avg net/item {format_gp(avg_net_each)}, "
                f"best {format_gp(best_trade)}, worst {format_gp(worst_trade)}"
            )
    else:
        lines.append("- No completed item performance found in this window.")
    lines.append("")

    lines.append(f"Worst-performing items in the last {days} days:")
    if worst_items:
        for row in worst_items:
            item_name, flips, item_profit, avg_roi, worst_trade = row
            lines.append(
                f"- {item_name}: {flips} flips, P/L {format_gp(item_profit)}, "
                f"avg ROI {format_percent(avg_roi)}, worst trade {format_gp(worst_trade)}"
            )
    else:
        lines.append("- No losing item groups found in this window.")
    lines.append("")

    lines.append("Recent completed flips:")
    if recent_trades:
        for row in recent_trades:
            (
                sell_time,
                item_name,
                quantity,
                buy_price_each,
                sell_price_each,
                raw_margin_each,
                tax_each,
                net_profit_each,
                total_profit,
                roi_percent
            ) = row

            lines.append(
                f"- {sell_time} | {item_name} | qty {safe_int(quantity):,} | "
                f"buy {safe_int(buy_price_each):,} -> sell {safe_int(sell_price_each):,} | "
                f"raw margin/item {format_gp(raw_margin_each)} | tax/item {format_gp(tax_each)} | "
                f"net/item {format_gp(net_profit_each)} | total {format_gp(total_profit)} | "
                f"ROI {format_percent(roi_percent)}"
            )
    else:
        lines.append("- No completed flips found yet.")
    lines.append("")

    if include_notes:
        lines.append("Previous saved AI trade feedback:")
        lines.append(get_recent_ai_feedback(limit=5))
        lines.append("")

    lines.append("Instruction for advisor:")
    lines.append(
        "- Use LIVE GE SLOT ANALYSIS only when discussing current GE slots, slot pressure, "
        "currently buying offers, currently selling offers, repricing, or controlled loss exits."
    )
    lines.append(
        "- Do not treat LOCAL UNMATCHED BUY HISTORY as current GE slots. That section is only "
        "inventory/history context and may include old buys that are no longer active offers."
    )
    lines.append(
        "- Loss-cut advice should only be based on live SELLING offers with an estimated cost basis, "
        "held time, slot pressure, liquidity, current trend, and estimated loss."
    )
    lines.append(
        "- For live BUYING offers, suggest cancel/reprice if stale; do not suggest selling at a loss "
        "because the item has not necessarily been bought yet."
    )

    return "\n".join(lines)


def print_context(days=30, account=None):
    print(build_trade_ai_context(days=days, account=account))


def main():
    parser = argparse.ArgumentParser(
        description="Build local trade-memory context for advisor.py."
    )

    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--account", default=None)
    parser.add_argument("--save-test-note", action="store_true")

    args = parser.parse_args()

    if args.save_test_note:
        note_id = save_ai_feedback(
            title="Test AI note",
            feedback="This is a test note showing that AI feedback storage is working.",
            tags="test"
        )

        print(f"Saved test AI note: {note_id}")

    print_context(days=args.days, account=args.account)


if __name__ == "__main__":
    main()
