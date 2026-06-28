from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import _connect


def ensure_maintenance_event_schema() -> dict[str, Any]:
    conn, db_path = _connect()

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS data_maintenance_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT,
                rows_affected INTEGER DEFAULT 0,
                db_size_before_mb REAL,
                db_size_after_mb REAL,
                backup_path TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_data_maintenance_events_created_at
            ON data_maintenance_events (created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_data_maintenance_events_type_status
            ON data_maintenance_events (event_type, status)
            """
        )
        conn.commit()

        return {
            "ok": True,
            "status": "Maintenance event schema is ready.",
            "database_path": str(db_path),
        }
    finally:
        conn.close()


def record_data_maintenance_event(
    event_type: str,
    status: str,
    detail: str = "",
    rows_affected: int | None = 0,
    db_size_before_mb: float | None = None,
    db_size_after_mb: float | None = None,
    backup_path: str | None = None,
) -> dict[str, Any]:
    schema_result = ensure_maintenance_event_schema()
    conn, db_path = _connect()

    try:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        conn.execute(
            """
            INSERT INTO data_maintenance_events (
                event_type,
                status,
                detail,
                rows_affected,
                db_size_before_mb,
                db_size_after_mb,
                backup_path,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(event_type or "unknown"),
                str(status or "unknown"),
                str(detail or "")[:1000],
                int(rows_affected or 0),
                db_size_before_mb,
                db_size_after_mb,
                str(backup_path or ""),
                now,
            ),
        )
        conn.commit()

        return {
            "ok": True,
            "status": "Maintenance event recorded.",
            "database_path": str(db_path),
            "created_at": now,
            "schema_result": schema_result,
        }
    finally:
        conn.close()


def build_maintenance_events_snapshot(limit: int = 25) -> dict[str, Any]:
    ensure_maintenance_event_schema()
    conn, db_path = _connect()

    try:
        limit_int = max(1, min(int(limit or 25), 200))

        rows = conn.execute(
            """
            SELECT
                id,
                event_type,
                status,
                detail,
                rows_affected,
                db_size_before_mb,
                db_size_after_mb,
                backup_path,
                created_at
            FROM data_maintenance_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit_int,),
        ).fetchall()

        out = [
            {
                "ID": row["id"],
                "Event Type": row["event_type"],
                "Status": row["status"],
                "Detail": row["detail"],
                "Rows Affected": row["rows_affected"],
                "DB Before MB": row["db_size_before_mb"],
                "DB After MB": row["db_size_after_mb"],
                "Backup": Path(row["backup_path"]).name if row["backup_path"] else "",
                "Created UTC": row["created_at"],
            }
            for row in rows
        ]

        return {
            "ok": True,
            "status": f"Loaded {len(out)} maintenance event(s).",
            "database_path": str(db_path),
            "rows": out,
        }
    finally:
        conn.close()
