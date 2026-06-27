from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE_PATH = BASE_DIR / "osrs_flip_scanner.db"


@dataclass(frozen=True)
class TrendSummary:
    item_id: int | None
    item_name: str
    days_seen: int
    recent_avg_margin: float | None
    prior_avg_margin: float | None
    margin_change: float | None
    margin_change_pct: float | None
    avg_score_recent: float | None
    avg_score_prior: float | None
    score_change: float | None
    margin_stability: float | None
    trend_direction: str
    trend_confidence: str
    trend_note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "trend_item_id": self.item_id,
            "trend_item_name": self.item_name,
            "days_seen": self.days_seen,
            "recent_avg_margin": _round_or_none(self.recent_avg_margin),
            "prior_avg_margin": _round_or_none(self.prior_avg_margin),
            "margin_change": _round_or_none(self.margin_change),
            "margin_change_pct": _round_or_none(self.margin_change_pct),
            "avg_score_recent": _round_or_none(self.avg_score_recent),
            "avg_score_prior": _round_or_none(self.avg_score_prior),
            "score_change": _round_or_none(self.score_change),
            "margin_stability": _round_or_none(self.margin_stability),
            "trend_direction": self.trend_direction,
            "trend_confidence": self.trend_confidence,
            "trend_note": self.trend_note,
        }


def _round_or_none(value: Any, digits: int = 2) -> float | None:
    if value is None:
        return None

    try:
        if math.isnan(float(value)):
            return None
    except Exception:
        return None

    return round(float(value), digits)


def _connect(database_path: str | Path | None = None) -> sqlite3.Connection:
    db_path = Path(database_path) if database_path else DEFAULT_DATABASE_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.Error:
        return set()

    return {str(row["name"]) for row in rows}


def _first_existing(candidates: Iterable[str], columns: set[str]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None

    try:
        out = float(value)
    except (TypeError, ValueError):
        return None

    if math.isnan(out) or math.isinf(out):
        return None

    return out


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _average(values: Iterable[Any]) -> float | None:
    floats = [_safe_float(value) for value in values]
    clean = [value for value in floats if value is not None]

    if not clean:
        return None

    return mean(clean)


def _stability(values: list[float]) -> float | None:
    clean = [float(value) for value in values if value is not None]

    if len(clean) < 3:
        return None

    avg = mean(clean)

    if abs(avg) < 0.000001:
        return None

    coeff = abs(pstdev(clean) / avg)
    score = max(0.0, min(100.0, 100.0 - (coeff * 100.0)))
    return score


def _direction(
    days_seen: int,
    margin_change: float | None,
    margin_change_pct: float | None,
    score_change: float | None,
) -> tuple[str, str]:
    if days_seen < 4:
        return "building", "Not enough daily history yet."

    pct = margin_change_pct or 0.0
    score_delta = score_change or 0.0

    if pct >= 15 or score_delta >= 10:
        return "up", "Recent margins/scores are improving."
    if pct <= -15 or score_delta <= -10:
        return "down", "Recent margins/scores are weakening."
    if abs(pct) <= 5 and abs(score_delta) <= 5:
        return "flat", "Trend is mostly stable."

    return "mixed", "Trend has mixed margin and score movement."


def _confidence(days_seen: int, margin_stability: float | None, recent_avg_margin: float | None) -> str:
    if days_seen < 4:
        return "low"

    stability = margin_stability or 0.0
    margin = recent_avg_margin or 0.0

    if days_seen >= 14 and stability >= 70 and margin > 0:
        return "high"

    if days_seen >= 7 and stability >= 45 and margin > 0:
        return "medium"

    return "low"


def load_item_trend_summary(
    item_name: str | None = None,
    item_id: int | None = None,
    database_path: str | Path | None = None,
    recent_days: int = 3,
    prior_days: int = 4,
) -> TrendSummary:
    """Return trend summary for one item from daily_item_metrics.

    The helper is intentionally read-only. It never changes the database and is
    safe to call from Trade Board callbacks.
    """

    if not item_name and item_id is None:
        return TrendSummary(
            item_id=None,
            item_name="",
            days_seen=0,
            recent_avg_margin=None,
            prior_avg_margin=None,
            margin_change=None,
            margin_change_pct=None,
            avg_score_recent=None,
            avg_score_prior=None,
            score_change=None,
            margin_stability=None,
            trend_direction="unknown",
            trend_confidence="low",
            trend_note="No item name or item id was provided.",
        )

    conn = _connect(database_path)

    try:
        if not _table_exists(conn, "daily_item_metrics"):
            return TrendSummary(
                item_id=item_id,
                item_name=str(item_name or ""),
                days_seen=0,
                recent_avg_margin=None,
                prior_avg_margin=None,
                margin_change=None,
                margin_change_pct=None,
                avg_score_recent=None,
                avg_score_prior=None,
                score_change=None,
                margin_stability=None,
                trend_direction="unavailable",
                trend_confidence="low",
                trend_note="daily_item_metrics table does not exist yet.",
            )

        columns = _column_names(conn, "daily_item_metrics")

        item_id_col = _first_existing(["item_id", "id"], columns)
        item_name_col = _first_existing(["item_name", "name", "item"], columns)
        day_col = _first_existing(["metric_date", "day", "date", "scan_date"], columns)
        margin_col = _first_existing(["avg_margin", "margin", "margin_gp", "gross_margin"], columns)
        score_col = _first_existing(["avg_score", "score", "flip_score"], columns)

        if not day_col or not margin_col:
            return TrendSummary(
                item_id=item_id,
                item_name=str(item_name or ""),
                days_seen=0,
                recent_avg_margin=None,
                prior_avg_margin=None,
                margin_change=None,
                margin_change_pct=None,
                avg_score_recent=None,
                avg_score_prior=None,
                score_change=None,
                margin_stability=None,
                trend_direction="unavailable",
                trend_confidence="low",
                trend_note="daily_item_metrics does not have recognizable date/margin columns.",
            )

        where_clauses = []
        params: list[Any] = []

        if item_id is not None and item_id_col:
            where_clauses.append(f"{item_id_col} = ?")
            params.append(item_id)

        if item_name and item_name_col:
            where_clauses.append(f"LOWER({item_name_col}) = LOWER(?)")
            params.append(item_name)

        if not where_clauses:
            return TrendSummary(
                item_id=item_id,
                item_name=str(item_name or ""),
                days_seen=0,
                recent_avg_margin=None,
                prior_avg_margin=None,
                margin_change=None,
                margin_change_pct=None,
                avg_score_recent=None,
                avg_score_prior=None,
                score_change=None,
                margin_stability=None,
                trend_direction="unavailable",
                trend_confidence="low",
                trend_note="Could not match this item to daily_item_metrics columns.",
            )

        select_parts = [
            f"{day_col} AS metric_day",
            f"{margin_col} AS avg_margin",
        ]

        if item_id_col:
            select_parts.append(f"{item_id_col} AS item_id")
        else:
            select_parts.append("NULL AS item_id")

        if item_name_col:
            select_parts.append(f"{item_name_col} AS item_name")
        else:
            select_parts.append("NULL AS item_name")

        if score_col:
            select_parts.append(f"{score_col} AS avg_score")
        else:
            select_parts.append("NULL AS avg_score")

        sql = f"""
            SELECT {", ".join(select_parts)}
            FROM daily_item_metrics
            WHERE {" OR ".join(where_clauses)}
            ORDER BY {day_col} DESC
            LIMIT ?
        """

        lookback = max(7, int(recent_days) + int(prior_days) + 14)
        rows = conn.execute(sql, (*params, lookback)).fetchall()

        if not rows:
            return TrendSummary(
                item_id=item_id,
                item_name=str(item_name or ""),
                days_seen=0,
                recent_avg_margin=None,
                prior_avg_margin=None,
                margin_change=None,
                margin_change_pct=None,
                avg_score_recent=None,
                avg_score_prior=None,
                score_change=None,
                margin_stability=None,
                trend_direction="building",
                trend_confidence="low",
                trend_note="No daily trend rows found for this item yet.",
            )

        rows_ordered = list(rows)
        resolved_item_id = _safe_int(rows_ordered[0]["item_id"]) if "item_id" in rows_ordered[0].keys() else item_id
        resolved_item_name = str(rows_ordered[0]["item_name"] or item_name or "")

        recent_slice = rows_ordered[: max(1, int(recent_days))]
        prior_slice = rows_ordered[max(1, int(recent_days)) : max(1, int(recent_days)) + max(1, int(prior_days))]

        recent_avg_margin = _average(row["avg_margin"] for row in recent_slice)
        prior_avg_margin = _average(row["avg_margin"] for row in prior_slice)
        margin_change = None
        margin_change_pct = None

        if recent_avg_margin is not None and prior_avg_margin is not None:
            margin_change = recent_avg_margin - prior_avg_margin
            if abs(prior_avg_margin) > 0.000001:
                margin_change_pct = (margin_change / abs(prior_avg_margin)) * 100.0

        avg_score_recent = _average(row["avg_score"] for row in recent_slice)
        avg_score_prior = _average(row["avg_score"] for row in prior_slice)
        score_change = None

        if avg_score_recent is not None and avg_score_prior is not None:
            score_change = avg_score_recent - avg_score_prior

        margin_values = [
            value
            for value in (_safe_float(row["avg_margin"]) for row in rows_ordered[:14])
            if value is not None
        ]
        margin_stability = _stability(margin_values)

        days_seen = len(rows_ordered)
        trend_direction, trend_note = _direction(days_seen, margin_change, margin_change_pct, score_change)
        trend_confidence = _confidence(days_seen, margin_stability, recent_avg_margin)

        return TrendSummary(
            item_id=resolved_item_id,
            item_name=resolved_item_name,
            days_seen=days_seen,
            recent_avg_margin=recent_avg_margin,
            prior_avg_margin=prior_avg_margin,
            margin_change=margin_change,
            margin_change_pct=margin_change_pct,
            avg_score_recent=avg_score_recent,
            avg_score_prior=avg_score_prior,
            score_change=score_change,
            margin_stability=margin_stability,
            trend_direction=trend_direction,
            trend_confidence=trend_confidence,
            trend_note=trend_note,
        )
    finally:
        conn.close()


def build_trade_board_trend_lookup(
    item_names: Iterable[str] | None = None,
    item_ids: Iterable[int] | None = None,
    database_path: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Build a name/id lookup of trend summaries for Trade Board enrichment."""

    lookup: dict[str, dict[str, Any]] = {}

    for item_id in item_ids or []:
        summary = load_item_trend_summary(item_id=item_id, database_path=database_path)
        data = summary.as_dict()
        lookup[str(item_id)] = data
        if summary.item_name:
            lookup[summary.item_name.lower()] = data

    for item_name in item_names or []:
        if not item_name:
            continue

        key = str(item_name).lower()
        if key in lookup:
            continue

        summary = load_item_trend_summary(item_name=str(item_name), database_path=database_path)
        data = summary.as_dict()
        lookup[key] = data

        if summary.item_id is not None:
            lookup[str(summary.item_id)] = data

    return lookup


def enrich_trade_board_rows_with_trends(
    rows: list[dict[str, Any]],
    database_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return Trade Board rows with read-only trend fields added.

    The function accepts common item-name/id column variants so it can be wired
    into the existing Trade Board with minimal assumptions.
    """

    if not rows:
        return rows

    name_keys = ["Item", "item", "Item Name", "item_name", "name", "Name"]
    id_keys = ["Item ID", "item_id", "id", "ID"]

    item_names: list[str] = []
    item_ids: list[int] = []

    for row in rows:
        for key in name_keys:
            value = row.get(key)
            if value:
                item_names.append(str(value))
                break

        for key in id_keys:
            value = _safe_int(row.get(key))
            if value is not None:
                item_ids.append(value)
                break

    lookup = build_trade_board_trend_lookup(
        item_names=item_names,
        item_ids=item_ids,
        database_path=database_path,
    )

    enriched: list[dict[str, Any]] = []

    for row in rows:
        new_row = dict(row)
        trend_data: dict[str, Any] | None = None

        for key in id_keys:
            value = _safe_int(new_row.get(key))
            if value is not None and str(value) in lookup:
                trend_data = lookup[str(value)]
                break

        if trend_data is None:
            for key in name_keys:
                value = new_row.get(key)
                if value and str(value).lower() in lookup:
                    trend_data = lookup[str(value).lower()]
                    break

        if not trend_data:
            trend_data = {
                "days_seen": 0,
                "trend_direction": "building",
                "trend_confidence": "low",
                "recent_avg_margin": None,
                "margin_stability": None,
                "score_change": None,
                "trend_note": "No trend history yet.",
            }

        new_row.update(
            {
                "Trend Direction": trend_data.get("trend_direction", "building"),
                "Trend Confidence": trend_data.get("trend_confidence", "low"),
                "Days Seen": trend_data.get("days_seen", 0),
                "Recent Avg Margin": trend_data.get("recent_avg_margin"),
                "Margin Stability": trend_data.get("margin_stability"),
                "Score Change": trend_data.get("score_change"),
                "Trend Note": trend_data.get("trend_note", ""),
            }
        )
        enriched.append(new_row)

    return enriched


def summarize_trade_board_trend_health(database_path: str | Path | None = None) -> dict[str, Any]:
    """Return a lightweight health summary for trend-aware Trade Board readiness."""

    conn = _connect(database_path)

    try:
        if not _table_exists(conn, "daily_item_metrics"):
            return {
                "ok": False,
                "status": "daily_item_metrics table does not exist yet.",
                "metric_days": 0,
                "items_with_history": 0,
            }

        columns = _column_names(conn, "daily_item_metrics")
        day_col = _first_existing(["metric_date", "day", "date", "scan_date"], columns)
        item_col = _first_existing(["item_id", "item_name", "name", "item"], columns)

        if not day_col or not item_col:
            return {
                "ok": False,
                "status": "daily_item_metrics does not have recognizable day/item columns.",
                "metric_days": 0,
                "items_with_history": 0,
            }

        metric_days = int(conn.execute(f"SELECT COUNT(DISTINCT {day_col}) FROM daily_item_metrics").fetchone()[0] or 0)
        items_with_history = int(conn.execute(f"SELECT COUNT(DISTINCT {item_col}) FROM daily_item_metrics").fetchone()[0] or 0)

        if metric_days >= 14:
            status = "Trend-aware Trade Board has strong daily history."
        elif metric_days >= 7:
            status = "Trend-aware Trade Board has usable daily history."
        elif metric_days >= 3:
            status = "Trend-aware Trade Board is still building history."
        else:
            status = "Trend-aware Trade Board needs more daily history."

        return {
            "ok": True,
            "status": status,
            "metric_days": metric_days,
            "items_with_history": items_with_history,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    summary = summarize_trade_board_trend_health()
    print(summary)

def _trend_boost_score_adjustment(row: dict[str, Any]) -> tuple[float, str]:
    direction = str(row.get("Trend Direction") or "").strip().lower()
    confidence = str(row.get("Trend Confidence") or "").strip().lower()
    days_seen = _safe_int(row.get("Days Seen")) or 0
    stability = _safe_float(row.get("Margin Stability")) or 0.0
    score_change = _safe_float(row.get("Score Change")) or 0.0

    adjustment = 0.0
    reasons: list[str] = []

    if direction == "up":
        adjustment += 4.0
        reasons.append("up trend")
    elif direction == "flat":
        adjustment += 1.0
        reasons.append("flat trend")
    elif direction == "mixed":
        adjustment += 0.0
        reasons.append("mixed trend")
    elif direction == "down":
        adjustment -= 5.0
        reasons.append("down trend")
    elif direction == "building":
        adjustment -= 1.0
        reasons.append("building history")
    elif direction == "unavailable":
        adjustment -= 2.0
        reasons.append("trend unavailable")

    if confidence == "high":
        adjustment += 3.0
        reasons.append("high confidence")
    elif confidence == "medium":
        adjustment += 1.0
        reasons.append("medium confidence")
    elif confidence == "low":
        adjustment -= 1.0
        reasons.append("low confidence")

    if days_seen >= 14:
        adjustment += 2.0
        reasons.append("14+ days")
    elif days_seen >= 7:
        adjustment += 1.0
        reasons.append("7+ days")
    elif days_seen > 0:
        adjustment -= 0.5
        reasons.append("short history")

    if stability >= 75:
        adjustment += 2.0
        reasons.append("stable margin")
    elif stability >= 50:
        adjustment += 1.0
        reasons.append("usable stability")
    elif stability > 0:
        adjustment -= 1.0
        reasons.append("unstable margin")

    if score_change >= 10:
        adjustment += 2.0
        reasons.append("score improving")
    elif score_change <= -10:
        adjustment -= 2.0
        reasons.append("score weakening")

    adjustment = max(-10.0, min(10.0, adjustment))

    if not reasons:
        reasons.append("no trend signal")

    return adjustment, ", ".join(reasons)


def apply_trade_board_trend_boost(
    rows: list[dict[str, Any]],
    mode: str = "off",
) -> list[dict[str, Any]]:
    """Add advisory trend boost columns to Trade Board rows.

    Modes:
    - off: return rows unchanged
    - annotate: add Original Score, Trend Boost, Trend Adjusted Score, Trend Boost Reason
    - reorder: add the same columns and sort by Trend Adjusted Score desc

    This function is display-only. It does not write to the database and does not
    automate any GE action.
    """

    mode_value = str(mode or "off").strip().lower()

    if mode_value not in {"annotate", "reorder"}:
        return rows

    if not rows:
        return rows

    score_keys = [
        "Score",
        "score",
        "Trade Score",
        "trade_score",
        "Flip Score",
        "flip_score",
        "Rank Score",
        "rank_score",
    ]

    enriched: list[dict[str, Any]] = []

    for row in rows:
        new_row = dict(row)

        score_key = next((key for key in score_keys if key in new_row), None)
        original_score = _safe_float(new_row.get(score_key)) if score_key else None

        if original_score is None:
            original_score = _safe_float(new_row.get("Expected Profit")) or _safe_float(new_row.get("Total Profit")) or 0.0

        boost, reason = _trend_boost_score_adjustment(new_row)
        adjusted = original_score + boost

        new_row["Original Score"] = _round_or_none(original_score)
        new_row["Trend Boost"] = _round_or_none(boost)
        new_row["Trend Adjusted Score"] = _round_or_none(adjusted)
        new_row["Trend Boost Reason"] = reason
        new_row["Trend Boost Mode"] = mode_value

        enriched.append(new_row)

    if mode_value == "reorder":
        enriched.sort(
            key=lambda item: _safe_float(item.get("Trend Adjusted Score")) or 0.0,
            reverse=True,
        )

    return enriched
