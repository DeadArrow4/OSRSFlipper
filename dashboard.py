import os

from security_runtime import scrub_shared_openai_env

scrub_shared_openai_env()

from dash import Dash
from flask import abort, request

# Importing dashboard_theme patches Dash inputs, dropdowns, and DataTables
# before the layout is built.
import dashboard_theme  # noqa: F401

from dashboard_auth import (
    build_dashboard_auth_layout,
    configure_dashboard_auth,
    dashboard_is_unlocked,
    register_dashboard_auth_callbacks,
    should_block_locked_dashboard_callback,
)
from dashboard_callbacks import register_dashboard_callbacks
from dashboard_tabs import build_app_layout


# =========================
# DASH APP
# =========================

app = Dash(__name__, suppress_callback_exceptions=True)
app.title = "OSRSFlipper"
server = app.server
configure_dashboard_auth(server)


@server.before_request
def enforce_local_dashboard_access():
    """Keep the dashboard local unless the user explicitly opts into remote access."""

    allow_remote = os.getenv("OSRSFLIPPER_ALLOW_REMOTE_DASHBOARD", "").strip().lower()
    if allow_remote in {"1", "true", "yes"}:
        return None

    remote_addr = str(request.remote_addr or "").strip()
    if remote_addr not in {"127.0.0.1", "::1", "localhost"}:
        abort(403)

    if should_block_locked_dashboard_callback():
        abort(403)

    return None


@server.after_request
def add_local_security_headers(response):
    response.headers.setdefault("Cache-Control", "no-store, max-age=0")
    response.headers.setdefault("Pragma", "no-cache")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


def serve_layout():
    if dashboard_is_unlocked():
        return build_app_layout()
    return build_dashboard_auth_layout()


app.layout = serve_layout

register_dashboard_callbacks(app)
register_dashboard_auth_callbacks(app)


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=8050,
        debug=False,
        dev_tools_ui=False,
        use_reloader=False,
        dev_tools_hot_reload=False
    )
