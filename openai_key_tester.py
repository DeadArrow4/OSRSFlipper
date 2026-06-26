from datetime import datetime, timezone

from openai import OpenAI, AuthenticationError, RateLimitError, APIError

from openai_key_manager import get_api_key, get_api_key_status
from openai_usage_manager import assert_ai_daily_limit, log_ai_usage
from security_runtime import get_non_secret_env_value, scrub_shared_openai_env


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def test_current_account_openai_key():
    """
    Makes one tiny OpenAI request using the current OSRSFlipper account's
    encrypted API key.

    This intentionally does not use .env OPENAI_API_KEY fallback.
    The request is logged in ai_usage_events with request_type='api_key_test'.
    """
    scrub_shared_openai_env()

    key_status = get_api_key_status()
    api_key = get_api_key(mark_used=True)

    if not api_key:
        return {
            "ok": False,
            "message": (
                "No encrypted OpenAI API key is saved for this OSRSFlipper account. "
                "Save the key in Setup or Settings first."
            ),
            "key_hint": "not set",
            "model": None,
            "usage": {}
        }

    try:
        limit_status = assert_ai_daily_limit()
    except Exception as error:
        return {
            "ok": False,
            "message": str(error),
            "key_hint": key_status.get("key_hint", "set"),
            "model": None,
            "usage": {}
        }

    model = get_non_secret_env_value("OPENAI_MODEL", "gpt-5.5")
    client = OpenAI(api_key=api_key, timeout=20.0)

    try:
        response = client.responses.create(
            model=model,
            instructions=(
                "You are only verifying that an API key works. "
                "Reply with exactly: OK"
            ),
            input="Return OK.",
            max_output_tokens=8
        )

        usage = log_ai_usage(
            model=model,
            request_type="api_key_test",
            response=response,
            success=True
        )

        return {
            "ok": True,
            "message": (
                f"OpenAI API key test succeeded using {model}. "
                f"Daily requests before this test: {limit_status['used']}/{limit_status['limit']}. "
                f"Usage logged: {usage.get('total_tokens', 0)} total tokens."
            ),
            "key_hint": key_status.get("key_hint", "set"),
            "model": model,
            "usage": usage
        }

    except AuthenticationError as error:
        log_ai_usage(
            model=model,
            request_type="api_key_test",
            success=False,
            error_message="Authentication failed during API key test."
        )

        return {
            "ok": False,
            "message": "Authentication failed. The saved OpenAI API key is invalid or revoked.",
            "key_hint": key_status.get("key_hint", "set"),
            "model": model,
            "usage": {}
        }

    except RateLimitError as error:
        log_ai_usage(
            model=model,
            request_type="api_key_test",
            success=False,
            error_message="Rate limit or quota error during API key test."
        )

        return {
            "ok": False,
            "message": "Rate limit or quota error. Check this user's OpenAI billing, quota, or project limits.",
            "key_hint": key_status.get("key_hint", "set"),
            "model": model,
            "usage": {}
        }

    except APIError as error:
        log_ai_usage(
            model=model,
            request_type="api_key_test",
            success=False,
            error_message=f"OpenAI API error during key test: {error}"
        )

        return {
            "ok": False,
            "message": f"OpenAI API error: {error}",
            "key_hint": key_status.get("key_hint", "set"),
            "model": model,
            "usage": {}
        }

    except Exception as error:
        log_ai_usage(
            model=model,
            request_type="api_key_test",
            success=False,
            error_message=f"Unexpected error during key test: {error}"
        )

        return {
            "ok": False,
            "message": f"Unexpected API key test error: {error}",
            "key_hint": key_status.get("key_hint", "set"),
            "model": model,
            "usage": {}
        }


if __name__ == "__main__":
    result = test_current_account_openai_key()

    print("\n==============================")
    print(" OpenAI API Key Test")
    print("==============================")
    print(f"Status: {'PASS' if result['ok'] else 'FAIL'}")
    print(f"Key: {result.get('key_hint', 'not set')}")
    print(f"Model: {result.get('model') or 'n/a'}")
    print(result["message"])
