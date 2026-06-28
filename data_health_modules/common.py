from __future__ import annotations

import math
import os
import sqlite3
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
SQLITE_TIMEOUT_SECONDS = 60
SQLITE_BUSY_TIMEOUT_MS = 60000
DB_CANDIDATES = [
    "osrs_flip_scanner.db",
    "osrs_flips.db",
    "flips.db",
    "osrsflipper.db",
    "osrs_flipper.db",
    "data/osrs_flip_scanner.db",
    "data/osrs_flips.db",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _connect() -> tuple[sqlite3.Connection, Path]:
    env_path = os.environ.get("OSRSFLIPPER_DB") or os.environ.get("OSRS_DB_PATH")
    candidates: list[Path] = []

    if env_path:
        candidates.append(Path(env_path))

    for name in DB_CANDIDATES:
        candidates.append(BASE_DIR / name)

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            conn = sqlite3.connect(candidate, timeout=SQLITE_TIMEOUT_SECONDS)
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
            return conn, candidate

    db_files = sorted(
        [p for p in BASE_DIR.rglob("*.db") if "backup" not in str(p).lower()],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )

    if db_files:
        conn = sqlite3.connect(db_files[0], timeout=SQLITE_TIMEOUT_SECONDS)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        return conn, db_files[0]

    raise FileNotFoundError("Could not find an OSRSFlipper SQLite database.")


def _fetchone(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = _fetchone(conn, sql, params)
    if row is None:
        return None
    return row[0]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        _scalar(
            conn,
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        )
    )


def _table_names(conn: sqlite3.Connection) -> list[str]:
    return [
        row["name"]
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    ]


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if not _table_exists(conn, table):
        return []

    return [
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({_safe_identifier(table)})").fetchall()
    ]


def _column_map(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    return {name.lower(): name for name in _columns(conn, table)}


def _index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    return bool(
        _scalar(
            conn,
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=? LIMIT 1",
            (index_name,),
        )
    )


def _existing_index_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if not _table_exists(conn, table):
        return []

    out = []
    for index_row in conn.execute(f"PRAGMA index_list({_safe_identifier(table)})").fetchall():
        index_name = index_row["name"]
        cols = [
            col["name"]
            for col in conn.execute(f"PRAGMA index_info({_safe_identifier(index_name)})").fetchall()
        ]
        out.append(", ".join(cols))
    return out


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None

    text = str(value).strip()
    if not text:
        return None

    if text.replace(".", "", 1).isdigit():
        try:
            number = float(text)
            # Old School RuneScape GE timestamps in this project appear as epoch seconds.
            if number > 1000000000:
                return datetime.fromtimestamp(number, tz=timezone.utc)
        except Exception:
            pass

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        pass

    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _metric_date(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    if parsed:
        return parsed.date().isoformat()

    text = str(value or "").strip()
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]

    return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None

    try:
        result = float(str(value).replace(",", "").strip())
    except Exception:
        return None

    if math.isnan(result) or math.isinf(result):
        return None

    return result


def _first_col(cmap: dict[str, str], names: list[str]) -> str | None:
    for name in names:
        if name.lower() in cmap:
            return cmap[name.lower()]

    for lower_name, real_name in cmap.items():
        for name in names:
            if name.lower() in lower_name:
                return real_name

    return None


def _avg(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None]

    if not clean:
        return None

    return sum(clean) / len(clean)


def _stddev(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None]

    if len(clean) < 2:
        return 0.0 if len(clean) == 1 else None

    return statistics.pstdev(clean)


def _trend_value(current_value: float | None, previous_value: float | None) -> tuple[float | None, str]:
    if current_value is None or previous_value is None:
        return None, "not enough data"

    delta = current_value - previous_value

    if abs(delta) < 0.01:
        return delta, "flat"

    return delta, "up" if delta > 0 else "down"


def _date_minus_days(date_text: str | None, days: int) -> str | None:
    parsed = _parse_datetime(date_text)

    if not parsed:
        return None

    return (parsed - timedelta(days=max(1, int(days)))).date().isoformat()


def _date_only(value: Any) -> str | None:
    parsed = _parse_datetime(value)

    if parsed:
        return parsed.date().isoformat()

    text = str(value or "").strip()

    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]

    return None


def _hours_since(value: Any) -> float | None:
    parsed = _parse_datetime(value)

    if not parsed:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600)


def _format_mb(value: float | None) -> str:
    if value is None:
        return "n/a"

    return f"{round(float(value), 2)} MB"
