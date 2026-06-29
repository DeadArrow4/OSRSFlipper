import argparse
import csv
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from trade_tracker import (
    DB_FILE,
    IMPORT_DIR,
    init_trade_db,
    record_trade_event
)
from account_context import BASE_DIR, apply_account_env
from runelite_paths import DEFAULT_RUNELITE_STATE_PATH, LEGACY_RUNELITE_STATE_PATH, resolve_runelite_state_path


SUPPORTED_EXTENSIONS = {".csv", ".json", ".jsonl"}

OSRSFLIPPER_RUNELITE_STATE_PATH = DEFAULT_RUNELITE_STATE_PATH
RUNELITE_TELEMETRY_SOURCE = "osrsflipper-runelite-telemetry"

ITEM_NAME_KEYS = [
    "item_name",
    "item",
    "itemName",
    "name"
]

ITEM_ID_KEYS = [
    "item_id",
    "itemId",
    "itemID",
    "id"
]

SIDE_KEYS = [
    "side",
    "type",
    "offer_type",
    "offerType",
    "action",
    "transaction_type",
    "transactionType",
    "buy_sell",
    "buySell",
    "state",
    "st"
]

PRICE_KEYS = [
    "price_each",
    "price",
    "unit_price",
    "unitPrice",
    "priceEach",
    "offer_price",
    "offerPrice",
    "average_price",
    "averagePrice",
    "gp_each",
    "gpEach",
    "p"
]

QUANTITY_KEYS = [
    "quantity",
    "qty",
    "amount",
    "count",
    "total_quantity",
    "totalQuantity",
    "items",
    "item_count",
    "itemCount",
    "cQIT"
]

TIME_KEYS = [
    "traded_at",
    "time",
    "timestamp",
    "date",
    "datetime",
    "created_at",
    "createdAt",
    "completed_at",
    "completedAt",
    "t"
]

EXTERNAL_ID_KEYS = [
    "external_id",
    "externalId",
    "uuid",
    "trade_id",
    "tradeId",
    "event_id",
    "eventId",
    "offer_id",
    "offerId"
]

NOTES_KEYS = [
    "notes",
    "note",
    "comment",
    "description",
    "state",
    "st"
]

# Completed trade states.
COMPLETED_BUY_STATES = {
    "buy",
    "bought",
    "purchased",
    "complete_buy",
    "completed_buy"
}

COMPLETED_SELL_STATES = {
    "sell",
    "sold",
    "sale",
    "complete_sell",
    "completed_sell"
}

# Cancelled offers can still contain a completed quantity.
# Example: CANCELLED_BUY with cQIT=97 means 97 items were bought before cancellation.
PARTIAL_BUY_STATES = {
    "cancelled_buy",
    "canceled_buy"
}

PARTIAL_SELL_STATES = {
    "cancelled_sell",
    "canceled_sell"
}

# Live/open offers. Do not import these as completed trade events.
IGNORED_OPEN_STATES = {
    "buying",
    "selling",
    "open",
    "pending"
}


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    return sqlite3.connect(DB_FILE)


def column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    return column_name in [row[1] for row in cursor.fetchall()]


def add_column_if_missing(cursor, table_name, column_name, column_definition):
    if not column_exists(cursor, table_name, column_name):
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )


def init_import_db():
    init_trade_db()
    os.makedirs(IMPORT_DIR, exist_ok=True)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS imported_trade_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE NOT NULL,
            file_name TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            modified_time REAL NOT NULL,
            imported_at TEXT NOT NULL,
            imported_rows INTEGER NOT NULL,
            skipped_rows INTEGER NOT NULL,
            matched_rows INTEGER NOT NULL,
            status TEXT NOT NULL,
            message TEXT
        )
    """)

    conn.commit()
    conn.close()


def normalize_key(key):
    return str(key).strip().replace(" ", "_").replace("-", "_").lower()


def normalize_row_keys(row):
    return {
        normalize_key(key): value
        for key, value in row.items()
    }


def pick(row, possible_keys, default=None):
    normalized = normalize_row_keys(row)

    for key in possible_keys:
        normalized_key = normalize_key(key)

        if normalized_key in normalized:
            value = normalized[normalized_key]

            if value is not None and str(value).strip() != "":
                return value

    return default


def clean_number(value):
    if value is None:
        return None

    text = str(value).strip()

    if text == "":
        return None

    text = (
        text.replace(",", "")
        .replace("gp", "")
        .replace("GP", "")
        .replace("_", "")
        .strip()
    )

    return int(float(text))


def normalize_state_text(value):
    if value is None:
        return ""

    return str(value).strip().replace(" ", "_").replace("-", "_").lower()


def normalize_side_value(value, quantity=None):
    """
    Converts trade state/type values into BUY or SELL.

    Imported:
    - BOUGHT
    - SOLD
    - CANCELLED_BUY if completed quantity > 0
    - CANCELLED_SELL if completed quantity > 0

    Ignored:
    - BUYING
    - SELLING
    - cancelled states with quantity 0
    """
    text = normalize_state_text(value)

    if text in IGNORED_OPEN_STATES:
        return None

    if text in COMPLETED_BUY_STATES:
        return "BUY"

    if text in COMPLETED_SELL_STATES:
        return "SELL"

    parsed_quantity = 0

    try:
        parsed_quantity = clean_number(quantity) if quantity is not None else 0
    except Exception:
        parsed_quantity = 0

    if text in PARTIAL_BUY_STATES and parsed_quantity > 0:
        return "BUY"

    if text in PARTIAL_SELL_STATES and parsed_quantity > 0:
        return "SELL"

    return None


def normalize_time(value):
    if value is None:
        return now_utc()

    text = str(value).strip()

    if text == "":
        return now_utc()

    # Epoch seconds or milliseconds.
    if text.replace(".", "", 1).isdigit():
        number = float(text)

        if number > 10_000_000_000:
            number = number / 1000

        return datetime.fromtimestamp(number, timezone.utc).isoformat()

    # Compatible RuneLite trade-history CSV format:
    # 2026-06-25 09:16 AM
    known_formats = [
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M"
    ]

    for time_format in known_formats:
        try:
            parsed = datetime.strptime(text, time_format)
            parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.isoformat()
        except ValueError:
            pass

    # Keep ISO-like strings as-is.
    return text


def make_external_id(file_path, row_index, row):
    explicit = pick(row, EXTERNAL_ID_KEYS)

    if explicit is not None:
        return f"{Path(file_path).name}|{explicit}"

    item_name = pick(row, ITEM_NAME_KEYS, "unknown_item")
    quantity = pick(row, QUANTITY_KEYS, "unknown_qty")
    side = normalize_side_value(
        pick(row, SIDE_KEYS, "unknown_side"),
        quantity=quantity
    ) or "ignored"
    price_each = pick(row, PRICE_KEYS, "unknown_price")
    traded_at = normalize_time(pick(row, TIME_KEYS, "unknown_time"))

    return (
        f"{Path(file_path).name}|row-{row_index}|"
        f"{item_name}|{side}|{price_each}|{quantity}|{traded_at}"
    )


def row_to_trade_event(row, file_path, row_index, source):
    item_name = pick(row, ITEM_NAME_KEYS)
    item_id = pick(row, ITEM_ID_KEYS)
    raw_state = pick(row, SIDE_KEYS)
    price_each = pick(row, PRICE_KEYS)
    quantity = pick(row, QUANTITY_KEYS)

    side = normalize_side_value(raw_state, quantity=quantity)

    traded_at = normalize_time(pick(row, TIME_KEYS))
    external_id = make_external_id(file_path, row_index, row)
    notes = pick(row, NOTES_KEYS)

    state_text = normalize_state_text(raw_state)

    if state_text in IGNORED_OPEN_STATES:
        raise ValueError(f"Ignored live/open offer state: {raw_state}")

    if state_text in PARTIAL_BUY_STATES.union(PARTIAL_SELL_STATES):
        try:
            parsed_quantity = clean_number(quantity)
        except Exception:
            parsed_quantity = 0

        if parsed_quantity <= 0:
            raise ValueError(f"Ignored cancelled offer with zero completed quantity: {raw_state}")

    if item_name is None:
        raise ValueError("Missing item name")

    if side is None:
        raise ValueError(f"Missing or unsupported completed side/state: {raw_state}")

    if price_each is None:
        raise ValueError("Missing price_each/price")

    if quantity is None:
        raise ValueError("Missing quantity/qty")

    price_each = clean_number(price_each)
    quantity = clean_number(quantity)

    if quantity <= 0:
        raise ValueError("Ignored zero-quantity trade")

    if item_id is not None:
        item_id = clean_number(item_id)

    return record_trade_event(
        item_name=item_name,
        item_id=item_id,
        side=side,
        price_each=price_each,
        quantity=quantity,
        traded_at=traded_at,
        source=source,
        external_id=external_id,
        notes=notes,
        raw_payload=row
    )


def is_probable_trade_row(row):
    if not isinstance(row, dict):
        return False

    has_item = pick(row, ITEM_NAME_KEYS) is not None
    has_price = pick(row, PRICE_KEYS) is not None
    has_quantity = pick(row, QUANTITY_KEYS) is not None
    has_side_or_state = pick(row, SIDE_KEYS) is not None

    return has_item and has_price and has_quantity and has_side_or_state


def is_runelite_trade_history_json(data):
    if not isinstance(data, dict):
        return False

    trades = data.get("trades")

    if not isinstance(trades, list):
        return False

    for trade in trades[:10]:
        if isinstance(trade, dict) and "h" in trade and "name" in trade:
            return True

    return False


def extract_runelite_trade_history_records(data):
    """
    Extract completed/partially completed offers from OSRSFlipper RuneLite
    telemetry. The telemetry intentionally keeps the historical lastOffers /
    trades shape that this importer already understood, so older exported JSON
    files can still be imported while the live source moves to our plugin.

    Expected shape:
    {
      "version": 1,
      "lastOffers": {...},
      "trades": [
        {
          "id": 2550,
          "name": "Ring of recoil",
          "h": {
            "sO": [
              {"uuid": "...", "b": true, "cQIT": 1000, "p": 989, "t": 1782391982000, "st": "BOUGHT"}
            ]
          }
        }
      ]
    }
    """
    records = []

    for trade in data.get("trades", []):
        if not isinstance(trade, dict):
            continue

        item_id = trade.get("id")
        item_name = trade.get("name")
        history = trade.get("h") or {}
        offers = history.get("sO") or []

        for offer in offers:
            if not isinstance(offer, dict):
                continue

            state = offer.get("st")
            quantity = offer.get("cQIT")

            record = {
                "item_id": item_id,
                "item_name": item_name,
                "state": state,
                "side": state,
                "price_each": offer.get("p"),
                "quantity": quantity,
                "traded_at": offer.get("t"),
                "external_id": offer.get("uuid"),
                "slot": offer.get("s"),
                "is_buy": offer.get("b"),
                "total_quantity_in_trade": offer.get("tQIT"),
                "total_spent_for_offer": offer.get("tSFO"),
                "total_amount_active": offer.get("tAA"),
                "trade_started_at": offer.get("tradeStartedAt"),
                "before_login": offer.get("beforeLogin"),
                "raw_state": state
            }

            records.append(record)

    return records


def extract_json_records(data):
    if is_runelite_trade_history_json(data):
        return extract_runelite_trade_history_records(data)

    records = []

    if isinstance(data, list):
        for item in data:
            records.extend(extract_json_records(item))

    elif isinstance(data, dict):
        if is_probable_trade_row(data):
            records.append(data)
        else:
            for key, value in data.items():
                if str(key).lower() in (
                    "trades",
                    "trade_events",
                    "events",
                    "history",
                    "offers",
                    "transactions",
                    "items",
                    "data"
                ):
                    records.extend(extract_json_records(value))

    return records


def load_csv_records(file_path):
    """
    Supports normal CSV and compatible RuneLite trade-history CSV exports.
    Some RuneLite exports include comment lines like:
    # Displaying trades...
    # Total profit...

    Those lines are skipped before DictReader sees the header.
    """
    filtered_lines = []

    with open(file_path, "r", encoding="utf-8-sig", newline="") as file:
        for line in file:
            stripped = line.strip()

            if stripped == "":
                continue

            if stripped.startswith("#"):
                continue

            filtered_lines.append(line)

    if not filtered_lines:
        return []

    reader = csv.DictReader(filtered_lines)
    return list(reader)


def load_json_records(file_path):
    with open(file_path, "r", encoding="utf-8-sig") as file:
        data = json.load(file)

    return extract_json_records(data)


def load_jsonl_records(file_path):
    records = []

    with open(file_path, "r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSONL on line {line_number}: {error}"
                ) from error

            records.extend(extract_json_records(data))

    return records


def load_records(file_path):
    extension = Path(file_path).suffix.lower()

    if extension == ".csv":
        return load_csv_records(file_path)

    if extension == ".json":
        return load_json_records(file_path)

    if extension == ".jsonl":
        return load_jsonl_records(file_path)

    raise ValueError(
        f"Unsupported file type: {extension}. "
        "Use .csv, .json, or .jsonl."
    )


def file_already_imported(file_path):
    file_path = str(Path(file_path).resolve())
    stat = os.stat(file_path)

    conn = get_connection()
    cursor = conn.cursor()

    # Only skip files that previously imported at least one row.
    # Use --force or watch-runelite to re-read a file after it changes.
    cursor.execute("""
        SELECT id
        FROM imported_trade_files
        WHERE file_path = ?
          AND file_size = ?
          AND modified_time = ?
          AND status = 'IMPORTED'
          AND imported_rows > 0
    """, (
        file_path,
        stat.st_size,
        stat.st_mtime
    ))

    row = cursor.fetchone()
    conn.close()

    return row is not None


def mark_file_imported(file_path, result, status="IMPORTED", message=None):
    file_path = str(Path(file_path).resolve())
    stat = os.stat(file_path)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO imported_trade_files (
            file_path,
            file_name,
            file_size,
            modified_time,
            imported_at,
            imported_rows,
            skipped_rows,
            matched_rows,
            status,
            message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        file_path,
        Path(file_path).name,
        stat.st_size,
        stat.st_mtime,
        now_utc(),
        result.get("imported", 0),
        result.get("skipped", 0),
        result.get("matched", 0),
        status,
        message
    ))

    conn.commit()
    conn.close()


def import_file(file_path, source="runelite", force=False, quiet_duplicates=True):
    init_import_db()

    file_path = str(Path(file_path).resolve())

    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    extension = Path(file_path).suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        return {
            "file": file_path,
            "imported": 0,
            "skipped": 1,
            "duplicates": 0,
            "ignored": 0,
            "matched": 0,
            "message": f"Skipped unsupported file type: {extension}"
        }

    if not force and file_already_imported(file_path):
        return {
            "file": file_path,
            "imported": 0,
            "skipped": 0,
            "duplicates": 0,
            "ignored": 0,
            "matched": 0,
            "message": "Already imported"
        }

    try:
        records = load_records(file_path)
    except Exception as error:
        result = {
            "file": file_path,
            "imported": 0,
            "skipped": 1,
            "duplicates": 0,
            "ignored": 0,
            "matched": 0,
            "message": f"Could not read file: {error}"
        }

        mark_file_imported(
            file_path=file_path,
            result=result,
            status="FAILED",
            message=result["message"]
        )

        return result

    imported = 0
    skipped = 0
    duplicates = 0
    matched = 0
    ignored = 0

    # Sort by normalized time so buys are usually seen before sells.
    records.sort(key=lambda row: normalize_time(pick(row, TIME_KEYS, "")))

    for index, row in enumerate(records, start=1):
        try:
            result = row_to_trade_event(
                row=row,
                file_path=file_path,
                row_index=index,
                source=source
            )

            if result.get("inserted"):
                imported += 1
                matched += result.get("matched_count", 0)
            else:
                duplicates += 1
                skipped += 1

        except Exception as error:
            message = str(error)

            if (
                "Ignored live/open offer state" in message
                or "Ignored cancelled offer with zero completed quantity" in message
                or "Ignored zero-quantity trade" in message
            ):
                ignored += 1
            else:
                if not quiet_duplicates:
                    print(f"Skipped row {index} in {Path(file_path).name}: {error}")

            skipped += 1

    result = {
        "file": file_path,
        "records_found": len(records),
        "imported": imported,
        "skipped": skipped,
        "duplicates": duplicates,
        "ignored": ignored,
        "matched": matched,
        "message": "Imported"
    }

    mark_file_imported(
        file_path=file_path,
        result=result,
        status="IMPORTED",
        message=(
            f"Imported. Duplicates: {duplicates}. "
            f"Ignored live/open/zero rows: {ignored}."
        )
    )

    return result


def should_consider_file(path):
    if not path.is_file():
        return False

    if path.name.upper().startswith("README"):
        return False

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return False

    return True


def find_import_files(folder):
    folder = Path(folder)

    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)

    files = [
        path for path in folder.iterdir()
        if should_consider_file(path)
    ]

    files.sort(key=lambda path: path.stat().st_mtime)

    return files


def import_folder(folder=IMPORT_DIR, source="runelite", force=False):
    init_import_db()

    results = []

    for file_path in find_import_files(folder):
        try:
            result = import_file(
                file_path=file_path,
                source=source,
                force=force
            )
        except Exception as error:
            result = {
                "file": str(file_path),
                "imported": 0,
                "skipped": 1,
                "duplicates": 0,
                "ignored": 0,
                "matched": 0,
                "message": f"Import failed but watcher continued: {error}"
            }

        results.append(result)

    return results


def print_result(result):
    print(
        f"{Path(result['file']).name}: "
        f"records {result.get('records_found', 0)}, "
        f"new {result.get('imported', 0)}, "
        f"duplicates {result.get('duplicates', 0)}, "
        f"ignored {result.get('ignored', 0)}, "
        f"matched {result.get('matched', 0)} | "
        f"{result.get('message', '')}"
    )


def watch_folder(folder=IMPORT_DIR, source="runelite", seconds=10):
    print("\n==============================")
    print(" OSRS Trade Import Watcher")
    print("==============================")
    print(f"Watching folder: {folder}")
    print("Supported import files: .csv, .json, .jsonl")
    print("Press CTRL+C to stop.")
    print()

    init_import_db()

    while True:
        try:
            results = import_folder(
                folder=folder,
                source=source,
                force=False
            )

            for result in results:
                if result["message"] != "Already imported":
                    print_result(result)

            time.sleep(seconds)

        except KeyboardInterrupt:
            print("\nWatcher stopped.")
            break

        except Exception as error:
            print(f"Watcher error, retrying in {seconds} seconds: {error}")
            time.sleep(seconds)


def get_osrsflipper_runelite_state_path():
    return resolve_runelite_state_path()


def resolve_runelite_file(file_path=None, account=None):
    if file_path:
        resolved = Path(os.path.expandvars(os.path.expanduser(file_path)))
        return str(resolved.resolve())

    resolved = get_osrsflipper_runelite_state_path()

    if resolved.exists():
        return str(resolved)

    account_note = f" for account {account}" if account else ""
    raise FileNotFoundError(
        f"Could not find OSRSFlipper RuneLite telemetry JSON{account_note}: {resolved}. "
        f"Start the OSRSFlipper Telemetry RuneLite plugin and wait for {DEFAULT_RUNELITE_STATE_PATH}. "
        f"Existing legacy installs are also checked at {LEGACY_RUNELITE_STATE_PATH}."
    )


def import_runelite_file(file_path=None, account=None, force=True):
    if account:
        apply_account_env(osrs_account_name=account)

    resolved = resolve_runelite_file(file_path=file_path, account=account)

    return import_file(
        file_path=resolved,
        source=RUNELITE_TELEMETRY_SOURCE,
        force=force
    )


def watch_runelite(file_path=None, account=None, seconds=10):
    if account:
        apply_account_env(osrs_account_name=account)

    resolved = resolve_runelite_file(file_path=file_path, account=account)

    print("\n==============================")
    print(" OSRS RuneLite Trade Watcher")
    print("==============================")
    print(f"Watching OSRSFlipper RuneLite telemetry file: {resolved}")
    print("Press CTRL+C to stop.")
    print()
    print("Tip: the OSRSFlipper Telemetry plugin writes this file from RuneLite.")
    print("If no new trades appear, make sure the plugin is enabled and RuneLite is logged in.")
    print()

    last_modified = None
    last_size = None

    while True:
        try:
            stat = os.stat(resolved)
            modified = stat.st_mtime
            size = stat.st_size

            if modified != last_modified or size != last_size:
                result = import_file(
                    file_path=resolved,
                    source=RUNELITE_TELEMETRY_SOURCE,
                    force=True
                )

                print_result(result)

                last_modified = modified
                last_size = size

            time.sleep(seconds)

        except KeyboardInterrupt:
            print("\nRuneLite watcher stopped.")
            break

        except Exception as error:
            print(f"RuneLite watcher error, retrying in {seconds} seconds: {error}")
            time.sleep(seconds)


def create_readme(folder=IMPORT_DIR):
    os.makedirs(folder, exist_ok=True)

    readme_path = Path(folder) / "README_IMPORT_FORMAT.txt"

    content = f"""OSRSFlipper Trade Import Folder

Drop CSV, JSON, or JSONL trade export files into this folder.

Direct OSRSFlipper RuneLite telemetry JSON is supported.

Default live RuneLite telemetry file:
{OSRSFLIPPER_RUNELITE_STATE_PATH}

Commands:

Import this folder:
python trade_importer.py import-folder --force

Import your live RuneLite file automatically:
python trade_importer.py import-runelite --account DeadArrow98

Watch your live RuneLite file automatically:
python trade_importer.py watch-runelite --account DeadArrow98

RuneLite telemetry states:
- BOUGHT imports as BUY
- SOLD imports as SELL
- CANCELLED_BUY imports as BUY only when completed quantity is greater than 0
- CANCELLED_SELL imports as SELL only when completed quantity is greater than 0
- BUYING and SELLING are ignored because they are still open
"""

    readme_path.write_text(content, encoding="utf-8")

    return readme_path


def main():
    parser = argparse.ArgumentParser(
        description="Import RuneLite/OSRSFlipper telemetry trade exports into OSRSFlipper."
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Create import folder and tracking table.")

    file_parser = subparsers.add_parser("import-file", help="Import one CSV/JSON/JSONL file.")
    file_parser.add_argument("file", help="File path.")
    file_parser.add_argument("--source", default="runelite")
    file_parser.add_argument("--force", action="store_true")

    folder_parser = subparsers.add_parser("import-folder", help="Import all supported files in folder.")
    folder_parser.add_argument("--folder", default=IMPORT_DIR)
    folder_parser.add_argument("--source", default="runelite")
    folder_parser.add_argument("--force", action="store_true")

    watch_parser = subparsers.add_parser("watch", help="Watch folder and auto-import new files.")
    watch_parser.add_argument("--folder", default=IMPORT_DIR)
    watch_parser.add_argument("--source", default="runelite")
    watch_parser.add_argument("--seconds", type=int, default=10)

    import_runelite_parser = subparsers.add_parser(
        "import-runelite",
        help="Import the live OSRSFlipper RuneLite telemetry JSON file."
    )
    import_runelite_parser.add_argument("--file", default=None, help="Direct path to telemetry JSON.")
    import_runelite_parser.add_argument("--account", default=None, help="Account scope to apply before importing.")

    watch_runelite_parser = subparsers.add_parser(
        "watch-runelite",
        help="Watch the live OSRSFlipper RuneLite telemetry JSON file."
    )
    watch_runelite_parser.add_argument("--file", default=None, help="Direct path to telemetry JSON.")
    watch_runelite_parser.add_argument("--account", default=None, help="Account scope to apply before watching.")
    watch_runelite_parser.add_argument("--seconds", type=int, default=10)

    args = parser.parse_args()

    if args.command == "init":
        init_import_db()
        readme_path = create_readme(IMPORT_DIR)
        print(f"Import folder ready: {IMPORT_DIR}")
        print(f"Created: {readme_path}")
        print(f"RuneLite telemetry file: {OSRSFLIPPER_RUNELITE_STATE_PATH}")

    elif args.command == "import-file":
        result = import_file(
            file_path=args.file,
            source=args.source,
            force=args.force
        )

        print_result(result)

    elif args.command == "import-folder":
        results = import_folder(
            folder=args.folder,
            source=args.source,
            force=args.force
        )

        if not results:
            print("No supported import files found.")

        for result in results:
            print_result(result)

    elif args.command == "watch":
        watch_folder(
            folder=args.folder,
            source=args.source,
            seconds=args.seconds
        )

    elif args.command == "import-runelite":
        result = import_runelite_file(
            file_path=args.file,
            account=args.account,
            force=True
        )

        print_result(result)

    elif args.command == "watch-runelite":
        watch_runelite(
            file_path=args.file,
            account=args.account,
            seconds=args.seconds
        )

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
