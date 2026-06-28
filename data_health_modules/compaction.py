from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backups import _latest_safety_backup
from .common import BASE_DIR, _connect, _format_mb, _scalar
from .maintenance import record_data_maintenance_event

COMPACTION_COPY_CONFIRMATION = "COMPACT DATABASE"


def build_database_compaction_preview_snapshot(record_event: bool = False) -> dict[str, Any]:
    conn, db_path = _connect()

    try:
        page_count = int(_scalar(conn, "PRAGMA page_count") or 0)
        freelist_count = int(_scalar(conn, "PRAGMA freelist_count") or 0)
        page_size = int(_scalar(conn, "PRAGMA page_size") or 4096)
        db_size_mb = round(db_path.stat().st_size / 1024 / 1024, 2) if db_path.exists() else 0.0
        free_mb = round((freelist_count * page_size) / 1024 / 1024, 2)
        estimated_after_mb = round(max(db_size_mb - free_mb, 0), 2)
        free_pct = round((freelist_count / page_count) * 100, 2) if page_count else 0.0

        backup_check = _latest_safety_backup(max_age_hours=24) if " _latest_safety_backup" else {"ok": False}
    except NameError:
        backup_check = {
            "ok": False,
            "status": "Backup guard is unavailable. Apply 1.0.8 database backup patch first.",
            "backup_file": "",
            "backup_age_hours": None,
            "backup_size_mb": None,
        }
    finally:
        conn.close()

    recommendation = "not needed"

    if free_mb >= 250 or free_pct >= 20:
        recommendation = "recommended"
    elif free_mb >= 50 or free_pct >= 10:
        recommendation = "optional"

    rows = [
        {
            "Metric": "Database",
            "Value": db_path.name,
            "Notes": str(db_path),
        },
        {
            "Metric": "Current size",
            "Value": _format_mb(db_size_mb),
            "Notes": "Actual SQLite file size on disk.",
        },
        {
            "Metric": "SQLite page count",
            "Value": f"{page_count:,}",
            "Notes": f"Page size: {page_size:,} bytes.",
        },
        {
            "Metric": "Free pages",
            "Value": f"{freelist_count:,}",
            "Notes": f"{free_pct}% of database pages are free.",
        },
        {
            "Metric": "Estimated reclaimable space",
            "Value": _format_mb(free_mb),
            "Notes": "Based on PRAGMA freelist_count. Actual VACUUM result can vary.",
        },
        {
            "Metric": "Estimated compacted size",
            "Value": _format_mb(estimated_after_mb),
            "Notes": "Rough estimate only; no compaction was run.",
        },
        {
            "Metric": "Recommendation",
            "Value": recommendation,
            "Notes": "Compaction is most useful after guarded cleanup deletes many rows.",
        },
        {
            "Metric": "Fresh backup",
            "Value": "yes" if backup_check.get("ok") else "no",
            "Notes": backup_check.get("status", "Create a safety backup before any future compact action."),
        },
        {
            "Metric": "Safety",
            "Value": "preview only",
            "Notes": "This phase does not run VACUUM or VACUUM INTO.",
        },
    ]

    status = (
        f"Compaction preview complete. Current size {db_size_mb} MB; "
        f"estimated reclaimable space {free_mb} MB ({free_pct}% free pages). "
        f"Recommendation: {recommendation}. No compaction was run."
    )

    if record_event:
        try:
            record_data_maintenance_event(
                event_type="compaction_preview",
                status=recommendation,
                detail=status,
                rows_affected=0,
                db_size_before_mb=db_size_mb,
                db_size_after_mb=estimated_after_mb,
                backup_path=backup_check.get("backup_path", ""),
            )
        except Exception:
            pass

    return {
        "ok": True,
        "status": status,
        "rows": rows,
        "db_size_mb": db_size_mb,
        "free_mb": free_mb,
        "estimated_after_mb": estimated_after_mb,
        "free_pct": free_pct,
        "recommendation": recommendation,
        "backup_check": backup_check,
    }


def _compacted_database_dir() -> Path:
    path = BASE_DIR / "backups" / "database" / "compacted"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _quote_sqlite_path(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def create_compacted_database_copy(
    confirmation_text: str | None = None,
    backup_max_age_hours: int = 24,
) -> dict[str, Any]:
    confirmation = str(confirmation_text or "").strip()

    preview = build_database_compaction_preview_snapshot(record_event=False)
    preview_rows = list(preview.get("rows", []))

    def rows_with_guard(extra_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return extra_rows + preview_rows

    if confirmation != COMPACTION_COPY_CONFIRMATION:
        rows = rows_with_guard(
            [
                {
                    "Metric": "Compaction blocked",
                    "Value": "confirmation required",
                    "Notes": f'Type exactly "{COMPACTION_COPY_CONFIRMATION}" before creating a compacted copy.',
                }
            ]
        )
        return {
            "ok": False,
            "compaction_ran": False,
            "status": f'Compaction blocked: confirmation text must be "{COMPACTION_COPY_CONFIRMATION}".',
            "rows": rows,
            "preview": preview,
        }

    backup_check = _latest_safety_backup(max_age_hours=backup_max_age_hours)

    if not backup_check.get("ok", False):
        rows = rows_with_guard(
            [
                {
                    "Metric": "Compaction blocked",
                    "Value": "fresh backup required",
                    "Notes": backup_check.get("status", "Create a safety backup first."),
                },
                {
                    "Metric": "Required backup age",
                    "Value": f"<= {backup_max_age_hours} hours",
                    "Notes": "Use Database Backup > Create Safety Backup, then retry compaction.",
                },
            ]
        )
        return {
            "ok": False,
            "compaction_ran": False,
            "status": "Compaction blocked: create a fresh database safety backup first.",
            "rows": rows,
            "preview": preview,
            "backup_check": backup_check,
        }

    conn, db_path = _connect()

    try:
        compact_dir = _compacted_database_dir()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        compact_path = compact_dir / f"{db_path.stem}_compacted_{timestamp}{db_path.suffix or '.db'}"
        metadata_path = compact_path.with_suffix(compact_path.suffix + ".txt")

        before_size_bytes = db_path.stat().st_size if db_path.exists() else 0
        before_size_mb = round(before_size_bytes / 1024 / 1024, 2)

        if compact_path.exists():
            compact_path.unlink()

        # VACUUM INTO creates a compacted copy. It does not replace the active
        # database file, which is safer while the Dash app is running.
        conn.execute(f"VACUUM INTO {_quote_sqlite_path(compact_path)}")
    finally:
        conn.close()

    compact_size_bytes = compact_path.stat().st_size if compact_path.exists() else 0
    compact_size_mb = round(compact_size_bytes / 1024 / 1024, 2)
    saved_mb = round(max(before_size_mb - compact_size_mb, 0), 2)

    integrity_status = "not checked"

    compact_conn = None
    try:
        compact_conn = sqlite3.connect(compact_path)
        integrity_status = str(compact_conn.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        if compact_conn is not None:
            compact_conn.close()

    verified = compact_path.exists() and compact_size_bytes > 0 and integrity_status.lower() == "ok"

    metadata = [
        "OSRSFlipper compacted database copy",
        f"created_at_utc={datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"source={db_path}",
        f"compacted_copy={compact_path}",
        f"source_size_bytes={before_size_bytes}",
        f"compacted_size_bytes={compact_size_bytes}",
        f"estimated_saved_mb={saved_mb}",
        f"backup_guard={backup_check.get('backup_path', '')}",
        f"integrity_check={integrity_status}",
        f"verified={verified}",
        "active_database_replaced=false",
    ]
    metadata_path.write_text("\n".join(metadata) + "\n", encoding="utf-8")

    event_status = "created" if verified else "verify_failed"
    detail = (
        f"Compacted database copy created: {compact_path.name}. "
        f"Before={before_size_mb} MB, compacted={compact_size_mb} MB, estimated saved={saved_mb} MB, "
        f"integrity={integrity_status}. Active database was not replaced."
    )

    try:
        record_data_maintenance_event(
            event_type="compaction_copy",
            status=event_status,
            detail=detail,
            rows_affected=0,
            db_size_before_mb=before_size_mb,
            db_size_after_mb=compact_size_mb,
            backup_path=backup_check.get("backup_path", ""),
        )
    except Exception:
        pass

    rows = [
        {
            "Metric": "Compaction action",
            "Value": "compacted copy created" if verified else "copy verification failed",
            "Notes": "Active database was not replaced.",
        },
        {
            "Metric": "Source database",
            "Value": db_path.name,
            "Notes": str(db_path),
        },
        {
            "Metric": "Compacted copy",
            "Value": compact_path.name,
            "Notes": str(compact_path),
        },
        {
            "Metric": "Source size",
            "Value": _format_mb(before_size_mb),
            "Notes": "Active database size before copy.",
        },
        {
            "Metric": "Compacted size",
            "Value": _format_mb(compact_size_mb),
            "Notes": "Compacted copy size.",
        },
        {
            "Metric": "Estimated saved",
            "Value": _format_mb(saved_mb),
            "Notes": "Difference between active DB and compacted copy.",
        },
        {
            "Metric": "Integrity check",
            "Value": integrity_status,
            "Notes": "Compacted copy verification.",
        },
        {
            "Metric": "Safety backup used",
            "Value": backup_check.get("backup_file", ""),
            "Notes": backup_check.get("status", ""),
        },
        {
            "Metric": "Replacement",
            "Value": "not performed",
            "Notes": "Manual replace/swap should only happen when the dashboard is stopped.",
        },
    ]

    return {
        "ok": verified,
        "compaction_ran": True,
        "status": detail if verified else f"Compacted copy was created but verification failed: {integrity_status}.",
        "rows": rows,
        "preview": preview,
        "backup_check": backup_check,
        "compact_path": str(compact_path),
        "metadata_path": str(metadata_path),
        "before_size_mb": before_size_mb,
        "compact_size_mb": compact_size_mb,
        "saved_mb": saved_mb,
        "integrity_status": integrity_status,
    }
