import argparse
import csv
import json
import os
import sqlite3
from datetime import datetime, timezone

from account_context import get_account_scope, apply_account_env

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "osrs_flip_scanner.db")
IMPORT_DIR = os.path.join(BASE_DIR, "runelite_imports")

GE_TAX_RATE = 0.02
GE_TAX_CAP_PER_ITEM = 5_000_000


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    return sqlite3.connect(DB_FILE)


def normalize_side(side):
    side = str(side).strip().upper()

    if side in ("B", "BUY", "BOUGHT"):
        return "BUY"

    if side in ("S", "SELL", "SOLD"):
        return "SELL"

    raise ValueError("side must be BUY or SELL")


def parse_int(value, field_name):
    if value is None:
        raise ValueError(f"{field_name} is required")

    value = str(value).replace(",", "").strip()

    if value == "":
        raise ValueError(f"{field_name} is required")

    return int(float(value))


def parse_optional_int(value):
    if value is None:
        return None

    value = str(value).replace(",", "").strip()

    if value == "":
        return None

    return int(float(value))


def calculate_ge_tax_per_item(sell_price_each):
    sell_price_each = int(sell_price_each)

    if sell_price_each <= 0:
        return 0

    return min(max(int(sell_price_each * GE_TAX_RATE), 0), GE_TAX_CAP_PER_ITEM)


def calculate_trade_metrics(buy_price_each, sell_price_each, quantity):
    buy_price_each = int(buy_price_each)
    sell_price_each = int(sell_price_each)
    quantity = int(quantity)

    raw_margin_each = sell_price_each - buy_price_each
    tax_each = calculate_ge_tax_per_item(sell_price_each)
    net_profit_each = sell_price_each - buy_price_each - tax_each
    total_profit = net_profit_each * quantity

    buy_total = buy_price_each * quantity
    sell_total = sell_price_each * quantity
    tax_total = tax_each * quantity

    if buy_price_each > 0:
        roi_percent = (net_profit_each / buy_price_each) * 100
    else:
        roi_percent = 0

    return {
        "raw_margin_each": raw_margin_each,
        "tax_each": tax_each,
        "net_profit_each": net_profit_each,
        "buy_total": buy_total,
        "sell_total": sell_total,
        "tax_total": tax_total,
        "total_profit": total_profit,
        "roi_percent": roi_percent
    }


def column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    return column_name in [row[1] for row in cursor.fetchall()]


def add_column_if_missing(cursor, table_name, column_name, column_definition):
    if not column_exists(cursor, table_name, column_name):
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )


def init_trade_db():
    os.makedirs(IMPORT_DIR, exist_ok=True)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_username TEXT NOT NULL DEFAULT 'default',
            osrs_account_name TEXT NOT NULL DEFAULT 'default',
            external_id TEXT UNIQUE,
            source TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',

            traded_at TEXT NOT NULL,
            imported_at TEXT NOT NULL,

            item_id INTEGER,
            item_name TEXT NOT NULL,
            side TEXT NOT NULL,

            price_each INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            remaining_quantity INTEGER NOT NULL,

            total_value INTEGER NOT NULL,
            notes TEXT,
            raw_payload TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS completed_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_username TEXT NOT NULL DEFAULT 'default',
            osrs_account_name TEXT NOT NULL DEFAULT 'default',

            buy_event_id INTEGER NOT NULL,
            sell_event_id INTEGER NOT NULL,

            item_id INTEGER,
            item_name TEXT NOT NULL,

            buy_time TEXT NOT NULL,
            sell_time TEXT NOT NULL,

            buy_price_each INTEGER NOT NULL,
            sell_price_each INTEGER NOT NULL,
            quantity INTEGER NOT NULL,

            raw_margin_each INTEGER NOT NULL,
            tax_each INTEGER NOT NULL,
            net_profit_each INTEGER NOT NULL,

            buy_total INTEGER NOT NULL,
            sell_total INTEGER NOT NULL,
            tax_total INTEGER NOT NULL,
            total_profit INTEGER NOT NULL,
            roi_percent REAL NOT NULL,

            source TEXT NOT NULL,
            created_at TEXT NOT NULL,

            notes TEXT,

            FOREIGN KEY (buy_event_id) REFERENCES trade_events(id),
            FOREIGN KEY (sell_event_id) REFERENCES trade_events(id)
        )
    """)

    # Migrate existing databases.
    for table in ("trade_events", "completed_trades"):
        add_column_if_missing(cursor, table, "app_username", "TEXT NOT NULL DEFAULT 'default'")
        add_column_if_missing(cursor, table, "osrs_account_name", "TEXT NOT NULL DEFAULT 'default'")

    # If old rows are still default and the current account is known, assign them once.
    scope = get_account_scope()

    if scope["app_username"] != "default" or scope["osrs_account_name"] != "default":
        cursor.execute("""
            UPDATE trade_events
            SET app_username = ?,
                osrs_account_name = ?
            WHERE app_username = 'default'
              AND osrs_account_name = 'default'
        """, (
            scope["app_username"],
            scope["osrs_account_name"]
        ))

        cursor.execute("""
            UPDATE completed_trades
            SET app_username = ?,
                osrs_account_name = ?
            WHERE app_username = 'default'
              AND osrs_account_name = 'default'
        """, (
            scope["app_username"],
            scope["osrs_account_name"]
        ))

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_trade_events_account_item_side
        ON trade_events(app_username, osrs_account_name, item_id, item_name, side)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_trade_events_account_remaining
        ON trade_events(app_username, osrs_account_name, side, remaining_quantity)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_trade_events_account_time
        ON trade_events(app_username, osrs_account_name, traded_at)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_completed_trades_account_item
        ON completed_trades(app_username, osrs_account_name, item_id, item_name)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_completed_trades_account_sell_time
        ON completed_trades(app_username, osrs_account_name, sell_time)
    """)

    conn.commit()
    conn.close()


def build_external_id(source, traded_at, item_id, item_name, side, price_each, quantity, app_username, osrs_account_name):
    item_part = item_id if item_id is not None else item_name
    return f"{app_username}|{osrs_account_name}|{source}|{traded_at}|{item_part}|{side}|{price_each}|{quantity}"


def record_trade_event(
    item_name,
    side,
    price_each,
    quantity,
    item_id=None,
    traded_at=None,
    source="manual",
    external_id=None,
    notes=None,
    raw_payload=None,
    app_username=None,
    osrs_account_name=None
):
    """
    Records one buy or sell event scoped to the current local app user and
    linked OSRS/RuneLite account.

    If it records a SELL event, it automatically matches the sell against
    earlier unmatched BUY events for the same account only.
    """
    init_trade_db()

    scope = get_account_scope(
        app_username=app_username,
        osrs_account_name=osrs_account_name
    )

    app_username = scope["app_username"]
    osrs_account_name = scope["osrs_account_name"]

    side = normalize_side(side)
    price_each = parse_int(price_each, "price_each")
    quantity = parse_int(quantity, "quantity")
    item_id = parse_optional_int(item_id)

    if quantity <= 0:
        raise ValueError("quantity must be greater than 0")

    if price_each <= 0:
        raise ValueError("price_each must be greater than 0")

    if traded_at is None:
        traded_at = now_utc()

    item_name = str(item_name).strip()

    if not item_name:
        raise ValueError("item_name is required")

    if external_id is None:
        external_id = build_external_id(
            source=source,
            traded_at=traded_at,
            item_id=item_id,
            item_name=item_name,
            side=side,
            price_each=price_each,
            quantity=quantity,
            app_username=app_username,
            osrs_account_name=osrs_account_name
        )
    else:
        external_id = f"{app_username}|{osrs_account_name}|{external_id}"

    if raw_payload is not None and not isinstance(raw_payload, str):
        raw_payload = json.dumps(raw_payload, ensure_ascii=False)

    total_value = price_each * quantity

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO trade_events (
                app_username,
                osrs_account_name,
                external_id,
                source,
                status,
                traded_at,
                imported_at,
                item_id,
                item_name,
                side,
                price_each,
                quantity,
                remaining_quantity,
                total_value,
                notes,
                raw_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            app_username,
            osrs_account_name,
            external_id,
            source,
            "OPEN",
            traded_at,
            now_utc(),
            item_id,
            item_name,
            side,
            price_each,
            quantity,
            quantity,
            total_value,
            notes,
            raw_payload
        ))

        event_id = cursor.lastrowid

    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return {
            "inserted": False,
            "matched_count": 0,
            "message": "Duplicate trade event skipped.",
            "external_id": external_id
        }

    if side == "SELL":
        matched_count = match_sell_event(cursor, event_id)
    else:
        matched_count = 0

    conn.commit()
    conn.close()

    return {
        "inserted": True,
        "event_id": event_id,
        "matched_count": matched_count,
        "external_id": external_id,
        "app_username": app_username,
        "osrs_account_name": osrs_account_name
    }


def match_sell_event(cursor, sell_event_id):
    cursor.execute("""
        SELECT
            id,
            app_username,
            osrs_account_name,
            item_id,
            item_name,
            traded_at,
            price_each,
            remaining_quantity,
            source
        FROM trade_events
        WHERE id = ?
          AND side = 'SELL'
          AND remaining_quantity > 0
    """, (sell_event_id,))

    sell = cursor.fetchone()

    if sell is None:
        return 0

    (
        sell_id,
        app_username,
        osrs_account_name,
        sell_item_id,
        sell_item_name,
        sell_time,
        sell_price_each,
        sell_remaining,
        sell_source
    ) = sell

    matched_count = 0

    while sell_remaining > 0:
        if sell_item_id is not None:
            cursor.execute("""
                SELECT
                    id,
                    traded_at,
                    price_each,
                    remaining_quantity
                FROM trade_events
                WHERE app_username = ?
                  AND osrs_account_name = ?
                  AND side = 'BUY'
                  AND remaining_quantity > 0
                  AND item_id = ?
                ORDER BY traded_at ASC, id ASC
                LIMIT 1
            """, (app_username, osrs_account_name, sell_item_id))
        else:
            cursor.execute("""
                SELECT
                    id,
                    traded_at,
                    price_each,
                    remaining_quantity
                FROM trade_events
                WHERE app_username = ?
                  AND osrs_account_name = ?
                  AND side = 'BUY'
                  AND remaining_quantity > 0
                  AND item_name = ?
                ORDER BY traded_at ASC, id ASC
                LIMIT 1
            """, (app_username, osrs_account_name, sell_item_name))

        buy = cursor.fetchone()

        if buy is None:
            break

        buy_id, buy_time, buy_price_each, buy_remaining = buy
        matched_quantity = min(buy_remaining, sell_remaining)

        metrics = calculate_trade_metrics(
            buy_price_each=buy_price_each,
            sell_price_each=sell_price_each,
            quantity=matched_quantity
        )

        cursor.execute("""
            INSERT INTO completed_trades (
                app_username,
                osrs_account_name,
                buy_event_id,
                sell_event_id,
                item_id,
                item_name,
                buy_time,
                sell_time,
                buy_price_each,
                sell_price_each,
                quantity,
                raw_margin_each,
                tax_each,
                net_profit_each,
                buy_total,
                sell_total,
                tax_total,
                total_profit,
                roi_percent,
                source,
                created_at,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            app_username,
            osrs_account_name,
            buy_id,
            sell_id,
            sell_item_id,
            sell_item_name,
            buy_time,
            sell_time,
            buy_price_each,
            sell_price_each,
            matched_quantity,
            metrics["raw_margin_each"],
            metrics["tax_each"],
            metrics["net_profit_each"],
            metrics["buy_total"],
            metrics["sell_total"],
            metrics["tax_total"],
            metrics["total_profit"],
            metrics["roi_percent"],
            sell_source,
            now_utc(),
            "Auto-matched FIFO"
        ))

        cursor.execute("""
            UPDATE trade_events
            SET remaining_quantity = remaining_quantity - ?
            WHERE id = ?
        """, (matched_quantity, buy_id))

        cursor.execute("""
            UPDATE trade_events
            SET remaining_quantity = remaining_quantity - ?
            WHERE id = ?
        """, (matched_quantity, sell_id))

        sell_remaining -= matched_quantity
        matched_count += 1

    cursor.execute("""
        UPDATE trade_events
        SET status = CASE
            WHEN remaining_quantity <= 0 THEN 'CLOSED'
            ELSE 'OPEN'
        END
        WHERE id = ?
    """, (sell_id,))

    cursor.execute("""
        UPDATE trade_events
        SET status = CASE
            WHEN remaining_quantity <= 0 THEN 'CLOSED'
            ELSE 'OPEN'
        END
        WHERE app_username = ?
          AND osrs_account_name = ?
          AND side = 'BUY'
    """, (app_username, osrs_account_name))

    return matched_count


def import_csv(file_path, source="csv", app_username=None, osrs_account_name=None):
    init_trade_db()

    imported = 0
    skipped = 0
    matched = 0

    with open(file_path, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    rows.sort(key=lambda row: row.get("traded_at") or row.get("time") or "")

    for row in rows:
        item_name = row.get("item_name") or row.get("item") or row.get("Item")
        side = row.get("side") or row.get("type") or row.get("Side")
        price_each = row.get("price_each") or row.get("price") or row.get("Price")
        quantity = row.get("quantity") or row.get("qty") or row.get("Quantity")
        item_id = row.get("item_id") or row.get("id") or row.get("Item ID")
        traded_at = row.get("traded_at") or row.get("time") or row.get("Time") or now_utc()
        external_id = row.get("external_id") or row.get("id_external")
        notes = row.get("notes") or row.get("Notes")

        try:
            result = record_trade_event(
                item_name=item_name,
                side=side,
                price_each=price_each,
                quantity=quantity,
                item_id=item_id,
                traded_at=traded_at,
                source=source,
                external_id=external_id,
                notes=notes,
                raw_payload=row,
                app_username=app_username,
                osrs_account_name=osrs_account_name
            )

            if result["inserted"]:
                imported += 1
                matched += result.get("matched_count", 0)
            else:
                skipped += 1

        except Exception as error:
            skipped += 1
            print(f"Skipped row because of error: {error}")
            print(row)

    return {
        "imported": imported,
        "skipped": skipped,
        "matched": matched
    }


def get_summary(app_username=None, osrs_account_name=None):
    init_trade_db()

    scope = get_account_scope(app_username, osrs_account_name)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(*),
            COALESCE(SUM(total_profit), 0),
            COALESCE(AVG(roi_percent), 0),
            COALESCE(MAX(total_profit), 0),
            COALESCE(MIN(total_profit), 0)
        FROM completed_trades
        WHERE app_username = ?
          AND osrs_account_name = ?
    """, (scope["app_username"], scope["osrs_account_name"]))

    (
        completed_count,
        total_profit,
        avg_roi,
        best_trade,
        worst_trade
    ) = cursor.fetchone()

    cursor.execute("""
        SELECT
            COALESCE(SUM(total_value), 0)
        FROM trade_events
        WHERE app_username = ?
          AND osrs_account_name = ?
          AND side = 'BUY'
          AND remaining_quantity > 0
    """, (scope["app_username"], scope["osrs_account_name"]))

    open_buy_value = cursor.fetchone()[0]

    cursor.execute("""
        SELECT
            COUNT(*)
        FROM trade_events
        WHERE app_username = ?
          AND osrs_account_name = ?
          AND remaining_quantity > 0
    """, (scope["app_username"], scope["osrs_account_name"]))

    open_event_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT
            item_name,
            COALESCE(SUM(total_profit), 0) AS item_profit
        FROM completed_trades
        WHERE app_username = ?
          AND osrs_account_name = ?
        GROUP BY item_id, item_name
        ORDER BY item_profit DESC
        LIMIT 1
    """, (scope["app_username"], scope["osrs_account_name"]))

    best_item = cursor.fetchone()

    cursor.execute("""
        SELECT
            item_name,
            COALESCE(SUM(total_profit), 0) AS item_profit
        FROM completed_trades
        WHERE app_username = ?
          AND osrs_account_name = ?
        GROUP BY item_id, item_name
        ORDER BY item_profit ASC
        LIMIT 1
    """, (scope["app_username"], scope["osrs_account_name"]))

    worst_item = cursor.fetchone()

    conn.close()

    return {
        "account": scope,
        "completed_count": completed_count,
        "total_profit": total_profit,
        "avg_roi": avg_roi,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "open_buy_value": open_buy_value,
        "open_event_count": open_event_count,
        "best_item": best_item,
        "worst_item": worst_item
    }


def print_summary():
    summary = get_summary()
    scope = summary["account"]

    print("\n==============================")
    print(" OSRS Trade Tracker Summary")
    print("==============================")
    print(f"Local user: {scope['app_username']}")
    print(f"OSRS/RuneLite account: {scope['osrs_account_name']}")
    print(f"Completed matched flips: {summary['completed_count']}")
    print(f"Total realized profit: {summary['total_profit']:,} gp")
    print(f"Average ROI: {summary['avg_roi']:.2f}%")
    print(f"Best matched trade: {summary['best_trade']:,} gp")
    print(f"Worst matched trade: {summary['worst_trade']:,} gp")
    print(f"Open trade events: {summary['open_event_count']}")
    print(f"Open buy value: {summary['open_buy_value']:,} gp")

    if summary["best_item"]:
        print(f"Best item: {summary['best_item'][0]} ({summary['best_item'][1]:,} gp)")

    if summary["worst_item"]:
        print(f"Worst item: {summary['worst_item'][0]} ({summary['worst_item'][1]:,} gp)")


def print_events(limit=50):
    init_trade_db()
    scope = get_account_scope()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            traded_at,
            item_name,
            side,
            price_each,
            quantity,
            remaining_quantity,
            total_value,
            source,
            status
        FROM trade_events
        WHERE app_username = ?
          AND osrs_account_name = ?
        ORDER BY traded_at DESC, id DESC
        LIMIT ?
    """, (scope["app_username"], scope["osrs_account_name"], limit))

    rows = cursor.fetchall()
    conn.close()

    print("\n==============================")
    print(" Trade Events")
    print("==============================")
    print(f"Local user: {scope['app_username']}")
    print(f"OSRS/RuneLite account: {scope['osrs_account_name']}")

    if not rows:
        print("No trade events found.")
        return

    for row in rows:
        (
            event_id,
            traded_at,
            item_name,
            side,
            price_each,
            quantity,
            remaining_quantity,
            total_value,
            source,
            status
        ) = row

        print(
            f"{event_id} | {traded_at} | {side:<4} | {item_name} | "
            f"{quantity:,} @ {price_each:,} gp | "
            f"remaining {remaining_quantity:,} | {total_value:,} gp | "
            f"{source} | {status}"
        )


def print_completed(limit=50):
    init_trade_db()
    scope = get_account_scope()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            sell_time,
            item_name,
            quantity,
            buy_price_each,
            sell_price_each,
            raw_margin_each,
            tax_each,
            net_profit_each,
            total_profit,
            roi_percent,
            source
        FROM completed_trades
        WHERE app_username = ?
          AND osrs_account_name = ?
        ORDER BY sell_time DESC, id DESC
        LIMIT ?
    """, (scope["app_username"], scope["osrs_account_name"], limit))

    rows = cursor.fetchall()
    conn.close()

    print("\n==============================")
    print(" Completed Matched Flips")
    print("==============================")
    print(f"Local user: {scope['app_username']}")
    print(f"OSRS/RuneLite account: {scope['osrs_account_name']}")

    if not rows:
        print("No completed flips found.")
        return

    for row in rows:
        (
            trade_id,
            sell_time,
            item_name,
            quantity,
            buy_price_each,
            sell_price_each,
            raw_margin_each,
            tax_each,
            net_profit_each,
            total_profit,
            roi_percent,
            source
        ) = row

        print(
            f"{trade_id} | {sell_time} | {item_name} | qty {quantity:,} | "
            f"buy {buy_price_each:,} -> sell {sell_price_each:,} | "
            f"raw {raw_margin_each:,} | tax {tax_each:,} | "
            f"net/item {net_profit_each:,} | total {total_profit:,} | "
            f"ROI {roi_percent:.2f}% | {source}"
        )


def create_template_csv():
    init_trade_db()

    template_path = os.path.join(IMPORT_DIR, "trade_import_template.csv")

    rows = [
        {
            "item_name": "Abyssal whip",
            "item_id": "4151",
            "side": "BUY",
            "price_each": "1030000",
            "quantity": "1",
            "traded_at": "2026-06-25T12:00:00+00:00",
            "external_id": "example-buy-1",
            "notes": "Example buy"
        },
        {
            "item_name": "Abyssal whip",
            "item_id": "4151",
            "side": "SELL",
            "price_each": "1060000",
            "quantity": "1",
            "traded_at": "2026-06-25T15:00:00+00:00",
            "external_id": "example-sell-1",
            "notes": "Example sell"
        }
    ]

    with open(template_path, "w", encoding="utf-8", newline="") as file:
        fieldnames = [
            "item_name",
            "item_id",
            "side",
            "price_each",
            "quantity",
            "traded_at",
            "external_id",
            "notes"
        ]

        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return template_path


def main():
    parser = argparse.ArgumentParser(
        description="OSRS trade tracker for completed flips and P/L."
    )

    parser.add_argument("--user", default=None, help="Optional local OSRSFlipper username scope.")
    parser.add_argument("--account", default=None, help="Optional OSRS/RuneLite account scope.")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Create trade tracking tables.")

    add_parser = subparsers.add_parser("add", help="Add one BUY or SELL event.")
    add_parser.add_argument("--item", required=True, help="Item name.")
    add_parser.add_argument("--item-id", default=None, help="Optional item ID.")
    add_parser.add_argument("--side", required=True, help="BUY or SELL.")
    add_parser.add_argument("--price", required=True, help="Price each.")
    add_parser.add_argument("--qty", required=True, help="Quantity.")
    add_parser.add_argument("--time", default=None, help="ISO timestamp. Optional.")
    add_parser.add_argument("--source", default="manual", help="Source label.")
    add_parser.add_argument("--notes", default=None, help="Optional notes.")

    import_parser = subparsers.add_parser("import-csv", help="Import trade events from CSV.")
    import_parser.add_argument("file", help="CSV file path.")
    import_parser.add_argument("--source", default="csv", help="Source label.")

    list_events_parser = subparsers.add_parser("list-events", help="List trade events.")
    list_events_parser.add_argument("--limit", type=int, default=50)

    list_completed_parser = subparsers.add_parser("list-completed", help="List completed matched flips.")
    list_completed_parser.add_argument("--limit", type=int, default=50)

    subparsers.add_parser("summary", help="Show profit/loss summary.")
    subparsers.add_parser("template", help="Create a CSV import template.")

    args = parser.parse_args()

    if args.user or args.account:
        apply_account_env(args.user, args.account)

    if args.command == "init":
        init_trade_db()
        scope = get_account_scope()
        print(f"Trade tracking tables ready in: {DB_FILE}")
        print(f"Import folder ready: {IMPORT_DIR}")
        print(f"Current local user: {scope['app_username']}")
        print(f"Current OSRS/RuneLite account: {scope['osrs_account_name']}")

    elif args.command == "add":
        result = record_trade_event(
            item_name=args.item,
            item_id=args.item_id,
            side=args.side,
            price_each=args.price,
            quantity=args.qty,
            traded_at=args.time,
            source=args.source,
            notes=args.notes
        )

        print(result)

    elif args.command == "import-csv":
        result = import_csv(
            file_path=args.file,
            source=args.source
        )

        print(result)

    elif args.command == "list-events":
        print_events(limit=args.limit)

    elif args.command == "list-completed":
        print_completed(limit=args.limit)

    elif args.command == "summary":
        print_summary()

    elif args.command == "template":
        template_path = create_template_csv()
        print(f"Created template: {template_path}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
