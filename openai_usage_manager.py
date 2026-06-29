import sqlite3
from datetime import datetime, timezone

from account_context import BASE_DIR, get_account_scope
from settings_manager import get_setting


DB_FILE = BASE_DIR / "osrs_flip_scanner.db"


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def today_utc_prefix():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_connection():
    return sqlite3.connect(DB_FILE)


def _safe_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(float(value or 0))
    except Exception:
        return default


def _safe_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value or 0)
    except Exception:
        return default


def get_ai_token_cost_rates():
    input_rate = max(0.0, _safe_float(get_setting("ai_input_cost_per_1m_tokens", 0.0), 0.0))
    output_rate = max(0.0, _safe_float(get_setting("ai_output_cost_per_1m_tokens", 0.0), 0.0))

    return {
        "input_per_1m": input_rate,
        "output_per_1m": output_rate,
        "configured": input_rate > 0 or output_rate > 0,
    }


def estimate_ai_cost(prompt_tokens=0, completion_tokens=0, rates=None):
    rates = rates or get_ai_token_cost_rates()
    prompt_tokens = _safe_int(prompt_tokens)
    completion_tokens = _safe_int(completion_tokens)

    input_cost = (prompt_tokens / 1_000_000) * rates["input_per_1m"]
    output_cost = (completion_tokens / 1_000_000) * rates["output_per_1m"]
    total_cost = input_cost + output_cost

    return {
        "configured": bool(rates.get("configured")),
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": total_cost,
    }


def _decorate_usage_costs(row, rates):
    row = dict(row or {})
    requests = max(0, _safe_int(row.get("total_requests")))
    prompt_tokens = _safe_int(row.get("prompt_tokens"))
    completion_tokens = _safe_int(row.get("completion_tokens"))
    total_tokens = _safe_int(row.get("total_tokens"), prompt_tokens + completion_tokens)
    costs = estimate_ai_cost(prompt_tokens, completion_tokens, rates=rates)

    row["total_tokens"] = total_tokens
    row["prompt_tokens"] = prompt_tokens
    row["completion_tokens"] = completion_tokens
    row["estimated_input_cost"] = costs["input_cost"] if costs["configured"] else None
    row["estimated_output_cost"] = costs["output_cost"] if costs["configured"] else None
    row["estimated_cost"] = costs["total_cost"] if costs["configured"] else None
    row["average_tokens_per_request"] = round(total_tokens / requests, 2) if requests else 0
    row["average_cost_per_request"] = (
        (costs["total_cost"] / requests) if requests and costs["configured"] else None
    )
    return row


def _format_cost(value):
    if value is None:
        return "n/a"

    value = float(value or 0)
    if value < 0.01:
        return f"${value:.5f}"
    return f"${value:.2f}"


def init_ai_usage_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_username TEXT NOT NULL,
            osrs_account_name TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'openai',
            model TEXT,
            request_type TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            success INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_ai_usage_events_account_date
        ON ai_usage_events(app_username, osrs_account_name, created_at)
    """)

    conn.commit()
    conn.close()


def get_daily_ai_limit():
    try:
        value = int(get_setting("max_ai_requests_per_day", 20))
    except Exception:
        value = 20

    # 0 or less means disabled, not unlimited.
    return max(0, value)


def count_ai_requests_today(app_username=None, osrs_account_name=None):
    init_ai_usage_db()
    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)
    prefix = today_utc_prefix()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM ai_usage_events
        WHERE app_username = ?
          AND osrs_account_name = ?
          AND created_at LIKE ?
    """, (
        scope["app_username"],
        scope["osrs_account_name"],
        f"{prefix}%"
    ))

    count = cursor.fetchone()[0] or 0

    conn.close()

    return int(count)


def get_ai_usage_summary(app_username=None, osrs_account_name=None):
    init_ai_usage_db()
    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)
    prefix = today_utc_prefix()

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(*) AS total_requests,
            COALESCE(SUM(success), 0) AS successful_requests,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
            MAX(created_at) AS last_request_at
        FROM ai_usage_events
        WHERE app_username = ?
          AND osrs_account_name = ?
    """, (
        scope["app_username"],
        scope["osrs_account_name"]
    ))

    all_time = dict(cursor.fetchone())

    cursor.execute("""
        SELECT
            COUNT(*) AS total_requests,
            COALESCE(SUM(success), 0) AS successful_requests,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
            MAX(created_at) AS last_request_at
        FROM ai_usage_events
        WHERE app_username = ?
          AND osrs_account_name = ?
          AND created_at LIKE ?
    """, (
        scope["app_username"],
        scope["osrs_account_name"],
        f"{prefix}%"
    ))

    today = dict(cursor.fetchone())

    cursor.execute("""
        SELECT
            model,
            request_type,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            success,
            error_message,
            created_at
        FROM ai_usage_events
        WHERE app_username = ?
          AND osrs_account_name = ?
        ORDER BY id DESC
        LIMIT 1
    """, (
        scope["app_username"],
        scope["osrs_account_name"]
    ))

    latest_row = cursor.fetchone()
    latest = dict(latest_row) if latest_row else {}

    conn.close()
    rates = get_ai_token_cost_rates()
    all_time = _decorate_usage_costs(all_time, rates)
    today = _decorate_usage_costs(today, rates)

    if latest:
        latest_costs = estimate_ai_cost(
            latest.get("prompt_tokens"),
            latest.get("completion_tokens"),
            rates=rates,
        )
        latest["prompt_tokens"] = _safe_int(latest.get("prompt_tokens"))
        latest["completion_tokens"] = _safe_int(latest.get("completion_tokens"))
        latest["total_tokens"] = _safe_int(
            latest.get("total_tokens"),
            latest["prompt_tokens"] + latest["completion_tokens"],
        )
        latest["estimated_cost"] = latest_costs["total_cost"] if latest_costs["configured"] else None

    return {
        "scope": scope,
        "daily_limit": get_daily_ai_limit(),
        "cost_rates": rates,
        "today": today,
        "all_time": all_time,
        "latest": latest,
    }


def format_ai_usage_summary(summary=None):
    summary = summary or get_ai_usage_summary()
    today = summary.get("today") or {}
    all_time = summary.get("all_time") or {}
    latest = summary.get("latest") or {}
    rates = summary.get("cost_rates") or get_ai_token_cost_rates()
    limit = summary.get("daily_limit", 0)

    today_requests = _safe_int(today.get("total_requests"))
    today_tokens = _safe_int(today.get("total_tokens"))
    today_prompt = _safe_int(today.get("prompt_tokens"))
    today_completion = _safe_int(today.get("completion_tokens"))
    all_requests = _safe_int(all_time.get("total_requests"))
    all_tokens = _safe_int(all_time.get("total_tokens"))

    pieces = [
        (
            f"AI usage today: {today_requests}/{limit} requests, "
            f"{today_tokens:,} tokens "
            f"(input {today_prompt:,}, output {today_completion:,})."
        ),
        (
            f"Average today: {today.get('average_tokens_per_request', 0):,.0f} "
            f"tokens/request."
        ),
        f"All time: {all_requests:,} requests, {all_tokens:,} tokens.",
    ]

    if latest:
        pieces.append(
            (
                "Last prompt: "
                f"{_safe_int(latest.get('total_tokens')):,} tokens "
                f"(input {_safe_int(latest.get('prompt_tokens')):,}, "
                f"output {_safe_int(latest.get('completion_tokens')):,}), "
                f"model {latest.get('model') or 'n/a'}, "
                f"status {'ok' if latest.get('success') else 'failed'}."
            )
        )

    if rates.get("configured"):
        pieces.append(
            (
                f"Estimated cost today: {_format_cost(today.get('estimated_cost'))}; "
                f"average/prompt {_format_cost(today.get('average_cost_per_request'))}; "
                f"last prompt {_format_cost(latest.get('estimated_cost') if latest else None)}."
            )
        )
        pieces.append(
            (
                f"Rates: input ${rates.get('input_per_1m', 0):g}/1M tokens, "
                f"output ${rates.get('output_per_1m', 0):g}/1M tokens."
            )
        )
    else:
        pieces.append("Cost estimate off: set input/output $ per 1M tokens in AI Advisor Rules.")

    return " ".join(pieces)


def assert_ai_daily_limit(app_username=None, osrs_account_name=None):
    limit = get_daily_ai_limit()

    if limit <= 0:
        raise RuntimeError(
            "AI Advisor is disabled because max_ai_requests_per_day is set to 0."
        )

    used = count_ai_requests_today(app_username=app_username, osrs_account_name=osrs_account_name)

    if used >= limit:
        raise RuntimeError(
            f"Daily AI request limit reached for this account: {used}/{limit}. "
            "Increase max_ai_requests_per_day in Settings if you intentionally want more AI calls."
        )

    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used)
    }


def extract_usage(response):
    usage = getattr(response, "usage", None)

    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0

    if usage is not None:
        prompt_tokens = int(
            getattr(usage, "input_tokens", None)
            or getattr(usage, "prompt_tokens", None)
            or 0
        )

        completion_tokens = int(
            getattr(usage, "output_tokens", None)
            or getattr(usage, "completion_tokens", None)
            or 0
        )

        total_tokens = int(
            getattr(usage, "total_tokens", None)
            or (prompt_tokens + completion_tokens)
            or 0
        )

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens
    }


def log_ai_usage(
    model=None,
    request_type="advisor",
    response=None,
    success=True,
    error_message=None,
    app_username=None,
    osrs_account_name=None
):
    init_ai_usage_db()

    scope = get_account_scope(app_username=app_username, osrs_account_name=osrs_account_name)
    usage = extract_usage(response)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO ai_usage_events (
            app_username,
            osrs_account_name,
            provider,
            model,
            request_type,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            success,
            error_message,
            created_at
        )
        VALUES (?, ?, 'openai', ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        scope["app_username"],
        scope["osrs_account_name"],
        model,
        request_type,
        int(usage["prompt_tokens"]),
        int(usage["completion_tokens"]),
        int(usage["total_tokens"]),
        1 if success else 0,
        str(error_message or "")[:1000],
        now_utc()
    ))

    conn.commit()
    conn.close()

    return usage


def print_summary():
    summary = get_ai_usage_summary()
    scope = summary["scope"]

    print("\n==============================")
    print(" AI Usage Summary")
    print("==============================")
    print(f"Local user: {scope['app_username']}")
    print(f"OSRS/RuneLite account: {scope['osrs_account_name']}")
    print(f"Daily request limit: {summary['daily_limit']}")
    print()
    print("Today:")
    print(f"  Requests: {summary['today']['total_requests']}")
    print(f"  Successful: {summary['today']['successful_requests']}")
    print(f"  Tokens: {summary['today']['total_tokens']}")
    print(f"  Last request: {summary['today']['last_request_at'] or 'n/a'}")
    print()
    print("All time:")
    print(f"  Requests: {summary['all_time']['total_requests']}")
    print(f"  Successful: {summary['all_time']['successful_requests']}")
    print(f"  Tokens: {summary['all_time']['total_tokens']}")
    print(f"  Last request: {summary['all_time']['last_request_at'] or 'n/a'}")
    print()
    print(format_ai_usage_summary(summary))


if __name__ == "__main__":
    init_ai_usage_db()
    print_summary()
