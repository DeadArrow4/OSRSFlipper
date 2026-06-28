from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import BASE_DIR, _connect


def _backup_dir() -> Path:
    path = BASE_DIR / "backups" / "database"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_database_safety_backup() -> dict[str, Any]:
    source_conn, db_path = _connect()
    backup_conn = None

    try:
        backup_dir = _backup_dir()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{db_path.stem}_safety_backup_{timestamp}{db_path.suffix or '.db'}"
        metadata_path = backup_path.with_suffix(backup_path.suffix + ".txt")

        backup_conn = sqlite3.connect(backup_path)
        source_conn.backup(backup_conn)
        backup_conn.close()
        backup_conn = None

        source_size = db_path.stat().st_size if db_path.exists() else 0
        backup_size = backup_path.stat().st_size if backup_path.exists() else 0

        metadata = [
            "OSRSFlipper database safety backup",
            f"created_at_utc={datetime.now(timezone.utc).isoformat(timespec='seconds')}",
            f"source={db_path}",
            f"backup={backup_path}",
            f"source_size_bytes={source_size}",
            f"backup_size_bytes={backup_size}",
            f"verified_exists={backup_path.exists()}",
        ]
        metadata_path.write_text("\n".join(metadata) + "\n", encoding="utf-8")

        ok = backup_path.exists() and backup_size > 0

        if source_size > 0:
            # sqlite backup API can change size slightly depending on page/free-list
            # state, so this is an informational check rather than exact equality.
            size_note = f"source={round(source_size / 1024 / 1024, 2)} MB, backup={round(backup_size / 1024 / 1024, 2)} MB"
        else:
            size_note = f"backup={round(backup_size / 1024 / 1024, 2)} MB"

        return {
            "ok": ok,
            "status": (
                f"Database safety backup created: {backup_path.name}. {size_note}."
                if ok
                else f"Database safety backup may have failed: {backup_path.name}."
            ),
            "source_path": str(db_path),
            "backup_path": str(backup_path),
            "metadata_path": str(metadata_path),
            "source_size_mb": round(source_size / 1024 / 1024, 2),
            "backup_size_mb": round(backup_size / 1024 / 1024, 2),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    finally:
        try:
            if backup_conn is not None:
                backup_conn.close()
        finally:
            source_conn.close()


def build_database_backup_snapshot(limit: int = 10) -> dict[str, Any]:
    conn, db_path = _connect()
    conn.close()

    backup_dir = _backup_dir()
    limit_int = max(1, min(int(limit or 10), 100))

    files = sorted(
        [path for path in backup_dir.glob("*.db") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    rows = []

    for path in files[:limit_int]:
        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        metadata_path = path.with_suffix(path.suffix + ".txt")

        rows.append(
            {
                "Backup File": path.name,
                "Size": f"{round(stat.st_size / 1024 / 1024, 2)} MB",
                "Modified UTC": modified,
                "Metadata": "yes" if metadata_path.exists() else "no",
                "Folder": str(path.parent),
                "Status": "exists" if path.exists() and stat.st_size > 0 else "check",
            }
        )

    if rows:
        status = f"Found {len(files)} database backup file(s). Showing latest {len(rows)}."
    else:
        status = "No database safety backups found yet."

    return {
        "ok": True,
        "status": status,
        "source_database": str(db_path),
        "backup_folder": str(backup_dir),
        "rows": rows,
    }


def _latest_safety_backup(max_age_hours: int = 24) -> dict[str, Any]:
    backup_dir = _backup_dir()
    max_age = max(1, int(max_age_hours or 24))

    files = sorted(
        [path for path in backup_dir.glob("*_safety_backup_*.db") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not files:
        return {
            "ok": False,
            "status": "No database safety backup was found.",
            "backup_path": "",
            "backup_age_hours": None,
            "backup_size_mb": None,
            "max_age_hours": max_age,
        }

    latest = files[0]
    stat = latest.stat()
    age_hours = max(0.0, (datetime.now(timezone.utc) - datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)).total_seconds() / 3600)
    size_mb = round(stat.st_size / 1024 / 1024, 2)
    ok = latest.exists() and stat.st_size > 0 and age_hours <= max_age

    if ok:
        status = f"Fresh safety backup found: {latest.name} ({round(age_hours, 2)} hour(s) old, {size_mb} MB)."
    else:
        status = f"Latest safety backup is not fresh enough: {latest.name} ({round(age_hours, 2)} hour(s) old, {size_mb} MB)."

    return {
        "ok": ok,
        "status": status,
        "backup_path": str(latest),
        "backup_file": latest.name,
        "backup_age_hours": round(age_hours, 2),
        "backup_size_mb": size_mb,
        "max_age_hours": max_age,
    }
