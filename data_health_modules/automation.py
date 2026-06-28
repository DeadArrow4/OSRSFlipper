from __future__ import annotations

from datetime import datetime
from typing import Any

from .common import _columns, _connect, _date_only, _hours_since, _scalar, _table_exists
from .metrics import rebuild_daily_item_metrics
from .schema import ensure_data_health_schema


def build_metrics_automation_snapshot(max_age_hours: int = 12) -> dict[str, Any]:
    conn, db_path = _connect()

    try:
        checks: list[dict[str, Any]] = []

        def add_check(check: str, value: Any, status: str, notes: str) -> None:
            checks.append(
                {
                    "Check": check,
                    "Value": value,
                    "Status": status,
                    "Notes": notes,
                }
            )

        scan_rows = 0
        scan_latest = None
        scan_latest_date = None
        metric_rows = 0
        metric_latest_date = None
        metric_updated_at = None
        stale_days = None

        if _table_exists(conn, "scan_results"):
            scan_rows = int(_scalar(conn, "SELECT COUNT(*) FROM scan_results") or 0)
            if "scanned_at" in _columns(conn, "scan_results"):
                scan_latest = _scalar(conn, "SELECT MAX(scanned_at) FROM scan_results")
                scan_latest_date = _date_only(scan_latest)

        if _table_exists(conn, "daily_item_metrics"):
            metric_rows = int(_scalar(conn, "SELECT COUNT(*) FROM daily_item_metrics") or 0)
            metric_latest_date = _scalar(conn, "SELECT MAX(metric_date) FROM daily_item_metrics")
            if "updated_at" in _columns(conn, "daily_item_metrics"):
                metric_updated_at = _scalar(conn, "SELECT MAX(updated_at) FROM daily_item_metrics")

        if scan_latest_date and metric_latest_date:
            try:
                stale_days = (
                    datetime.strptime(scan_latest_date, "%Y-%m-%d").date()
                    - datetime.strptime(str(metric_latest_date)[:10], "%Y-%m-%d").date()
                ).days
            except Exception:
                stale_days = None

        updated_age_hours = _hours_since(metric_updated_at)
        max_age = max(1, int(max_age_hours or 12))

        if not _table_exists(conn, "daily_item_metrics"):
            freshness_status = "schema missing"
            freshness_notes = "Click Apply Data Schema / Indexes before refreshing metrics."
        elif metric_rows <= 0:
            freshness_status = "empty"
            freshness_notes = "Click Rebuild Daily Item Metrics or Refresh Stale Metrics."
        elif stale_days is not None and stale_days > 0:
            freshness_status = "stale"
            freshness_notes = f"daily_item_metrics is {stale_days} day(s) behind scan_results."
        elif updated_age_hours is not None and updated_age_hours > max_age:
            freshness_status = "aging"
            freshness_notes = f"Metrics were last rebuilt about {round(updated_age_hours, 1)} hour(s) ago."
        else:
            freshness_status = "current"
            freshness_notes = "daily_item_metrics appears current enough for trend views."

        add_check("scan_results rows", f"{scan_rows:,}", "ok" if scan_rows else "missing", "Raw scanner observations.")
        add_check("latest scan date", scan_latest_date or "", "ok" if scan_latest_date else "missing", str(scan_latest or ""))
        add_check("daily_item_metrics rows", f"{metric_rows:,}", "ok" if metric_rows else "empty", "Aggregate rows used by Data Health and Item Trends.")
        add_check("latest metric date", metric_latest_date or "", "ok" if metric_latest_date else "missing", "Newest daily aggregate date.")
        add_check(
            "metrics updated age",
            "n/a" if updated_age_hours is None else f"{round(updated_age_hours, 1)} hours",
            "ok" if updated_age_hours is not None and updated_age_hours <= max_age else "aging",
            f"Target age <= {max_age} hours.",
        )
        add_check(
            "freshness",
            freshness_status,
            "ready" if freshness_status == "current" else "needs attention",
            freshness_notes,
        )

        return {
            "ok": True,
            "database_path": str(db_path),
            "checks": checks,
            "scan_rows": scan_rows,
            "scan_latest_date": scan_latest_date,
            "metric_rows": metric_rows,
            "metric_latest_date": metric_latest_date,
            "metric_updated_at": metric_updated_at,
            "stale_days": stale_days,
            "updated_age_hours": updated_age_hours,
            "freshness_status": freshness_status,
            "needs_refresh": freshness_status in {"schema missing", "empty", "stale", "aging"},
        }
    finally:
        conn.close()


def refresh_daily_metrics_if_stale(
    max_age_hours: int = 12,
    rebuild_days: int = 14,
    force: bool = False,
) -> dict[str, Any]:
    schema_result = ensure_data_health_schema()
    before = build_metrics_automation_snapshot(max_age_hours=max_age_hours)

    stale_days = before.get("stale_days")
    metric_rows = int(before.get("metric_rows") or 0)
    needs_refresh = bool(before.get("needs_refresh"))

    should_refresh = bool(force or needs_refresh)

    if not should_refresh:
        return {
            "ok": True,
            "refreshed": False,
            "status": "Daily metrics are current enough; no rebuild was needed.",
            "before": before,
            "after": before,
            "schema_result": schema_result,
        }

    safe_days = max(1, min(int(rebuild_days or 14), 3650))

    if stale_days is not None and stale_days > 0:
        safe_days = max(safe_days, min(int(stale_days) + 3, 3650))

    if metric_rows <= 0:
        safe_days = max(safe_days, 120)

    rebuild_result = rebuild_daily_item_metrics(days=safe_days)
    after = build_metrics_automation_snapshot(max_age_hours=max_age_hours)

    return {
        "ok": bool(rebuild_result.get("ok", False)),
        "refreshed": True,
        "status": (
            f"Stale daily metrics refresh complete. "
            f"Rebuilt last {safe_days} day(s). {rebuild_result.get('status', '')}"
        ),
        "before": before,
        "after": after,
        "schema_result": schema_result,
        "rebuild_result": rebuild_result,
        "rebuild_days": safe_days,
    }
