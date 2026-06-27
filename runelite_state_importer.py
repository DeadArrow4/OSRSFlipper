from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from capital_ai_memory import (
    ensure_capital_ai_tables,
    format_gp,
    get_setting,
    print_capital_summary,
    record_capital_snapshot,
    record_runelite_telemetry_import,
    replace_runelite_open_trade_locks,
    score_flip_for_capital,
    summarize_capital_state,
)


DEFAULT_STATE_PATH = Path(__file__).resolve().parent / "runtime" / "runelite_state.json"


def _int_value(payload: dict[str, Any], keys: list[str], default: int = 0) -> int:
    for key in keys:
        if key in payload and payload[key] is not None:
            try:
                return int(payload[key])
            except (TypeError, ValueError):
                return default

    return default


def normalize_offer(raw: dict[str, Any]) -> dict[str, Any] | None:
    item_name = str(raw.get("item_name") or raw.get("itemName") or raw.get("name") or "").strip()

    if not item_name:
        return None

    side = str(raw.get("side") or raw.get("type") or raw.get("offer_type") or raw.get("offerType") or "unknown").lower()

    if "buy" in side:
        side = "buy"
    elif "sell" in side:
        side = "sell"
    else:
        state = str(raw.get("state") or raw.get("status") or "").lower()

        if "buy" in state:
            side = "buy"
        elif "sell" in state:
            side = "sell"
        else:
            side = "unknown"

    price = _int_value(raw, ["offer_price", "price", "limit_price", "limitPrice"], 0)
    quantity_total = _int_value(raw, ["quantity_total", "quantityTotal", "total_quantity", "totalQuantity", "quantity"], 0)
    quantity_filled = _int_value(raw, ["quantity_filled", "quantityFilled", "filled_quantity", "filledQuantity"], 0)

    if "quantity_remaining" in raw or "quantityRemaining" in raw:
        quantity_remaining = _int_value(raw, ["quantity_remaining", "quantityRemaining"], 0)
    else:
        quantity_remaining = max(0, quantity_total - quantity_filled)

    if quantity_total <= 0 and quantity_remaining > 0:
        quantity_total = quantity_remaining + quantity_filled

    if quantity_remaining <= 0:
        return None

    return {
        "slot": raw.get("slot"),
        "item_id": raw.get("item_id") or raw.get("itemId"),
        "item_name": item_name,
        "side": side,
        "offer_price": price,
        "quantity_total": quantity_total,
        "quantity_filled": quantity_filled,
        "quantity_remaining": quantity_remaining,
        "offer_age_minutes": raw.get("offer_age_minutes") or raw.get("offerAgeMinutes"),
        "opened_at": raw.get("opened_at") or raw.get("openedAt"),
        "notes": raw.get("notes"),
    }


def load_runelite_state(path: str | Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    state_path = Path(path).expanduser().resolve()

    if not state_path.exists():
        raise FileNotFoundError(
            f"RuneLite state file not found: {state_path}. "
            "Use runtime/runelite_state.example.json for the expected shape."
        )

    return json.loads(state_path.read_text(encoding="utf-8"))


def import_runelite_state(
    path: str | Path = DEFAULT_STATE_PATH,
    account_name: str | None = None,
    safety_reserve_gp: int | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    ensure_capital_ai_tables(db_path)

    source_path = str(Path(path).expanduser().resolve())
    payload = load_runelite_state(source_path)

    account = account_name or str(payload.get("account_name") or payload.get("accountName") or "default")
    captured_at = payload.get("captured_at") or payload.get("capturedAt")

    inventory_gp = _int_value(payload, ["inventory_gp", "inventoryGp", "cash_stack", "cashStack"], 0)
    bank_gp = _int_value(payload, ["bank_gp", "bankGp"], 0)

    include_bank = str(payload.get("include_bank_gp", "")).strip().lower()

    if include_bank:
        include_bank_gp = include_bank in {"1", "true", "yes", "y", "on"}
    else:
        include_bank_gp = str(get_setting("include_bank_gp_in_raw_available", "true", db_path)).lower() in {
            "1",
            "true",
            "yes",
            "y",
            "on",
        }

    if "raw_gp_available" in payload or "rawGpAvailable" in payload:
        raw_gp_available = _int_value(payload, ["raw_gp_available", "rawGpAvailable"], 0)
    else:
        raw_gp_available = inventory_gp + (bank_gp if include_bank_gp else 0)

    if safety_reserve_gp is None:
        safety_reserve_gp = _int_value(payload, ["safety_reserve_gp", "safetyReserveGp"], -1)

        if safety_reserve_gp < 0:
            safety_reserve_gp = int(get_setting("default_safety_reserve_gp", "0", db_path) or 0)

    active_raw = payload.get("active_ge_offers") or payload.get("activeGeOffers") or payload.get("offers") or []
    offers = []

    for raw_offer in active_raw:
        if not isinstance(raw_offer, dict):
            continue

        normalized = normalize_offer(raw_offer)

        if normalized:
            offers.append(normalized)

    snapshot_id = record_capital_snapshot(
        raw_gp_available=raw_gp_available,
        inventory_gp=inventory_gp,
        bank_gp=bank_gp,
        safety_reserve_gp=safety_reserve_gp,
        account_name=account,
        source="runelite",
        source_path=source_path,
        notes=f"Imported RuneLite telemetry captured_at={captured_at}",
        db_path=db_path,
    )

    imported_locks = replace_runelite_open_trade_locks(
        account_name=account,
        locks=offers,
        source_path=source_path,
        db_path=db_path,
    )

    state = summarize_capital_state(account, db_path)
    import_id = record_runelite_telemetry_import(
        account_name=account,
        source_path=source_path,
        payload=payload,
        capital_state=state,
        captured_at=captured_at,
        db_path=db_path,
    )

    return {
        "ok": True,
        "import_id": import_id,
        "snapshot_id": snapshot_id,
        "account_name": account,
        "captured_at": captured_at,
        "source_path": source_path,
        "inventory_gp": inventory_gp,
        "bank_gp": bank_gp,
        "raw_gp_available": raw_gp_available,
        "imported_offer_count": imported_locks,
        "capital_state": state,
    }


def print_import_result(result: dict[str, Any]) -> None:
    print("RuneLite Telemetry Import")
    print("=" * 72)
    print(f"Import ID:        {result['import_id']}")
    print(f"Snapshot ID:      {result['snapshot_id']}")
    print(f"Account:          {result['account_name']}")
    print(f"Captured at:      {result.get('captured_at')}")
    print(f"Source:           {result['source_path']}")
    print(f"Inventory GP:     {format_gp(result['inventory_gp'])}")
    print(f"Bank GP:          {format_gp(result['bank_gp'])}")
    print(f"Raw GP available: {format_gp(result['raw_gp_available'])}")
    print(f"Offers imported:  {result['imported_offer_count']}")
    print()
    print_capital_summary(result["account_name"])


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import read-only RuneLite telemetry into OSRSFlipper")
    parser.add_argument(
        "--state",
        default=str(DEFAULT_STATE_PATH),
        help="Path to RuneLite telemetry JSON file",
    )
    parser.add_argument("--account", help="Override account name from telemetry file")
    parser.add_argument("--reserve", type=int, help="Safety reserve GP")
    parser.add_argument("--db", help="Optional SQLite database path")

    sub = parser.add_subparsers(dest="command")

    import_cmd = sub.add_parser("import", help="Import RuneLite telemetry")
    import_cmd.set_defaults(command="import")

    summary = sub.add_parser("summary", help="Show imported capital summary")
    summary.set_defaults(command="summary")

    score = sub.add_parser("score", help="Import telemetry, then score a candidate flip")
    score.add_argument("--item", required=True)
    score.add_argument("--buy", type=int, required=True)
    score.add_argument("--sell", type=int, required=True)
    score.add_argument("--quantity", type=int, required=True)
    score.set_defaults(command="score")

    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    command = args.command or "import"

    if command == "import":
        result = import_runelite_state(args.state, args.account, args.reserve, args.db)
        print_import_result(result)
        return 0

    if command == "summary":
        result = import_runelite_state(args.state, args.account, args.reserve, args.db)
        print_capital_summary(result["account_name"], args.db)
        return 0

    if command == "score":
        result = import_runelite_state(args.state, args.account, args.reserve, args.db)
        score = score_flip_for_capital(
            item_name=args.item,
            buy_price=args.buy,
            sell_price=args.sell,
            proposed_quantity=args.quantity,
            account_name=result["account_name"],
            db_path=args.db,
        )

        print_import_result(result)
        print()
        print("Candidate Score After RuneLite Import")
        print("=" * 72)
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
            print("-" * 72)
            for warning in score["warnings"]:
                print(f"- {warning}")

        return 0

    parser.error(f"Unknown command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
