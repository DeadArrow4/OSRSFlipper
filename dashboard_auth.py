"""Dashboard-local authentication gate for OSRSFlipper."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from dash import Input, Output, State, ctx, dcc, html, no_update
from flask import has_request_context, request, session as flask_session

from account_manager import (
    authenticate_user,
    create_user,
    get_current_session,
    list_users,
    normalize_username,
    user_has_dashboard_pin,
    validate_dashboard_pin,
    verify_dashboard_pin,
)
from app_version import get_version_line


AUTH_SESSION_KEY = "osrsflipper_dashboard_unlocked_user"
AUTH_UNLOCKED_AT_KEY = "osrsflipper_dashboard_unlocked_at"


def _now_utc():
    return datetime.now(timezone.utc).isoformat()


def configure_dashboard_auth(server):
    """Configure an in-memory session secret for this dashboard run."""

    server.secret_key = secrets.token_hex(32)
    server.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=False,
    )


def _current_username():
    current = get_current_session() or {}
    return normalize_username(current.get("username"))


def unlock_dashboard_for_user(username):
    username = normalize_username(username)
    flask_session[AUTH_SESSION_KEY] = username
    flask_session[AUTH_UNLOCKED_AT_KEY] = _now_utc()
    flask_session.modified = True


def lock_dashboard():
    flask_session.pop(AUTH_SESSION_KEY, None)
    flask_session.pop(AUTH_UNLOCKED_AT_KEY, None)
    flask_session.modified = True


def dashboard_is_unlocked():
    if not has_request_context():
        return False

    username = _current_username()

    if not username:
        return False

    unlocked_user = normalize_username(flask_session.get(AUTH_SESSION_KEY))

    if unlocked_user != username:
        return False

    return True


def _callback_targets_auth_layout(payload):
    if not isinstance(payload, dict):
        return False

    chunks = []
    output = payload.get("output")

    if output is not None:
        chunks.append(str(output))

    outputs = payload.get("outputs")

    if isinstance(outputs, dict):
        chunks.extend(str(value) for value in outputs.values())
        chunks.extend(str(value) for value in outputs.keys())
    elif isinstance(outputs, list):
        for item in outputs:
            if isinstance(item, dict):
                chunks.extend(str(value) for value in item.values())
                chunks.extend(str(value) for value in item.keys())
            else:
                chunks.append(str(item))

    return any("dashboard-auth-" in chunk for chunk in chunks)


def should_block_locked_dashboard_callback():
    """Block non-auth Dash callbacks when the dashboard is locked."""

    if not str(request.path or "").rstrip("/").endswith("_dash-update-component"):
        return False

    if dashboard_is_unlocked():
        return False

    payload = request.get_json(silent=True) or {}
    return not _callback_targets_auth_layout(payload)


def _field(label, component, help_text=None):
    children = [
        html.Div(label, className="auth-field-label"),
        component,
    ]

    if help_text:
        children.append(html.Div(help_text, className="auth-field-help"))

    return html.Div(className="auth-field", children=children)


def _pin_input(component_id, placeholder="4-8 digit PIN"):
    return dcc.Input(
        id=component_id,
        type="password",
        inputMode="numeric",
        maxLength=8,
        placeholder=placeholder,
    )


def _password_input(component_id, placeholder="local OSRSFlipper password"):
    return dcc.Input(
        id=component_id,
        type="password",
        placeholder=placeholder,
    )


def _text_input(component_id, placeholder):
    return dcc.Input(
        id=component_id,
        type="text",
        placeholder=placeholder,
    )


def build_dashboard_auth_layout():
    current = get_current_session() or {}
    current_username = normalize_username(current.get("username"))

    try:
        users = list_users()
    except Exception:
        users = []

    has_users = bool(users)
    current_has_pin = bool(current_username and user_has_dashboard_pin(current_username))
    default_tab = "create"

    if current_username and current_has_pin:
        session_text = f"Saved local session: {current_username}"
        unlock_help = "Enter the dashboard PIN for this saved OSRSFlipper user."
        default_tab = "pin"
    elif current_username:
        session_text = f"Saved local session needs a PIN: {current_username}"
        unlock_help = (
            "This older account does not have a dashboard PIN yet. "
            "Sign in with the local password, then set the PIN from Admin > Account Manager."
        )
        default_tab = "signin"
    elif has_users:
        session_text = "No saved session is active."
        unlock_help = "Sign in with your local OSRSFlipper username and password."
        default_tab = "signin"
    else:
        session_text = "No local OSRSFlipper users exist yet."
        unlock_help = "Create your first local user to unlock the dashboard."
        default_tab = "create"

    pin_tab = dcc.Tab(
        label="PIN",
        value="pin",
        className="tab",
        selected_className="tab--selected",
        disabled=not current_has_pin,
        children=[
            html.Div(
                className="auth-panel auth-panel--focused",
                children=[
                    html.Div("Saved Session", className="auth-panel-title"),
                    html.Div(
                        "Unlocks the remembered local OSRSFlipper user on this machine.",
                        className="muted-text",
                    ),
                    _field(
                        "Dashboard PIN",
                        _pin_input("dashboard-auth-pin"),
                    ),
                    html.Button(
                        "Unlock Dashboard",
                        id="dashboard-auth-unlock-button",
                        n_clicks=0,
                        className="primary-button",
                        disabled=not current_has_pin,
                    ),
                ],
            )
        ],
    )

    signin_tab = dcc.Tab(
        label="Sign In",
        value="signin",
        className="tab",
        selected_className="tab--selected",
        disabled=not has_users,
        children=[
            html.Div(
                className="auth-panel auth-panel--focused",
                children=[
                    html.Div("Sign In", className="auth-panel-title"),
                    html.Div(
                        "Use your local OSRSFlipper password. Never enter a Jagex password here.",
                        className="muted-text",
                    ),
                    _field("Username", _text_input("dashboard-auth-username", "local username")),
                    _field("Password", _password_input("dashboard-auth-password")),
                    html.Button(
                        "Sign In",
                        id="dashboard-auth-signin-button",
                        n_clicks=0,
                        className="primary-button",
                        disabled=not has_users,
                    ),
                ],
            )
        ],
    )

    create_tab = dcc.Tab(
        label="Create Account",
        value="create",
        className="tab",
        selected_className="tab--selected",
        children=[
            html.Div(
                className="auth-panel auth-panel--focused",
                children=[
                    html.Div("Create Local Account", className="auth-panel-title"),
                    html.Div(
                        "Create a local OSRSFlipper user and dashboard PIN for this computer.",
                        className="muted-text",
                    ),
                    _field("Username", _text_input("dashboard-auth-create-username", "new local username")),
                    _field("Password", _password_input("dashboard-auth-create-password", "new local password")),
                    _field("Confirm password", _password_input("dashboard-auth-create-confirm-password", "confirm password")),
                    _field("Dashboard PIN", _pin_input("dashboard-auth-create-pin")),
                    _field("Confirm PIN", _pin_input("dashboard-auth-create-confirm-pin")),
                    _field("RuneLite/OSRS account", _text_input("dashboard-auth-create-osrs-account", "RuneLite account name")),
                    html.Button(
                        "Create Account",
                        id="dashboard-auth-create-button",
                        n_clicks=0,
                        className="primary-button",
                    ),
                ],
            )
        ],
    )

    return html.Div(
        className="auth-shell",
        children=[
            dcc.Location(id="dashboard-auth-location", refresh=True),
            html.Div(
                className="auth-card",
                children=[
                    html.Div(
                        className="auth-header",
                        children=[
                            html.Div("OSRSFlipper", className="auth-title"),
                            html.Div(get_version_line(), className="auth-version"),
                        ],
                    ),
                    html.Div("Dashboard Unlock", className="section-title"),
                    html.Div(session_text, className="auth-session-summary"),
                    html.Div(unlock_help, className="muted-text"),
                    html.Div(id="dashboard-auth-status", className="status-text"),
                    dcc.Tabs(
                        id="dashboard-auth-tabs",
                        value=default_tab,
                        persistence=False,
                        className="dash-tabs auth-tabs",
                        children=[pin_tab, signin_tab, create_tab],
                    ),
                ],
            ),
        ],
    )


def register_dashboard_auth_callbacks(app):
    @app.callback(
        Output("dashboard-auth-status", "children"),
        Output("dashboard-auth-location", "href"),
        Input("dashboard-auth-unlock-button", "n_clicks"),
        Input("dashboard-auth-signin-button", "n_clicks"),
        Input("dashboard-auth-create-button", "n_clicks"),
        State("dashboard-auth-pin", "value"),
        State("dashboard-auth-username", "value"),
        State("dashboard-auth-password", "value"),
        State("dashboard-auth-create-username", "value"),
        State("dashboard-auth-create-password", "value"),
        State("dashboard-auth-create-confirm-password", "value"),
        State("dashboard-auth-create-pin", "value"),
        State("dashboard-auth-create-confirm-pin", "value"),
        State("dashboard-auth-create-osrs-account", "value"),
        prevent_initial_call=True,
    )
    def handle_dashboard_auth(
        unlock_clicks,
        signin_clicks,
        create_clicks,
        saved_pin,
        signin_username,
        signin_password,
        create_username,
        create_password,
        create_confirm_password,
        create_pin,
        create_confirm_pin,
        create_osrs_account,
    ):
        triggered_id = ctx.triggered_id

        if not triggered_id:
            return "", no_update

        try:
            if triggered_id == "dashboard-auth-unlock-button":
                current = get_current_session() or {}
                username = normalize_username(current.get("username"))

                if not username:
                    return "No saved session is available. Sign in or create a user.", no_update

                if not verify_dashboard_pin(username, saved_pin):
                    lock_dashboard()
                    return "Invalid dashboard PIN.", no_update

                unlock_dashboard_for_user(username)
                return "Dashboard unlocked.", "/"

            if triggered_id == "dashboard-auth-signin-button":
                username = normalize_username(signin_username)
                password = str(signin_password or "")

                if not username or not password:
                    return "Enter username and password.", no_update

                user = authenticate_user(username, password)

                if not user:
                    lock_dashboard()
                    return "Invalid username or password.", no_update

                unlock_dashboard_for_user(username)
                return "Dashboard unlocked.", "/"

            if triggered_id == "dashboard-auth-create-button":
                username = normalize_username(create_username)
                password = str(create_password or "")
                confirm_password = str(create_confirm_password or "")
                pin = str(create_pin or "").strip()
                confirm = str(create_confirm_pin or "").strip()
                osrs_account_name = str(create_osrs_account or "").strip()

                if not username:
                    return "Username is required.", no_update

                if not osrs_account_name:
                    return "RuneLite/OSRS account name is required.", no_update

                if password != confirm_password:
                    return "Passwords do not match.", no_update

                if len(password) < 6:
                    return "Password must be at least 6 characters.", no_update

                if pin != confirm:
                    return "PINs do not match.", no_update

                valid_pin, pin_message = validate_dashboard_pin(pin)

                if not valid_pin:
                    return pin_message, no_update

                create_user(
                    username=username,
                    password=password,
                    osrs_account_name=osrs_account_name,
                    dashboard_pin=pin,
                )
                authenticate_user(username, password)
                unlock_dashboard_for_user(username)
                return "Account created and dashboard unlocked.", "/"

            return "", no_update

        except Exception as error:
            lock_dashboard()
            return f"Dashboard unlock failed: {type(error).__name__}: {error}", no_update
