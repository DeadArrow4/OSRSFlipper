from __future__ import annotations

from typing import Any

from .backups import _latest_safety_backup
from .common import (
    _columns,
    _connect,
    _date_minus_days,
    _date_only,
    _format_mb,
    _scalar,
    _table_exists,
)
from .metrics import rebuild_daily_item_metrics

RETENTION_CLEANUP_CONFIRMATION = "DELETE OLD SCANS"


def build_retention_preview_snapshot(retention_days: int | str | None = 90) -> dict[str, Any]:
    conn, db_path = _connect()

    try:
        if not _table_exists(conn, "scan_results"):
            return {
                "ok": False,
                "status": "scan_results table was not found. No retention preview is available.",
                "rows": [
                    {
                        "Metric": "scan_results",
                        "Value": "missing",
                        "Notes": "No raw scanner table was found.",
                    }
                ],
            }

        if "scanned_at" not in _columns(conn, "scan_results"):
            return {
                "ok": False,
                "status": "scan_results.scanned_at was not found. No retention preview is available.",
                "rows": [
                    {
                        "Metric": "scan_results.scanned_at",
                        "Value": "missing",
                        "Notes": "Retention preview requires scanned_at.",
                    }
                ],
            }

        try:
            days_int = int(retention_days or 0)
        except Exception:
            days_int = 0

        days_int = max(0, min(days_int, 3650))

        total_rows = int(_scalar(conn, "SELECT COUNT(*) FROM scan_results") or 0)
        oldest_scan = _scalar(conn, "SELECT MIN(scanned_at) FROM scan_results WHERE scanned_at IS NOT NULL AND TRIM(CAST(scanned_at AS TEXT)) <> ''")
        newest_scan = _scalar(conn, "SELECT MAX(scanned_at) FROM scan_results WHERE scanned_at IS NOT NULL AND TRIM(CAST(scanned_at AS TEXT)) <> ''")
        distinct_days = int(
            _scalar(
                conn,
                """
                SELECT COUNT(DISTINCT substr(CAST(scanned_at AS TEXT), 1, 10))
                FROM scan_results
                WHERE scanned_at IS NOT NULL
                  AND TRIM(CAST(scanned_at AS TEXT)) <> ''
                """
            )
            or 0
        )

        db_size_mb = round(db_path.stat().st_size / 1024 / 1024, 2) if db_path.exists() else 0.0

        if days_int <= 0:
            rows = [
                {
                    "Metric": "Retention mode",
                    "Value": "Keep forever",
                    "Notes": "No rows would be removed.",
                },
                {
                    "Metric": "scan_results rows",
                    "Value": f"{total_rows:,}",
                    "Notes": "All raw scan rows would be retained.",
                },
                {
                    "Metric": "Scan date coverage",
                    "Value": f"{distinct_days} day(s)",
                    "Notes": f"{oldest_scan or ''} -> {newest_scan or ''}",
                },
                {
                    "Metric": "Database size",
                    "Value": _format_mb(db_size_mb),
                    "Notes": "Preview only. Database is not changed.",
                },
            ]

            return {
                "ok": True,
                "status": "Retention preview: Keep forever selected. No raw scan rows would be removed.",
                "rows": rows,
                "would_delete_rows": 0,
                "would_keep_rows": total_rows,
                "retention_days": days_int,
                "cutoff_date": "",
            }

        newest_date = _date_only(newest_scan)
        cutoff_date = _date_minus_days(newest_date, days_int) if newest_date else None

        if not cutoff_date:
            return {
                "ok": False,
                "status": "Retention preview could not determine a cutoff date from the newest scan.",
                "rows": [
                    {
                        "Metric": "Newest scan",
                        "Value": newest_scan or "",
                        "Notes": "Could not parse newest scan date.",
                    }
                ],
            }

        delete_rows = int(
            _scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM scan_results
                WHERE scanned_at IS NOT NULL
                  AND substr(CAST(scanned_at AS TEXT), 1, 10) < ?
                """,
                (cutoff_date,),
            )
            or 0
        )
        keep_rows = max(total_rows - delete_rows, 0)

        newest_deleted_scan = None
        oldest_retained_scan = None

        if delete_rows:
            newest_deleted_scan = _scalar(
                conn,
                """
                SELECT MAX(scanned_at)
                FROM scan_results
                WHERE scanned_at IS NOT NULL
                  AND substr(CAST(scanned_at AS TEXT), 1, 10) < ?
                """,
                (cutoff_date,),
            )

        if keep_rows:
            oldest_retained_scan = _scalar(
                conn,
                """
                SELECT MIN(scanned_at)
                FROM scan_results
                WHERE scanned_at IS NOT NULL
                  AND substr(CAST(scanned_at AS TEXT), 1, 10) >= ?
                """,
                (cutoff_date,),
            )

        delete_pct = round((delete_rows / total_rows) * 100, 2) if total_rows else 0.0
        keep_pct = round((keep_rows / total_rows) * 100, 2) if total_rows else 0.0

        estimated_raw_scan_mb = None
        estimated_deleted_mb = None
        estimated_remaining_mb = None

        if total_rows:
            # This is intentionally conservative/rough. SQLite file size will
            # not fully shrink until vacuum/backup compaction, so call it impact,
            # not guaranteed immediate disk savings.
            estimated_raw_scan_mb = db_size_mb * min(1.0, total_rows / max(total_rows, 1))
            estimated_deleted_mb = db_size_mb * (delete_rows / total_rows)
            estimated_remaining_mb = max(db_size_mb - estimated_deleted_mb, 0)

        rows = [
            {
                "Metric": "Retention mode",
                "Value": f"Keep last {days_int} day(s)",
                "Notes": "Preview only. No rows are deleted.",
            },
            {
                "Metric": "Cutoff date",
                "Value": cutoff_date,
                "Notes": f"Rows before this date would be candidates for cleanup.",
            },
            {
                "Metric": "scan_results rows",
                "Value": f"{total_rows:,}",
                "Notes": f"{distinct_days} scan day(s): {oldest_scan or ''} -> {newest_scan or ''}",
            },
            {
                "Metric": "Rows that would be removed",
                "Value": f"{delete_rows:,}",
                "Notes": f"{delete_pct}% of scan_results.",
            },
            {
                "Metric": "Rows that would be retained",
                "Value": f"{keep_rows:,}",
                "Notes": f"{keep_pct}% of scan_results.",
            },
            {
                "Metric": "Newest deleted scan",
                "Value": newest_deleted_scan or "",
                "Notes": "Newest raw scan row that would be removed.",
            },
            {
                "Metric": "Oldest retained scan",
                "Value": oldest_retained_scan or "",
                "Notes": "Oldest raw scan row that would remain.",
            },
            {
                "Metric": "Current database size",
                "Value": _format_mb(db_size_mb),
                "Notes": str(db_path.name),
            },
            {
                "Metric": "Estimated impacted size",
                "Value": _format_mb(estimated_deleted_mb),
                "Notes": "Rough estimate. SQLite may require VACUUM/backup compaction to reclaim file space.",
            },
            {
                "Metric": "Safety",
                "Value": "Preview only",
                "Notes": "This release phase does not delete, vacuum, or compact anything.",
            },
        ]

        status = (
            f"Retention preview complete. Keep last {days_int} day(s): "
            f"{delete_rows:,} scan_results row(s) would be removable and {keep_rows:,} would remain. "
            "No rows were deleted."
        )

        if delete_rows == 0:
            status = (
                f"Retention preview complete. Keep last {days_int} day(s): no raw scan rows are old enough to remove. "
                "No rows were deleted."
            )

        return {
            "ok": True,
            "status": status,
            "rows": rows,
            "would_delete_rows": delete_rows,
            "would_keep_rows": keep_rows,
            "delete_pct": delete_pct,
            "keep_pct": keep_pct,
            "retention_days": days_int,
            "cutoff_date": cutoff_date,
            "estimated_deleted_mb": estimated_deleted_mb,
            "estimated_remaining_mb": estimated_remaining_mb,
        }
    finally:
        conn.close()


def cleanup_scan_results_with_backup_guard(
    retention_days: int | str | None = 90,
    confirmation_text: str | None = None,
    backup_max_age_hours: int = 24,
) -> dict[str, Any]:
    confirmation = str(confirmation_text or "").strip()

    try:
        days_int = int(retention_days or 0)
    except Exception:
        days_int = 0

    days_int = max(0, min(days_int, 3650))

    preview = build_retention_preview_snapshot(retention_days=days_int)
    preview_rows = list(preview.get("rows", []))

    def rows_with_guard(extra_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return extra_rows + preview_rows

    if days_int <= 0:
        rows = rows_with_guard(
            [
                {
                    "Metric": "Cleanup blocked",
                    "Value": "Keep forever selected",
                    "Notes": "Choose a retention window before cleanup can run.",
                }
            ]
        )
        return {
            "ok": False,
            "cleanup_ran": False,
            "deleted_rows": 0,
            "status": "Cleanup blocked: Keep forever is selected.",
            "rows": rows,
            "preview": preview,
        }

    if confirmation != RETENTION_CLEANUP_CONFIRMATION:
        rows = rows_with_guard(
            [
                {
                    "Metric": "Cleanup blocked",
                    "Value": "confirmation required",
                    "Notes": f'Type exactly "{RETENTION_CLEANUP_CONFIRMATION}" before cleanup can run.',
                }
            ]
        )
        return {
            "ok": False,
            "cleanup_ran": False,
            "deleted_rows": 0,
            "status": f'Cleanup blocked: confirmation text must be "{RETENTION_CLEANUP_CONFIRMATION}".',
            "rows": rows,
            "preview": preview,
        }

    if not preview.get("ok", False):
        rows = rows_with_guard(
            [
                {
                    "Metric": "Cleanup blocked",
                    "Value": "preview failed",
                    "Notes": preview.get("status", "Retention preview was not successful."),
                }
            ]
        )
        return {
            "ok": False,
            "cleanup_ran": False,
            "deleted_rows": 0,
            "status": "Cleanup blocked: retention preview failed.",
            "rows": rows,
            "preview": preview,
        }

    would_delete_rows = int(preview.get("would_delete_rows") or 0)

    if would_delete_rows <= 0:
        rows = rows_with_guard(
            [
                {
                    "Metric": "Cleanup skipped",
                    "Value": "0 rows eligible",
                    "Notes": "No raw scan_results rows are old enough to remove.",
                }
            ]
        )
        return {
            "ok": True,
            "cleanup_ran": False,
            "deleted_rows": 0,
            "status": "Cleanup skipped: no raw scan rows are old enough to remove.",
            "rows": rows,
            "preview": preview,
        }

    backup_check = _latest_safety_backup(max_age_hours=backup_max_age_hours)

    if not backup_check.get("ok", False):
        rows = rows_with_guard(
            [
                {
                    "Metric": "Cleanup blocked",
                    "Value": "fresh backup required",
                    "Notes": backup_check.get("status", "Create a safety backup first."),
                },
                {
                    "Metric": "Required backup age",
                    "Value": f"<= {backup_max_age_hours} hours",
                    "Notes": "Use Database Backup > Create Safety Backup, then retry cleanup.",
                },
            ]
        )
        return {
            "ok": False,
            "cleanup_ran": False,
            "deleted_rows": 0,
            "status": "Cleanup blocked: create a fresh database safety backup first.",
            "rows": rows,
            "preview": preview,
            "backup_check": backup_check,
        }

    cutoff_date = preview.get("cutoff_date")

    if not cutoff_date:
        rows = rows_with_guard(
            [
                {
                    "Metric": "Cleanup blocked",
                    "Value": "missing cutoff date",
                    "Notes": "Retention preview did not return a cutoff date.",
                }
            ]
        )
        return {
            "ok": False,
            "cleanup_ran": False,
            "deleted_rows": 0,
            "status": "Cleanup blocked: cutoff date is missing.",
            "rows": rows,
            "preview": preview,
            "backup_check": backup_check,
        }

    # Preserve aggregate history before raw rows are removed. This is intentionally
    # broad so long-term daily_item_metrics remains available even after raw
    # scan_results is trimmed.
    metrics_result = rebuild_daily_item_metrics(days=3650)

    conn, db_path = _connect()

    try:
        cursor = conn.execute(
            """
            DELETE FROM scan_results
            WHERE scanned_at IS NOT NULL
              AND substr(CAST(scanned_at AS TEXT), 1, 10) < ?
            """,
            (cutoff_date,),
        )
        deleted_rows = cursor.rowcount if cursor.rowcount is not None else would_delete_rows
        conn.commit()
    finally:
        conn.close()

    after_preview = build_retention_preview_snapshot(retention_days=days_int)

    rows = [
        {
            "Metric": "Cleanup action",
            "Value": "completed",
            "Notes": "Raw scan_results rows older than the cutoff were deleted.",
        },
        {
            "Metric": "Deleted rows",
            "Value": f"{int(deleted_rows or 0):,}",
            "Notes": f"Preview expected {would_delete_rows:,} row(s).",
        },
        {
            "Metric": "Retention window",
            "Value": f"{days_int} day(s)",
            "Notes": f"Cutoff date: {cutoff_date}",
        },
        {
            "Metric": "Safety backup used",
            "Value": backup_check.get("backup_file", ""),
            "Notes": backup_check.get("status", ""),
        },
        {
            "Metric": "Daily metrics preserved",
            "Value": "rebuilt before cleanup",
            "Notes": metrics_result.get("status", ""),
        },
        {
            "Metric": "Compaction",
            "Value": "not run",
            "Notes": "SQLite file size may not shrink until a future VACUUM/compact feature.",
        },
    ] + list(after_preview.get("rows", []))

    return {
        "ok": True,
        "cleanup_ran": True,
        "deleted_rows": int(deleted_rows or 0),
        "status": (
            f"Cleanup complete. Deleted {int(deleted_rows or 0):,} old raw scan_results row(s). "
            f"Backup used: {backup_check.get('backup_file', '')}. "
            "Daily metrics were rebuilt before cleanup. Database compaction was not run."
        ),
        "rows": rows,
        "preview": preview,
        "after_preview": after_preview,
        "backup_check": backup_check,
        "metrics_result": metrics_result,
    }
