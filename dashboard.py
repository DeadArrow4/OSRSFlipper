import os

from security_runtime import scrub_shared_openai_env

scrub_shared_openai_env()

from dash import Dash

# Importing dashboard_theme patches Dash inputs, dropdowns, and DataTables
# before the layout is built.
import dashboard_theme  # noqa: F401

from dashboard_callbacks import register_dashboard_callbacks
from dashboard_tabs import build_app_layout


# =========================
# DASH APP
# =========================

app = Dash(__name__)
app.title = "OSRS Flip Dashboard"
server = app.server

app.layout = build_app_layout()

register_dashboard_callbacks(app)


if __name__ == "__main__":
    app.run(
        debug=True,
        dev_tools_ui=False,
        use_reloader=False,
        dev_tools_hot_reload=False
    )
