from __future__ import annotations

from typing import Any

from .common import (
    _avg,
    _connect,
    _date_minus_days,
    _safe_float,
    _scalar,
    _table_exists,
    _trend_value,
)


def build_data_trend_snapshot(limit: int = 25) -> dict[str, Any]:
    conn, db_path = _connect()

    try:
        if not _table_exists(conn, "daily_item_metrics"):
            return {
                "ok": False,
                "status": "daily_item_metrics is missing. Click Apply Data Schema / Indexes, then Rebuild Daily Item Metrics.",
                "readiness": [
                    {
                        "Signal": "Daily metrics",
                        "Available": "missing",
                        "Target": "created table",
                        "Status": "not ready",
                        "Notes": "daily_item_metrics table has not been created yet.",
                    }
                ],
                "top_trends": [],
            }

        total_rows = int(_scalar(conn, "SELECT COUNT(*) FROM daily_item_metrics") or 0)
        distinct_days = int(_scalar(conn, "SELECT COUNT(DISTINCT metric_date) FROM daily_item_metrics") or 0)
        distinct_items = int(_scalar(conn, "SELECT COUNT(DISTINCT item_name) FROM daily_item_metrics") or 0)
        newest_date = _scalar(conn, "SELECT MAX(metric_date) FROM daily_item_metrics")
        oldest_date = _scalar(conn, "SELECT MIN(metric_date) FROM daily_item_metrics")

        readiness = []

        def add_readiness(signal: str, available: Any, target: Any, status: str, notes: str) -> None:
            readiness.append(
                {
                    "Signal": signal,
                    "Available": available,
                    "Target": target,
                    "Status": status,
                    "Notes": notes,
                }
            )

        add_readiness(
            "Daily aggregate rows",
            f"{total_rows:,}",
            "> 0",
            "ready" if total_rows > 0 else "not ready",
            "Rows in daily_item_metrics.",
        )
        add_readiness(
            "Distinct metric days",
            distinct_days,
            "7+",
            "ready" if distinct_days >= 7 else "building",
            f"{oldest_date or ''} -> {newest_date or ''}. Short-term trend scoring improves at 7+ days.",
        )
        add_readiness(
            "30-day trend window",
            distinct_days,
            "30+",
            "ready" if distinct_days >= 30 else "building",
            "Needed for stronger medium-term direction and stability signals.",
        )
        add_readiness(
            "90-day trend window",
            distinct_days,
            "90+",
            "ready" if distinct_days >= 90 else "building",
            "Needed before treating monthly/seasonal trend predictions as meaningful.",
        )
        add_readiness(
            "Distinct items",
            f"{distinct_items:,}",
            "100+",
            "ready" if distinct_items >= 100 else "building",
            "More items give the dashboard better comparison/ranking context.",
        )

        if total_rows <= 0:
            return {
                "ok": True,
                "status": "Trend readiness loaded, but daily_item_metrics has no rows yet.",
                "readiness": readiness,
                "top_trends": [],
            }

        raw_rows = conn.execute(
            """
            WITH per_item AS (
                SELECT
                    item_name,
                    COUNT(DISTINCT metric_date) AS days_seen,
                    MIN(metric_date) AS first_date,
                    MAX(metric_date) AS last_date,
                    AVG(avg_margin) AS avg_margin_all,
                    AVG(avg_roi) AS avg_roi_all,
                    AVG(avg_volume) AS avg_volume_all,
                    AVG(avg_recommendation_score) AS avg_score_all,
                    AVG(margin_volatility) AS avg_margin_volatility,
                    SUM(scan_count) AS scan_count_total
                FROM daily_item_metrics
                GROUP BY item_name
            ),
            first_day AS (
                SELECT d.item_name, AVG(d.avg_margin) AS first_margin, AVG(d.avg_recommendation_score) AS first_score
                FROM daily_item_metrics d
                JOIN per_item p
                  ON p.item_name = d.item_name
                 AND p.first_date = d.metric_date
                GROUP BY d.item_name
            ),
            last_day AS (
                SELECT d.item_name, AVG(d.avg_margin) AS last_margin, AVG(d.avg_recommendation_score) AS last_score
                FROM daily_item_metrics d
                JOIN per_item p
                  ON p.item_name = d.item_name
                 AND p.last_date = d.metric_date
                GROUP BY d.item_name
            )
            SELECT
                p.item_name,
                p.days_seen,
                p.first_date,
                p.last_date,
                ROUND(p.avg_margin_all, 2) AS avg_margin,
                ROUND(p.avg_roi_all, 2) AS avg_roi,
                ROUND(p.avg_volume_all, 2) AS avg_volume,
                ROUND(p.avg_score_all, 2) AS avg_score,
                ROUND(p.avg_margin_volatility, 2) AS margin_volatility,
                p.scan_count_total,
                ROUND(f.first_margin, 2) AS first_margin,
                ROUND(l.last_margin, 2) AS last_margin,
                ROUND(f.first_score, 2) AS first_score,
                ROUND(l.last_score, 2) AS last_score
            FROM per_item p
            LEFT JOIN first_day f ON f.item_name = p.item_name
            LEFT JOIN last_day l ON l.item_name = p.item_name
            WHERE p.days_seen >= 2
            ORDER BY p.days_seen DESC, p.avg_score_all DESC
            LIMIT 500
            """
        ).fetchall()

        trend_rows = []

        for row in raw_rows:
            margin_delta, margin_direction = _trend_value(row["last_margin"], row["first_margin"])
            score_delta, score_direction = _trend_value(row["last_score"], row["first_score"])

            margin_delta_value = round(margin_delta, 2) if margin_delta is not None else None
            score_delta_value = round(score_delta, 2) if score_delta is not None else None

            days_seen = int(row["days_seen"] or 0)
            scan_count_total = int(row["scan_count_total"] or 0)
            avg_score = row["avg_score"] if row["avg_score"] is not None else 0
            margin_volatility = row["margin_volatility"] if row["margin_volatility"] is not None else 0

            readiness_weight = min(days_seen / 7, 1.0)
            score_component = float(avg_score or 0)
            margin_component = max(float(margin_delta_value or 0), 0) / 100
            score_delta_component = max(float(score_delta_value or 0), 0)
            volatility_penalty = min(abs(float(margin_volatility or 0)) / 1000, 25)
            scan_weight = min(scan_count_total / 25, 10)

            trend_score = round(
                readiness_weight
                * (
                    (score_component * 0.45)
                    + (score_delta_component * 0.30)
                    + (margin_component * 0.15)
                    + (scan_weight * 0.10)
                    - volatility_penalty
                ),
                2,
            )

            trend_rows.append(
                {
                    "Item": row["item_name"],
                    "Days Seen": days_seen,
                    "First Date": row["first_date"],
                    "Last Date": row["last_date"],
                    "Trend Score": trend_score,
                    "Avg Score": row["avg_score"],
                    "Score Δ": score_delta_value,
                    "Score Direction": score_direction,
                    "Avg Margin": row["avg_margin"],
                    "Margin Δ": margin_delta_value,
                    "Margin Direction": margin_direction,
                    "Margin Volatility": row["margin_volatility"],
                    "Total Scans": scan_count_total,
                }
            )

        trend_rows.sort(key=lambda item: (item["Trend Score"], item["Days Seen"], item["Total Scans"]), reverse=True)
        trend_rows = trend_rows[: max(1, min(int(limit or 25), 100))]

        status = (
            f"Trend readiness loaded from daily_item_metrics. "
            f"{total_rows:,} metric rows, {distinct_days} day(s), {distinct_items:,} item(s). "
            f"Top trend rows shown: {len(trend_rows)}."
        )

        return {
            "ok": True,
            "status": status,
            "readiness": readiness,
            "top_trends": trend_rows,
        }
    finally:
        conn.close()


def build_item_trend_explorer_snapshot(item_query: str | None = None, days: int = 90) -> dict[str, Any]:
    conn, db_path = _connect()

    try:
        if not _table_exists(conn, "daily_item_metrics"):
            return {
                "ok": False,
                "status": "daily_item_metrics is missing. Open Admin > Data Health, click Apply Data Schema / Indexes, then Rebuild Daily Item Metrics.",
                "matched_item": "",
                "summary_cards": [],
                "rows": [],
                "matches": [],
            }

        total_rows = int(_scalar(conn, "SELECT COUNT(*) FROM daily_item_metrics") or 0)

        if total_rows <= 0:
            return {
                "ok": False,
                "status": "daily_item_metrics has no rows yet. Open Admin > Data Health and click Rebuild Daily Item Metrics.",
                "matched_item": "",
                "summary_cards": [],
                "rows": [],
                "matches": [],
            }

        safe_days = max(1, min(int(days or 90), 3650))
        query_text = str(item_query or "").strip()

        if query_text:
            like = f"%{query_text.lower()}%"
            prefix = f"{query_text.lower()}%"
            match_rows = conn.execute(
                """
                SELECT
                    item_name,
                    COUNT(DISTINCT metric_date) AS days_seen,
                    COUNT(*) AS metric_rows,
                    ROUND(AVG(avg_margin), 2) AS avg_margin,
                    ROUND(AVG(avg_recommendation_score), 2) AS avg_score,
                    MAX(metric_date) AS newest_date
                FROM daily_item_metrics
                WHERE LOWER(item_name) LIKE ?
                GROUP BY item_name
                ORDER BY
                    CASE
                        WHEN LOWER(item_name) = ? THEN 0
                        WHEN LOWER(item_name) LIKE ? THEN 1
                        ELSE 2
                    END,
                    days_seen DESC,
                    avg_score DESC
                LIMIT 15
                """,
                (like, query_text.lower(), prefix),
            ).fetchall()
        else:
            match_rows = conn.execute(
                """
                SELECT
                    item_name,
                    COUNT(DISTINCT metric_date) AS days_seen,
                    COUNT(*) AS metric_rows,
                    ROUND(AVG(avg_margin), 2) AS avg_margin,
                    ROUND(AVG(avg_recommendation_score), 2) AS avg_score,
                    MAX(metric_date) AS newest_date
                FROM daily_item_metrics
                GROUP BY item_name
                ORDER BY days_seen DESC, avg_score DESC, avg_margin DESC
                LIMIT 15
                """
            ).fetchall()

        matches = [
            {
                "Item": row["item_name"],
                "Days Seen": row["days_seen"],
                "Metric Rows": row["metric_rows"],
                "Avg Margin": row["avg_margin"],
                "Avg Score": row["avg_score"],
                "Newest Date": row["newest_date"],
            }
            for row in match_rows
        ]

        if not match_rows:
            return {
                "ok": False,
                "status": f"No daily metrics matched {query_text!r}. Try a broader item name.",
                "matched_item": "",
                "summary_cards": [],
                "rows": [],
                "matches": [],
            }

        matched_item = match_rows[0]["item_name"]
        newest_date = _scalar(
            conn,
            "SELECT MAX(metric_date) FROM daily_item_metrics WHERE item_name = ?",
            (matched_item,),
        )
        cutoff = _date_minus_days(newest_date, safe_days) if newest_date else None

        params: list[Any] = [matched_item]
        where = "WHERE item_name = ?"

        if cutoff:
            where += " AND metric_date >= ?"
            params.append(cutoff)

        metric_rows = conn.execute(
            f"""
            SELECT
                metric_date,
                SUM(scan_count) AS scan_count,
                SUM(profitable_count) AS profitable_count,
                ROUND(AVG(avg_margin), 2) AS avg_margin,
                ROUND(AVG(avg_total_profit), 2) AS avg_total_profit,
                ROUND(AVG(avg_profit_per_item), 2) AS avg_profit_per_item,
                ROUND(AVG(avg_roi), 2) AS avg_roi,
                ROUND(AVG(avg_volume), 2) AS avg_volume,
                ROUND(AVG(avg_quick_score), 2) AS avg_quick_score,
                ROUND(AVG(avg_overnight_score), 2) AS avg_overnight_score,
                ROUND(AVG(avg_recommendation_score), 2) AS avg_recommendation_score,
                ROUND(AVG(margin_volatility), 2) AS margin_volatility,
                MIN(min_margin) AS min_margin,
                MAX(max_margin) AS max_margin
            FROM daily_item_metrics
            {where}
            GROUP BY metric_date
            ORDER BY metric_date
            """,
            tuple(params),
        ).fetchall()

        rows = [
            {
                "Metric Date": row["metric_date"],
                "Scan Count": row["scan_count"],
                "Profitable Count": row["profitable_count"],
                "Avg Margin": row["avg_margin"],
                "Avg Total Profit": row["avg_total_profit"],
                "Avg Profit / Item": row["avg_profit_per_item"],
                "Avg ROI": row["avg_roi"],
                "Avg Volume": row["avg_volume"],
                "Quick Score": row["avg_quick_score"],
                "Overnight Score": row["avg_overnight_score"],
                "Recommendation Score": row["avg_recommendation_score"],
                "Margin Volatility": row["margin_volatility"],
                "Min Margin": row["min_margin"],
                "Max Margin": row["max_margin"],
            }
            for row in metric_rows
        ]

        if not rows:
            return {
                "ok": False,
                "status": f"{matched_item} matched, but no rows were found in the selected {safe_days}-day window.",
                "matched_item": matched_item,
                "summary_cards": [],
                "rows": [],
                "matches": matches,
            }

        first = rows[0]
        last = rows[-1]

        margin_delta, margin_direction = _trend_value(last.get("Avg Margin"), first.get("Avg Margin"))
        score_delta, score_direction = _trend_value(last.get("Recommendation Score"), first.get("Recommendation Score"))

        total_scans = sum(int(row.get("Scan Count") or 0) for row in rows)
        total_profitable = sum(int(row.get("Profitable Count") or 0) for row in rows)
        avg_score = _avg([_safe_float(row.get("Recommendation Score")) for row in rows])
        avg_margin = _avg([_safe_float(row.get("Avg Margin")) for row in rows])
        avg_volatility = _avg([_safe_float(row.get("Margin Volatility")) for row in rows])

        best_row = max(rows, key=lambda row: _safe_float(row.get("Recommendation Score")) or -999999)

        summary_cards = [
            {
                "Title": "Matched Item",
                "Value": matched_item,
                "Detail": f"{len(matches)} match(es), {len(rows)} metric day(s)",
            },
            {
                "Title": "Date Range",
                "Value": f"{first.get('Metric Date')} -> {last.get('Metric Date')}",
                "Detail": f"selected window: {safe_days} day(s)",
            },
            {
                "Title": "Avg Margin",
                "Value": round(avg_margin, 2) if avg_margin is not None else "n/a",
                "Detail": f"delta {round(margin_delta, 2) if margin_delta is not None else 'n/a'} ({margin_direction})",
            },
            {
                "Title": "Avg Score",
                "Value": round(avg_score, 2) if avg_score is not None else "n/a",
                "Detail": f"delta {round(score_delta, 2) if score_delta is not None else 'n/a'} ({score_direction})",
            },
            {
                "Title": "Total Scans",
                "Value": f"{total_scans:,}",
                "Detail": f"profitable observations: {total_profitable:,}",
            },
            {
                "Title": "Margin Volatility",
                "Value": round(avg_volatility, 2) if avg_volatility is not None else "n/a",
                "Detail": "lower is usually more stable",
            },
            {
                "Title": "Best Score Day",
                "Value": best_row.get("Metric Date"),
                "Detail": f"score {best_row.get('Recommendation Score')}",
            },
        ]

        status = (
            f"Loaded trend explorer for {matched_item}. "
            f"{len(rows)} daily point(s), {total_scans:,} total scan observations, "
            f"margin direction={margin_direction}, score direction={score_direction}."
        )

        if query_text and matched_item.lower() != query_text.lower():
            status += f" Search {query_text!r} matched closest item {matched_item!r}."

        return {
            "ok": True,
            "status": status,
            "matched_item": matched_item,
            "summary_cards": summary_cards,
            "rows": rows,
            "matches": matches,
        }
    finally:
        conn.close()
