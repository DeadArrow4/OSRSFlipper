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

    conn.close()

    return {
        "scope": scope,
        "daily_limit": get_daily_ai_limit(),
        "today": today,
        "all_time": all_time
    }


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


if __name__ == "__main__":
    init_ai_usage_db()
    print_summary()
