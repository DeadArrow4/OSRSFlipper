"""
Dash callback registration for the OSRSFlipper dashboard.

Keep callbacks here so dashboard.py can stay small and easy to scan.
"""
import os

import plotly.express as px
from dash import dcc, html, Input, Output, State, ALL, ctx, no_update

from account_context import apply_account_env
from account_manager import (
    authenticate_user,
    create_user,
    get_current_session,
    save_session,
    set_dashboard_pin,
    update_osrs_account,
    user_has_dashboard_pin,
    validate_dashboard_pin,
    verify_dashboard_pin,
)
from dashboard_auth import unlock_dashboard_for_user
from advisor import generate_ai_advice
from backup_manager import create_private_backup
from migration_manager import run_app_migrations
from openai_key_manager import (
    delete_api_key,
    get_api_key_status,
    save_api_key,
    validate_key_shape,
)
from openai_key_tester import test_current_account_openai_key
from omitted_items import omit_item, restore_omitted_item
from openai_usage_manager import format_ai_usage_summary, get_ai_usage_summary, init_ai_usage_db
from flip_decision_engine import build_flip_plan_snapshot
from offer_intents import clear_offer_intent, mark_offer_overnight
from prepare_release import prepare_clean_release_package
from release_check import run_release_check
from safety_manager import build_safety_review, write_safety_review
from settings_manager import set_setting
from update_install import install_update

from dashboard_data import (
    BASE_DIR,
    LOG_DIR,
    OVERNIGHT_RAW_MARGIN_MIN,
    OVERNIGHT_ROI_MIN,
    add_chart_size,
    backup_database_file,
    clear_all_dashboard_caches,
    clear_current_account_ai_notes,
    clear_dashboard_cache,
    clear_log_files,
    clear_trade_dashboard_cache,
    export_ai_notes_csv,
    export_completed_trades_csv,
    export_latest_scan_csv,
    export_trade_events_csv,
    get_account_manager_rows,
    get_best_recurring_flips,
    get_completed_trade_history,
    get_current_trade_scope,
    get_filtered_latest,
    get_item_history_for_item,
    get_item_options,
    get_live_ge_offer_rows,
    get_open_slot_actions,
    get_open_trade_rows,
    get_omitted_item_rows,
    get_setup_summary_items,
    get_status_summary,
    get_trade_board_recommendations,
    get_trade_summary,
    get_transaction_history_rows,
    import_runelite_now,
    optimize_database_file,
    read_last_lines,
    read_saved_ai_advice,
    refresh_runelite_trades_for_dashboard,
    reset_ai_advice_file,
    run_health_check_report,
)
from dashboard_formatters import (
    build_latest_display_df,
    clean_trade_display_df,
    format_gp,
    format_percent,
    parse_positive_int,
    trade_table_columns,
)
from dashboard_tabs import build_status_cards
from dashboard_theme import (
    apply_dark_chart_layout,
    empty_figure,
    make_card,
)
from data_health import (
    build_data_health_snapshot,
    build_data_trend_snapshot,
    build_database_backup_snapshot,
    build_database_compaction_preview_snapshot,
    build_item_trend_explorer_snapshot,
    build_maintenance_events_snapshot,
    build_metrics_automation_snapshot,
    build_retention_preview_snapshot,
    cleanup_scan_results_with_backup_guard,
    create_compacted_database_copy,
    create_database_safety_backup,
    ensure_data_health_schema,
    rebuild_daily_item_metrics,
    refresh_daily_metrics_if_stale,
)
from dashboard_control_commands import schedule_dashboard_shutdown, write_dashboard_command
from trade_trends import (
    apply_trade_board_trend_boost,
    enrich_trade_board_rows_with_trends,
    summarize_trade_board_trend_health,
)

try:
    from capital_dashboard import register_capital_ai_callbacks
except Exception:
    def register_capital_ai_callbacks(app):
        return None


def _columns_for_records(rows):
    if not rows:
        return []

    return [{"name": str(key), "id": str(key)} for key in rows[0].keys()]


def _columns_for_names(names):
    return [{"name": str(name), "id": str(name)} for name in names]


def _visible_columns_for_records(rows, preferred_names):
    if not rows:
        return _columns_for_names(preferred_names)

    available = set(rows[0].keys())
    names = [name for name in preferred_names if name in available]
    return _columns_for_names(names)


def _enrich_trade_board_dataframe_with_trends(board_df):
    """Add read-only trend columns to the Trade Board dataframe.

    This helper is intentionally defensive. If trend history is missing or a
    schema edge case appears, the Trade Board still loads with the original rows.
    """

    try:
        if board_df is None:
            return board_df, "no Trade Board rows"

        if getattr(board_df, "empty", False):
            return board_df, "no Trade Board rows"

        if hasattr(board_df, "to_dict"):
            records = board_df.to_dict("records")
        else:
            records = list(board_df or [])

        if not records:
            return board_df, "no Trade Board rows"

        enriched_records = enrich_trade_board_rows_with_trends(records)

        if hasattr(board_df, "columns"):
            return board_df.__class__(enriched_records), f"trend columns added to {len(enriched_records)} row(s)"

        return enriched_records, f"trend columns added to {len(enriched_records)} row(s)"
    except Exception as exc:
        return board_df, f"trend enrichment skipped: {type(exc).__name__}: {str(exc)[:120]}"

def register_dashboard_callbacks(app):
    register_capital_ai_callbacks(app)


    @app.callback(
        Output("dashboard-control-status", "children"),
        Input("dashboard-refresh-status-button", "n_clicks"),
        Input("dashboard-stop-services-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_dashboard_command_buttons(refresh_clicks, stop_clicks):
        from datetime import datetime

        triggered_id = ctx.triggered_id

        try:
            if triggered_id == "dashboard-refresh-status-button":
                write_dashboard_command("refresh_status")
                return f"Status refresh requested {datetime.now().strftime('%H:%M:%S')}."

            if triggered_id == "dashboard-stop-services-button":
                write_dashboard_command("stop_all")
                schedule_dashboard_shutdown()
                return "Stop requested. Services and dashboard are closing."

            return ""

        except Exception as error:
            return f"Dashboard command failed: {type(error).__name__}: {error}"


    @app.callback(
        Output("flip-plan-status", "children"),
        Output("flip-plan-updated", "children"),
        Output("flip-plan-kpi-cards", "children"),
        Output("flip-buy-plan-records", "data"),
        Output("flip-offer-plan-table", "data"),
        Output("flip-offer-plan-table", "columns"),
        Output("flip-plan-notes-list", "children"),
        Input("flip-plan-refresh-button", "n_clicks"),
        Input("auto-refresh", "n_intervals"),
        Input("dashboard-refresh-status-button", "n_clicks"),
        Input("flip-offer-intents-version", "data"),
    )
    def update_flip_plan(refresh_clicks, intervals, status_clicks, offer_intents_version):
        try:
            snapshot = build_flip_plan_snapshot(max_buy_rows=12)
            summary = snapshot.get("summary") or {}
            buy_rows = snapshot.get("buy_plan") or [
                {
                    "Action": "Wait",
                    "Item": "No capital-fit buy",
                    "Why": "Current GP, open slots, filters, or market conditions do not support a strong new buy.",
                }
            ]
            offer_rows = snapshot.get("offer_plan") or [
                {
                    "Action": "No active offer",
                    "Item": "",
                    "Reason": "No active RuneLite GE offers are available in the current capital snapshot.",
                }
            ]
            for row in buy_rows:
                if row.get("Buy") or row.get("Sell"):
                    row["Target"] = f"{row.get('Buy', 'n/a')} -> {row.get('Sell', 'n/a')}"
                row["Profit"] = row.get("Projected Profit", "")

            for row in offer_rows:
                row["P/L"] = row.get("Projected P/L", "")

            notes = snapshot.get("notes") or [
                {
                    "Topic": "Plan",
                    "Note": "Run the collector and RuneLite telemetry import to build a current plan.",
                }
            ]
            note_cards = [
                html.Div(
                    className="flip-plan-note",
                    children=[
                        html.Div(note.get("Topic", "Note"), className="flip-plan-note-title"),
                        html.Div(note.get("Note", ""), className="flip-plan-note-body"),
                    ],
                )
                for note in notes
            ]

            card_subtitles = {
                "Raw GP": "cash currently visible",
                "Usable GP": "after cap/reserve rules",
                "Free Slots": "Grand Exchange slots",
                "Offer P/L": "projected active-offer result",
                "Next Buy": "top capital-fit candidate",
                "Wait": "expected patience window",
            }
            cards = [
                make_card(name, value, card_subtitles.get(name, ""))
                for name, value in summary.items()
            ]

            offer_visible_columns = [
                "Action",
                "Item",
                "Qty",
                "Sell Price",
                "Recommended Sell",
                "P/L",
                "Wait",
            ]

            status = snapshot.get("status", "")
            updated = f"Updated {snapshot.get('generated_at', '')}."

            return (
                status,
                updated,
                cards,
                buy_rows,
                offer_rows,
                _visible_columns_for_records(offer_rows, offer_visible_columns),
                note_cards,
            )

        except Exception as error:
            error_note = f"Next Moves failed: {type(error).__name__}: {error}"
            return (
                error_note,
                "",
                [make_card("Next Moves", "Error", "review dashboard logs")],
                [{"Action": "Error", "Item": "", "Why": error_note}],
                [{"Action": "Error", "Item": "", "Reason": error_note}],
                _columns_for_names(["Action", "Item", "Reason"]),
                [
                    html.Div(
                        className="flip-plan-note",
                        children=[
                            html.Div("Error", className="flip-plan-note-title"),
                            html.Div(error_note, className="flip-plan-note-body"),
                        ],
                    )
                ],
            )


    def _selected_table_row(active_cell, rows, default_index=0):
        rows = rows or []
        if not rows:
            return {}

        row_index = default_index
        if active_cell and active_cell.get("row") is not None:
            try:
                row_index = int(active_cell.get("row"))
            except Exception:
                row_index = default_index

        if row_index < 0 or row_index >= len(rows):
            row_index = 0

        return rows[row_index] or {}


    def _detail_field(label, value):
        value = "" if value is None else str(value)
        if not value:
            value = "n/a"

        return html.Div(
            className="flip-plan-detail-field",
            children=[
                html.Div(label, className="flip-plan-detail-label"),
                html.Div(value, className="flip-plan-detail-value"),
            ],
        )


    def _safe_selected_index(selected_index, rows):
        rows = rows or []
        if not rows:
            return 0

        try:
            selected_index = int(selected_index or 0)
        except Exception:
            selected_index = 0

        if selected_index < 0 or selected_index >= len(rows):
            return 0

        return selected_index


    def _candidate_metric(label, value):
        value = "" if value is None else str(value)
        if not value:
            value = "n/a"

        return html.Span(
            className="flip-candidate-metric",
            children=[
                html.Span(label, className="flip-candidate-metric-label"),
                html.Span(value, className="flip-candidate-metric-value"),
            ],
        )


    def _buy_candidate_button(row, index, selected_index):
        action = str(row.get("Action") or "Review")
        item = str(row.get("Item") or "Unknown item")
        target = row.get("Target")
        if not target and (row.get("Buy") or row.get("Sell")):
            target = f"{row.get('Buy', 'n/a')} -> {row.get('Sell', 'n/a')}"

        classes = ["flip-candidate-row"]
        if index == selected_index:
            classes.append("is-selected")

        return html.Button(
            id={"type": "flip-buy-candidate-button", "index": index},
            n_clicks=0,
            type="button",
            className=" ".join(classes),
            title=f"{action}: {item}",
            children=[
                html.Span(action, className="flip-candidate-action"),
                html.Span(
                    className="flip-candidate-main",
                    children=[
                        html.Span(item, className="flip-candidate-item"),
                        html.Span(row.get("Why") or "Open for details.", className="flip-candidate-reason"),
                    ],
                ),
                _candidate_metric("Target", target),
                _candidate_metric("Qty", row.get("Qty")),
                _candidate_metric("Profit", row.get("Profit") or row.get("Projected Profit")),
                _candidate_metric("Wait", row.get("Wait")),
            ],
        )


    @app.callback(
        Output("flip-buy-selected-index", "data"),
        Input({"type": "flip-buy-candidate-button", "index": ALL}, "n_clicks"),
        State("flip-buy-selected-index", "data"),
        prevent_initial_call=True,
    )
    def select_flip_buy_candidate(candidate_clicks, current_index):
        triggered_id = ctx.triggered_id

        if isinstance(triggered_id, dict) and triggered_id.get("type") == "flip-buy-candidate-button":
            try:
                return int(triggered_id.get("index", 0))
            except Exception:
                return int(current_index or 0)

        return int(current_index or 0)


    @app.callback(
        Output("flip-buy-candidate-list", "children"),
        Output("flip-buy-plan-detail", "children"),
        Input("flip-buy-plan-records", "data"),
        Input("flip-buy-selected-index", "data"),
    )
    def render_flip_buy_candidates(rows, selected_index):
        rows = rows or []
        selected_index = _safe_selected_index(selected_index, rows)
        if not rows:
            empty_detail = "No capital-fit buy candidates are available right now."
            return (
                html.Div(empty_detail, className="muted-text flip-buy-candidate-empty"),
                empty_detail,
            )

        row = rows[selected_index] or {}
        candidate_list = [
            html.Div(
                f"{len(rows)} buy candidates. Select one to inspect prices, quantity, wait time, and reasoning.",
                className="muted-text flip-buy-candidate-summary",
            )
        ]
        candidate_list.extend(
            _buy_candidate_button(candidate, index, selected_index)
            for index, candidate in enumerate(rows)
        )

        detail = html.Div(
            className="flip-plan-detail-content",
            children=[
                html.Div(
                    className="flip-plan-detail-title",
                    children=f"{row.get('Action', 'Review')} - {row.get('Item', '')}",
                ),
                _detail_field("Why", row.get("Why")),
                _detail_field("Capital Note", row.get("Capital Note")),
                html.Div(
                    className="flip-plan-detail-grid",
                    children=[
                        _detail_field("Buy", row.get("Buy")),
                        _detail_field("Sell", row.get("Sell")),
                        _detail_field("Quantity", row.get("Qty")),
                        _detail_field("Use GP", row.get("Use GP")),
                        _detail_field("Projected Profit", row.get("Projected Profit")),
                        _detail_field("Wait", row.get("Wait")),
                        _detail_field("ROI", row.get("ROI")),
                        _detail_field("Confidence", row.get("Confidence")),
                    ],
                ),
            ],
        )

        return candidate_list, detail


    @app.callback(
        Output("flip-offer-plan-detail", "children"),
        Input("flip-offer-plan-table", "active_cell"),
        Input("flip-offer-plan-table", "selected_rows"),
        Input("flip-offer-plan-table", "derived_virtual_selected_rows"),
        Input("flip-offer-plan-table", "derived_virtual_data"),
        Input("flip-offer-plan-table", "data"),
    )
    def update_flip_offer_detail(active_cell, selected_rows, visible_selected_rows, visible_rows, all_rows):
        rows = visible_rows or all_rows or []

        selected_index = 0
        active_selected_rows = visible_selected_rows or selected_rows or []
        if active_cell and active_cell.get("row") is not None:
            try:
                selected_index = int(active_cell.get("row"))
            except Exception:
                selected_index = 0
        elif active_selected_rows:
            try:
                selected_index = int(active_selected_rows[0])
            except Exception:
                selected_index = 0

        row = _selected_table_row(None, rows, default_index=selected_index)
        if not row:
            return "Click an offer row to see the tax, reason, and overnight status."

        return html.Div(
            className="flip-plan-detail-content",
            children=[
                html.Div(
                    className="flip-plan-detail-title",
                    children=f"{row.get('Action', 'Review')} - {row.get('Item', '')}",
                ),
                _detail_field("Reason", row.get("Reason")),
                html.Div(
                    className="flip-plan-detail-grid",
                    children=[
                        _detail_field("Side", row.get("Side")),
                        _detail_field("Quantity", row.get("Qty")),
                        _detail_field("Buy Price", row.get("Buy Price")),
                        _detail_field("Sell Price", row.get("Sell Price")),
                        _detail_field("Recommended Sell", row.get("Recommended Sell")),
                        _detail_field("Tax Total", row.get("Tax Total")),
                        _detail_field("Projected P/L", row.get("Projected P/L")),
                        _detail_field("Wait", row.get("Wait")),
                    ],
                ),
            ],
        )


    @app.callback(
        Output("flip-offer-intent-status", "children"),
        Output("flip-offer-intents-version", "data"),
        Output("flip-offer-plan-table", "selected_rows"),
        Input("flip-mark-overnight-button", "n_clicks"),
        Input("flip-clear-overnight-button", "n_clicks"),
        State("flip-offer-plan-table", "selected_rows"),
        State("flip-offer-plan-table", "derived_virtual_selected_rows"),
        State("flip-offer-plan-table", "derived_virtual_data"),
        State("flip-offer-plan-table", "data"),
        State("flip-offer-intents-version", "data"),
        prevent_initial_call=True,
    )
    def update_flip_offer_intent(mark_clicks, clear_clicks, selected_rows, visible_selected_rows, visible_rows, all_rows, version):
        triggered_id = ctx.triggered_id
        active_selected_rows = visible_selected_rows or selected_rows or []
        rows = visible_rows if visible_selected_rows else all_rows
        rows = rows or []

        if not active_selected_rows:
            return "Select one current offer row first.", int(version or 0), no_update

        row_index = int(active_selected_rows[0])
        if row_index < 0 or row_index >= len(rows):
            return "The selected offer row is no longer available.", int(version or 0), []

        row = rows[row_index] or {}

        try:
            if triggered_id == "flip-mark-overnight-button":
                result = mark_offer_overnight(row)
                item_name = result.get("item_name") or row.get("Item") or "offer"
                version = int(version or 0) + 1
                return (
                    f"Marked {item_name} as an overnight hold until tomorrow.",
                    version,
                    [],
                )

            if triggered_id == "flip-clear-overnight-button":
                cleared = clear_offer_intent(row)
                item_name = row.get("Item") or "offer"
                version = int(version or 0) + 1 if cleared else int(version or 0)
                status = (
                    f"Cleared overnight hold for {item_name}."
                    if cleared
                    else f"No active overnight hold found for {item_name}."
                )
                return status, version, []

            return "", int(version or 0), no_update

        except Exception as error:
            return f"Offer intent update failed: {type(error).__name__}: {error}", int(version or 0), no_update


    @app.callback(
        Output("omitted-items-table", "data"),
        Output("omitted-items-table", "columns"),
        Output("omit-item-status", "children"),
        Output("omit-items-version", "data"),
        Output("omit-item-dropdown", "options"),
        Input("omit-item-button", "n_clicks"),
        Input("omit-selected-trade-board-item-button", "n_clicks"),
        Input("restore-omitted-item-button", "n_clicks"),
        State("omit-item-dropdown", "value"),
        State("omit-item-reason", "value"),
        State("trade-board-table", "active_cell"),
        State("trade-board-table", "derived_virtual_data"),
        State("trade-board-table", "data"),
        State("omitted-items-table", "selected_rows"),
        State("omitted-items-table", "data"),
        State("omit-items-version", "data"),
    )
    def update_omitted_items(
        omit_clicks,
        omit_selected_clicks,
        restore_clicks,
        selected_item,
        reason,
        active_cell,
        trade_board_visible_rows,
        trade_board_rows,
        selected_rows,
        omitted_rows,
        version,
    ):
        triggered_id = ctx.triggered_id
        status = ""
        changed = False

        try:
            if triggered_id == "omit-item-button":
                result = omit_item(selected_item, reason=reason)
                status = f"Omitted {result.get('item_name')}."
                changed = True

            elif triggered_id == "omit-selected-trade-board-item-button":
                if not active_cell or active_cell.get("row") is None:
                    status = "Click a recommendation row first, then press Omit Selected."
                else:
                    rows = trade_board_visible_rows or trade_board_rows or []
                    row_index = int(active_cell.get("row"))
                    if row_index < 0 or row_index >= len(rows):
                        status = "The selected recommendation row is no longer available."
                    else:
                        row = rows[row_index] or {}
                        item_name = row.get("Item") or row.get("item_name")
                        item_id = row.get("Item ID") or row.get("item_id")
                        result = omit_item(item_name, item_id=item_id, reason=reason or "Omitted from Trade Board")
                        status = f"Omitted {result.get('item_name')}."
                        changed = True

            elif triggered_id == "restore-omitted-item-button":
                selected_rows = selected_rows or []
                rows = omitted_rows or []
                if not selected_rows:
                    status = "Select an omitted item row to restore."
                else:
                    row_index = int(selected_rows[0])
                    if row_index < 0 or row_index >= len(rows):
                        status = "The selected omitted row is no longer available."
                    else:
                        restored = restore_omitted_item(row_id=rows[row_index].get("ID"))
                        item_name = rows[row_index].get("Item") or "item"
                        status = f"Restored {item_name}." if restored else "No omitted item was restored."
                        changed = restored > 0

            if changed:
                clear_all_dashboard_caches()
                version = int(version or 0) + 1

        except Exception as error:
            status = f"Omitted item update failed: {type(error).__name__}: {error}"

        rows = get_omitted_item_rows()
        columns = [
            {"name": "ID", "id": "ID"},
            {"name": "Item", "id": "Item"},
            {"name": "Item ID", "id": "Item ID"},
            {"name": "Reason", "id": "Reason"},
            {"name": "Created", "id": "Created"},
        ]

        if not status:
            status = f"{len(rows)} omitted item(s)." if rows else "No omitted items."

        return rows, columns, status, int(version or 0), get_item_options()







    @app.callback(
        Output("database-compaction-status", "children"),
        Output("database-compaction-preview-table", "data"),
        Output("database-compaction-preview-table", "columns"),
        Output("maintenance-history-status", "children"),
        Output("maintenance-history-table", "data"),
        Output("maintenance-history-table", "columns"),
        Input("preview-database-compaction-button", "n_clicks"),
        Input("create-compacted-database-copy-button", "n_clicks"),
        Input("refresh-maintenance-history-button", "n_clicks"),
        State("database-compaction-confirmation", "value"),
    )
    def update_database_compaction_and_history(preview_clicks, compact_clicks, history_clicks, confirmation_text):
        try:
            from dash import ctx as dash_ctx

            triggered_id = dash_ctx.triggered_id or "initial-load"
            compaction_rows = []
            compaction_status = "Click Preview Compact Database to estimate reclaimable SQLite space."

            if triggered_id == "preview-database-compaction-button":
                compaction = build_database_compaction_preview_snapshot(record_event=True)
                compaction_rows = compaction.get("rows", [])
                compaction_status = compaction.get("status", compaction_status)
            elif triggered_id == "create-compacted-database-copy-button":
                compaction = create_compacted_database_copy(
                    confirmation_text=confirmation_text,
                    backup_max_age_hours=24,
                )
                compaction_rows = compaction.get("rows", [])
                compaction_status = compaction.get("status", "Compacted copy action complete.")

            history = build_maintenance_events_snapshot(limit=25)
            history_rows = history.get("rows", [])
            history_status = history.get("status", "Maintenance history loaded.")

            if not history_rows:
                history_rows = [
                    {
                        "ID": "",
                        "Event Type": "",
                        "Status": "no events yet",
                        "Detail": "Run a backup, preview, cleanup, or compaction preview to create history.",
                        "Rows Affected": "",
                        "DB Before MB": "",
                        "DB After MB": "",
                        "Backup": "",
                        "Created UTC": "",
                    }
                ]

            return (
                compaction_status,
                compaction_rows,
                _columns_for_records(compaction_rows),
                history_status,
                history_rows,
                _columns_for_records(history_rows),
            )
        except Exception as exc:
            compaction_rows = [
                {
                    "Metric": "Database compaction",
                    "Value": "error",
                    "Notes": f"{type(exc).__name__}: {str(exc)[:180]}",
                }
            ]
            history_rows = [
                {
                    "ID": "",
                    "Event Type": "error",
                    "Status": type(exc).__name__,
                    "Detail": str(exc)[:180],
                    "Rows Affected": "",
                    "DB Before MB": "",
                    "DB After MB": "",
                    "Backup": "",
                    "Created UTC": "",
                }
            ]
            return (
                f"Database compaction failed: {type(exc).__name__}: {exc}",
                compaction_rows,
                _columns_for_records(compaction_rows),
                "Maintenance history failed to load.",
                history_rows,
                _columns_for_records(history_rows),
            )

    @app.callback(
        Output("database-backup-status", "children"),
        Output("database-backup-table", "data"),
        Output("database-backup-table", "columns"),
        Input("create-database-safety-backup-button", "n_clicks"),
        Input("refresh-database-backup-list-button", "n_clicks"),
    )
    def update_database_backup(create_clicks, refresh_clicks):
        try:
            from dash import ctx as dash_ctx

            triggered_id = dash_ctx.triggered_id or "initial-load"
            action_status = ""

            if triggered_id == "create-database-safety-backup-button":
                result = create_database_safety_backup()
                action_status = result.get("status", "Database safety backup completed.")

            snapshot = build_database_backup_snapshot(limit=10)
            rows = snapshot.get("rows", [])
            status = action_status or snapshot.get("status", "Database backup list loaded.")

            if not rows:
                rows = [
                    {
                        "Backup File": "",
                        "Size": "",
                        "Modified UTC": "",
                        "Metadata": "",
                        "Folder": snapshot.get("backup_folder", ""),
                        "Status": "no backups yet",
                    }
                ]

            return (
                status,
                rows,
                _columns_for_records(rows),
            )
        except Exception as exc:
            rows = [
                {
                    "Backup File": "error",
                    "Size": "",
                    "Modified UTC": "",
                    "Metadata": "",
                    "Folder": "",
                    "Status": f"{type(exc).__name__}: {str(exc)[:160]}",
                }
            ]
            return (
                f"Database backup failed: {type(exc).__name__}: {exc}",
                rows,
                _columns_for_records(rows),
            )


    @app.callback(
        Output("data-retention-preview-status", "children"),
        Output("data-retention-preview-table", "data"),
        Output("data-retention-preview-table", "columns"),
        Input("preview-retention-cleanup-button", "n_clicks"),
        Input("run-retention-cleanup-button", "n_clicks"),
        State("raw-scan-retention-days", "value"),
        State("retention-cleanup-confirmation", "value"),
    )
    def update_retention_preview(preview_clicks, cleanup_clicks, retention_days, confirmation_text):
        try:
            from dash import ctx as dash_ctx

            triggered_id = dash_ctx.triggered_id or "initial-load"

            if triggered_id == "run-retention-cleanup-button":
                result = cleanup_scan_results_with_backup_guard(
                    retention_days=retention_days,
                    confirmation_text=confirmation_text,
                    backup_max_age_hours=24,
                )
                rows = result.get("rows", [])
                return (
                    result.get("status", "Cleanup check completed."),
                    rows,
                    _columns_for_records(rows),
                )

            snapshot = build_retention_preview_snapshot(retention_days=retention_days)
            rows = snapshot.get("rows", [])

            return (
                snapshot.get("status", "Retention preview loaded."),
                rows,
                _columns_for_records(rows),
            )
        except Exception as exc:
            rows = [
                {
                    "Metric": "Retention cleanup",
                    "Value": "error",
                    "Notes": f"{type(exc).__name__}: {str(exc)[:180]}",
                }
            ]
            return (
                f"Retention cleanup/preview failed: {type(exc).__name__}: {exc}",
                rows,
                _columns_for_records(rows),
            )

    @app.callback(
        Output("item-trend-status", "children"),
        Output("item-trend-summary-cards", "children"),
        Output("item-trend-margin-graph", "figure"),
        Output("item-trend-score-graph", "figure"),
        Output("item-trend-matches-table", "data"),
        Output("item-trend-matches-table", "columns"),
        Output("item-trend-history-table", "data"),
        Output("item-trend-history-table", "columns"),
        Input("load-item-trend-button", "n_clicks"),
        State("item-trend-search-input", "value"),
        State("item-trend-days-input", "value"),
    )
    def update_item_trend_explorer(n_clicks, item_query, days):
        def empty_figure(title):
            return {
                "data": [],
                "layout": {
                    "title": title,
                    "template": "plotly_dark",
                    "paper_bgcolor": "rgba(0,0,0,0)",
                    "plot_bgcolor": "rgba(0,0,0,0)",
                    "font": {"color": "#e5e7eb"},
                    "margin": {"l": 40, "r": 20, "t": 50, "b": 40},
                },
            }

        try:
            snapshot = build_item_trend_explorer_snapshot(item_query=item_query, days=days or 90)
            rows = snapshot.get("rows", [])
            matches = snapshot.get("matches", [])

            cards = [
                make_card(card.get("Title", ""), card.get("Value", ""), card.get("Detail", ""))
                for card in snapshot.get("summary_cards", [])
            ]

            if not rows:
                return (
                    snapshot.get("status", "No trend rows found."),
                    cards,
                    empty_figure("Margin Trend"),
                    empty_figure("Score Trend"),
                    matches,
                    _columns_for_records(matches),
                    rows,
                    _columns_for_records(rows),
                )

            dates = [row.get("Metric Date") for row in rows]

            margin_figure = {
                "data": [
                    {
                        "x": dates,
                        "y": [row.get("Avg Margin") for row in rows],
                        "type": "scatter",
                        "mode": "lines+markers",
                        "name": "Avg Margin",
                    },
                    {
                        "x": dates,
                        "y": [row.get("Avg Profit / Item") for row in rows],
                        "type": "scatter",
                        "mode": "lines+markers",
                        "name": "Avg Profit / Item",
                    },
                    {
                        "x": dates,
                        "y": [row.get("Margin Volatility") for row in rows],
                        "type": "scatter",
                        "mode": "lines+markers",
                        "name": "Margin Volatility",
                    },
                ],
                "layout": {
                    "title": f"Margin Trend — {snapshot.get('matched_item', '')}",
                    "template": "plotly_dark",
                    "paper_bgcolor": "rgba(0,0,0,0)",
                    "plot_bgcolor": "rgba(0,0,0,0)",
                    "font": {"color": "#e5e7eb"},
                    "xaxis": {"title": "Metric Date"},
                    "yaxis": {"title": "GP / Volatility"},
                    "hovermode": "x unified",
                    "margin": {"l": 50, "r": 20, "t": 50, "b": 40},
                },
            }

            score_figure = {
                "data": [
                    {
                        "x": dates,
                        "y": [row.get("Recommendation Score") for row in rows],
                        "type": "scatter",
                        "mode": "lines+markers",
                        "name": "Recommendation Score",
                    },
                    {
                        "x": dates,
                        "y": [row.get("Quick Score") for row in rows],
                        "type": "scatter",
                        "mode": "lines+markers",
                        "name": "Quick Score",
                    },
                    {
                        "x": dates,
                        "y": [row.get("Overnight Score") for row in rows],
                        "type": "scatter",
                        "mode": "lines+markers",
                        "name": "Overnight Score",
                    },
                ],
                "layout": {
                    "title": f"Score Trend — {snapshot.get('matched_item', '')}",
                    "template": "plotly_dark",
                    "paper_bgcolor": "rgba(0,0,0,0)",
                    "plot_bgcolor": "rgba(0,0,0,0)",
                    "font": {"color": "#e5e7eb"},
                    "xaxis": {"title": "Metric Date"},
                    "yaxis": {"title": "Score"},
                    "hovermode": "x unified",
                    "margin": {"l": 50, "r": 20, "t": 50, "b": 40},
                },
            }

            return (
                snapshot.get("status", "Loaded item trend."),
                cards,
                margin_figure,
                score_figure,
                matches,
                _columns_for_records(matches),
                rows,
                _columns_for_records(rows),
            )
        except Exception as exc:
            error_rows = [
                {
                    "Error": type(exc).__name__,
                    "Details": str(exc)[:200],
                }
            ]
            return (
                f"Item Trend Explorer failed: {type(exc).__name__}: {exc}",
                [make_card("Item Trend", "Error", str(exc)[:90])],
                empty_figure("Margin Trend"),
                empty_figure("Score Trend"),
                error_rows,
                _columns_for_records(error_rows),
                [],
                [],
                [],
                [],
            )

    @app.callback(
        Output("data-health-trend-readiness-table", "data"),
        Output("data-health-trend-readiness-table", "columns"),
        Output("data-health-trend-items-table", "data"),
        Output("data-health-trend-items-table", "columns"),
        Input("refresh-data-health-button", "n_clicks"),
        Input("apply-data-health-schema-button", "n_clicks"),
        Input("rebuild-daily-metrics-button", "n_clicks"),
    )
    def update_data_trend_readiness(refresh_clicks, schema_clicks, rebuild_clicks):
        try:
            snapshot = build_data_trend_snapshot(limit=25)

            readiness = snapshot.get("readiness", [])
            top_trends = snapshot.get("top_trends", [])

            return (
                readiness,
                _columns_for_records(readiness),
                top_trends,
                _columns_for_records(top_trends),
            )
        except Exception as exc:
            readiness = [
                {
                    "Signal": "Trend readiness",
                    "Available": "error",
                    "Target": "load snapshot",
                    "Status": type(exc).__name__,
                    "Notes": str(exc)[:120],
                }
            ]
            return (
                readiness,
                _columns_for_records(readiness),
                [],
                [],
            )

    @app.callback(
        Output("data-health-status", "children"),
        Output("data-health-cards", "children"),
        Output("data-health-tables-table", "data"),
        Output("data-health-tables-table", "columns"),
        Output("data-health-time-table", "data"),
        Output("data-health-time-table", "columns"),
        Output("data-health-index-table", "data"),
        Output("data-health-index-table", "columns"),
        Output("data-health-metrics-table", "data"),
        Output("data-health-metrics-table", "columns"),
        Output("data-health-automation-table", "data"),
        Output("data-health-automation-table", "columns"),
        Input("refresh-data-health-button", "n_clicks"),
        Input("apply-data-health-schema-button", "n_clicks"),
        Input("rebuild-daily-metrics-button", "n_clicks"),
        Input("refresh-stale-daily-metrics-button", "n_clicks"),
        State("daily-metrics-days", "value"),
        running=[
            (Output("apply-data-health-schema-button", "disabled"), True, False),
            (Output("rebuild-daily-metrics-button", "disabled"), True, False),
            (Output("refresh-stale-daily-metrics-button", "disabled"), True, False),
        ],
    )
    def update_data_health(refresh_clicks, schema_clicks, rebuild_clicks, stale_refresh_clicks, rebuild_days):
        try:
            from dash import ctx as dash_ctx

            triggered_id = dash_ctx.triggered_id or "initial-load"
            action_status = ""

            if triggered_id == "apply-data-health-schema-button":
                result = ensure_data_health_schema()
                action_status = result.get("status", "Schema/index check complete.")
            elif triggered_id == "rebuild-daily-metrics-button":
                result = rebuild_daily_item_metrics(days=rebuild_days or 30)
                action_status = result.get("status", "Daily metrics rebuild complete.")
            elif triggered_id == "refresh-stale-daily-metrics-button":
                result = refresh_daily_metrics_if_stale(max_age_hours=12, rebuild_days=14, force=False)
                action_status = result.get("status", "Stale metrics refresh complete.")

            snapshot = build_data_health_snapshot()

            cards = [
                make_card(card.get("Title", ""), card.get("Value", ""), card.get("Detail", ""))
                for card in snapshot.get("cards", [])
            ]

            status = snapshot.get("status", "Data Health loaded.")

            if action_status:
                status = f"{action_status} {status}"

            if triggered_id and triggered_id != "initial-load":
                status = f"{status} Trigger: {triggered_id}."

            tables = snapshot.get("tables", [])
            time_rows = snapshot.get("time_coverage", [])
            index_rows = snapshot.get("index_status", [])
            metric_rows = snapshot.get("daily_metrics", [])
            automation_rows = build_metrics_automation_snapshot(max_age_hours=12).get("checks", [])

            return (
                status,
                cards,
                tables,
                _columns_for_records(tables),
                time_rows,
                _columns_for_records(time_rows),
                index_rows,
                _columns_for_records(index_rows),
                metric_rows,
                _columns_for_records(metric_rows),
                automation_rows,
                _columns_for_records(automation_rows),
            )
        except Exception as exc:
            cards = [
                make_card("Data Health", "Error", "send the status line"),
                make_card("Exception", type(exc).__name__, str(exc)[:90]),
            ]
            return (
                f"Data Health failed: {type(exc).__name__}: {exc}",
                cards,
                [],
                [],
                [],
                [],
                [],
                [],
                [],
                [],
            )

    @app.callback(
        Output("slot-actions-status", "children"),
        Output("slot-actions-kpi-cards", "children"),
        Output("slot-actions-table", "data"),
        Output("slot-actions-table", "columns"),
        Input("refresh-slot-actions-button", "n_clicks"),
        Input("auto-refresh", "n_intervals"),
        Input("dashboard-refresh-status-button", "n_clicks"),
    )
    def update_open_slot_actions(n_clicks, intervals, dashboard_refresh_clicks):
        try:
            from datetime import datetime

            triggered_id = ctx.triggered_id or "initial-load"
            actions_df, summary = get_open_slot_actions(limit=12)
            refreshed_at = datetime.now().strftime("%H:%M:%S")

            cards = [
                make_card(
                    "Active Slots",
                    f"{summary.get('active_slots', 0)}/{summary.get('ge_slot_count', 8)}",
                    f"{summary.get('free_slots', 0)} free slots"
                ),
                make_card(
                    "Slot Pressure",
                    "High" if summary.get("slot_pressure") else "Normal",
                    "based on live RuneLite slots"
                ),
                make_card(
                    "High Priority",
                    str(summary.get("high_count", 0)),
                    "review these first"
                ),
                make_card(
                    "Medium Priority",
                    str(summary.get("medium_count", 0)),
                    "aging or slot-pressure candidates"
                ),
                make_card(
                    "Controlled Loss",
                    str(summary.get("controlled_loss_count", 0)),
                    "review only; never automatic"
                ),
            ]

            status = (
                f"{summary.get('status', 'Open Slot Actions updated.')} "
                f"Last update {refreshed_at}. Trigger={triggered_id}. "
                f"Refresh clicks={n_clicks or 0}; interval ticks={intervals or 0}."
            )

            if actions_df.empty:
                return status, cards, [], []

            columns = [{"name": column, "id": column} for column in actions_df.columns]
            return status, cards, actions_df.to_dict("records"), columns

        except Exception as error:
            cards = [
                make_card("Open Slot Actions", "Error", "send the status line"),
                make_card("Phase", "1", "manual refresh only"),
            ]
            return (
                f"Open Slot Actions failed: {type(error).__name__}: {error}",
                cards,
                [],
                [],
            )






    @app.callback(
        Output("trade-board-status", "children"),
        Output("trade-board-kpi-cards", "children"),
        Output("trade-board-table", "data"),
        Output("trade-board-table", "columns"),
        Input("refresh-trade-board-button", "n_clicks"),
        Input("trade-board-risk-profile", "value"),
        Input("trade-board-limit", "value"),
        Input("trade-board-min-profit", "value"),
        Input("trade-board-action-filter", "value"),
        Input("trade-board-confidence-filter", "value"),
        Input("trade-board-fill-filter", "value"),
        Input("trade-board-trend-direction-filter", "value"),
        Input("trade-board-trend-confidence-filter", "value"),
        Input("trade-board-trend-boost-mode", "value"),
        Input("dashboard-refresh-status-button", "n_clicks"),
        Input("omit-items-version", "data"),
    )
    def update_trade_board_phase1(
        n_clicks,
        risk_profile,
        limit,
        minimum_profit,
        action_filter,
        confidence_filter,
        fill_filter,
        trend_direction_filter,
        trend_confidence_filter,
        trend_boost_mode,
        dashboard_refresh_clicks,
        omitted_items_version,
    ):
        try:
            from datetime import datetime
            from dash import ctx as dash_ctx

            triggered_id = dash_ctx.triggered_id or "initial-load"
            refreshed_at = datetime.now().strftime("%H:%M:%S")

            try:
                visible_limit = int(limit or 25)
            except Exception:
                visible_limit = 25

            visible_limit = max(5, min(visible_limit, 100))

            board_df, summary = get_trade_board_recommendations(
                limit=visible_limit,
                risk_profile=risk_profile,
                minimum_profit=minimum_profit,
                action_filter=action_filter,
                confidence_filter=confidence_filter,
                fill_filter=fill_filter,
            )

            board_df, trade_trend_status = _enrich_trade_board_dataframe_with_trends(board_df)
            trade_trend_health = summarize_trade_board_trend_health()
            if isinstance(summary, dict):
                summary["trend_status"] = trade_trend_status
                summary["trend_history_days"] = trade_trend_health.get("metric_days", 0)
                summary["trend_items_with_history"] = trade_trend_health.get("items_with_history", 0)


            try:
                trend_boost_mode_value = str(trend_boost_mode or "off").lower()

                if hasattr(board_df, "to_dict"):
                    boost_records = board_df.to_dict("records")
                    boosted_records = apply_trade_board_trend_boost(
                        boost_records,
                        mode=trend_boost_mode_value,
                    )

                    if trend_boost_mode_value in {"annotate", "reorder"}:
                        board_df = board_df.__class__(boosted_records)

                if isinstance(summary, dict):
                    summary["trend_boost_mode"] = trend_boost_mode_value
                    summary["trend_boost_status"] = (
                        "off"
                        if trend_boost_mode_value == "off"
                        else f"{trend_boost_mode_value} applied to displayed rows"
                    )
            except Exception as trend_boost_exc:
                if isinstance(summary, dict):
                    summary["trend_boost_mode"] = trend_boost_mode or "off"
                    summary["trend_boost_status"] = f"trend boost skipped: {type(trend_boost_exc).__name__}"

            trend_filter_notes = []

            try:
                if hasattr(board_df, "columns"):
                    if (
                        trend_direction_filter
                        and trend_direction_filter != "all"
                        and "Trend Direction" in board_df.columns
                    ):
                        board_df = board_df[
                            board_df["Trend Direction"]
                            .fillna("")
                            .astype(str)
                            .str.lower()
                            == str(trend_direction_filter).lower()
                        ]
                        trend_filter_notes.append(f"direction={trend_direction_filter}")

                    if (
                        trend_confidence_filter
                        and trend_confidence_filter != "all"
                        and "Trend Confidence" in board_df.columns
                    ):
                        board_df = board_df[
                            board_df["Trend Confidence"]
                            .fillna("")
                            .astype(str)
                            .str.lower()
                            == str(trend_confidence_filter).lower()
                        ]
                        trend_filter_notes.append(f"confidence={trend_confidence_filter}")

                    if isinstance(summary, dict):
                        summary["trend_direction_filter"] = trend_direction_filter or "all"
                        summary["trend_confidence_filter"] = trend_confidence_filter or "all"
                        summary["trend_filtered_rows"] = int(len(board_df))
                        summary["trend_filter_status"] = ", ".join(trend_filter_notes) if trend_filter_notes else "no trend filters"
            except Exception as trend_filter_exc:
                if isinstance(summary, dict):
                    summary["trend_filter_status"] = f"trend filters skipped: {type(trend_filter_exc).__name__}"


            visible_count = len(board_df)
            filtered_count = int(summary.get("filtered_count", visible_count))
            source_count = int(summary.get("filter_source_count", filtered_count))

            cards = []

            latest_run = summary.get("latest_run_id", "n/a")
            status_parts = [
                f"Updated {refreshed_at}",
                f"scan {latest_run}",
                f"showing {visible_count}/{filtered_count}",
                f"risk {risk_profile or 'medium'}",
                f"min {format_gp(summary.get('minimum_profit', 0))} gp",
            ]

            if trend_filter_notes:
                status_parts.append("trend " + ", ".join(trend_filter_notes))

            trend_boost_mode_label = str(summary.get("trend_boost_mode", "off"))
            if trend_boost_mode_label != "off":
                status_parts.append(f"boost {trend_boost_mode_label}")

            status = " | ".join(status_parts)

            if board_df.empty:
                return (
                    status,
                    cards,
                    [],
                    [],
                )

            columns = [{"name": column, "id": column} for column in board_df.columns]
            return (
                status,
                cards,
                board_df.to_dict("records"),
                columns,
            )
        except Exception as exc:
            cards = []
            return (
                f"Trade Board failed: {type(exc).__name__}: {exc}",
                cards,
                [],
                [],
            )

    @app.callback(
        Output("kpi-cards", "children"),
        Output("top-profit-chart", "figure"),
        Output("quick-overnight-chart", "figure"),
        Output("trend-position-chart", "figure"),
        Output("roi-volume-chart", "figure"),
        Output("latest-table", "data"),
        Output("latest-table", "columns"),
        Output("recurring-table", "data"),
        Output("recurring-table", "columns"),
        Input("window-filter", "value"),
        Input("result-type-filter", "value"),
        Input("signal-filter", "value"),
        Input("category-filter", "value"),
        Input("trend-filter", "value"),
        Input("limit-filter", "value"),
        Input("auto-refresh", "n_intervals"),
        Input("dashboard-refresh-status-button", "n_clicks"),
        Input("omit-items-version", "data"),
    )
    def update_dashboard(
        window_filter,
        result_type_filter,
        signal_filter,
        category_filter,
        trend_filter,
        limit,
        _,
        dashboard_refresh_clicks,
        omitted_items_version,
    ):
        df = get_filtered_latest(
            window_filter=window_filter,
            result_type_filter=result_type_filter,
            signal_filter=signal_filter,
            category_filter=category_filter,
            trend_filter=trend_filter,
            limit=limit
        )

        if df.empty:
            cards = [
                make_card("Best Profit", "0 gp", "run main.py or collector.py first"),
                make_card("Avg ROI", "N/A", "post-tax"),
                make_card("Best Net/Item", "0 gp", "post-tax"),
                make_card("Best Quick Score", "0", "active flips"),
                make_card("Overnight Qualified", "0", f"{OVERNIGHT_RAW_MARGIN_MIN:,}+ raw margin and {OVERNIGHT_ROI_MIN}%+ ROI"),
                make_card("Trend Warnings", "0", "current filters")
            ]

            recurring_df = get_best_recurring_flips(limit=limit)
            recurring_data = recurring_df.to_dict("records")
            recurring_columns = [{"name": column, "id": column} for column in recurring_df.columns]

            return (
                cards,
                empty_figure("Top Profit Opportunities"),
                empty_figure("Quick Score vs Overnight Score"),
                empty_figure("7-Day Price Position"),
                empty_figure("ROI vs Volume"),
                [],
                [],
                recurring_data,
                recurring_columns
            )

        best_profit = df["total_profit"].max() if "total_profit" in df.columns else 0
        avg_roi = df["roi_percent"].mean() if "roi_percent" in df.columns else 0
        best_net_item = df["profit_per_item"].max() if "profit_per_item" in df.columns else 0
        best_quick_score = df["quick_score"].max() if "quick_score" in df.columns else 0
        best_overnight_score = df["overnight_score"].max() if "overnight_score" in df.columns else 0

        overnight_qualified_count = 0

        if "overnight_qualified" in df.columns:
            overnight_qualified_count = int(df["overnight_qualified"].sum())

        trend_warning_count = 0

        if "trend_warning" in df.columns:
            trend_warning_count = len(df[df["trend_warning"].fillna("OK") != "OK"])

        cards = [
            make_card("Best Profit", f"{format_gp(best_profit)} gp", "best total profit in view"),
            make_card("Avg ROI", format_percent(avg_roi), "post-tax average"),
            make_card("Best Net/Item", f"{format_gp(best_net_item)} gp", "post-tax per item"),
            make_card("Best Quick Score", round(float(best_quick_score), 2), "active flipping strength"),
            make_card("Overnight Qualified", str(overnight_qualified_count), f"{OVERNIGHT_RAW_MARGIN_MIN:,}+ raw margin and {OVERNIGHT_ROI_MIN}%+ ROI"),
            make_card("Trend Warnings", str(trend_warning_count), f"best overnight score {round(float(best_overnight_score), 2)}")
        ]

        df = add_chart_size(df)
        chart_df = df.head(15).copy()

        top_profit_fig = px.bar(
            chart_df,
            x="item_name",
            y="total_profit",
            color="flip_category" if "flip_category" in chart_df.columns else None,
            hover_data=[
                column for column in [
                    "window_name",
                    "flip_category",
                    "price_source",
                    "target_buy",
                    "target_sell",
                    "quantity",
                    "roi_percent",
                    "quick_score",
                    "overnight_score",
                    "weekly_trend",
                    "trend_warning"
                ]
                if column in chart_df.columns
            ],
            title="Top Profit Opportunities"
        )
        top_profit_fig.update_layout(xaxis_tickangle=-45)
        apply_dark_chart_layout(
            top_profit_fig,
            x_title="Item",
            y_title="Total Profit",
            bottom_margin=130
        )

        if "quick_score" in df.columns and "overnight_score" in df.columns:
            quick_overnight_fig = px.scatter(
                df,
                x="quick_score",
                y="overnight_score",
                size="chart_size" if "chart_size" in df.columns else None,
                color="flip_category" if "flip_category" in df.columns else None,
                hover_name="item_name",
                hover_data=[
                    column for column in [
                        "window_name",
                        "expected_fill_time",
                        "liquidity_rating",
                        "weekly_trend",
                        "trend_warning",
                        "total_profit",
                        "roi_percent"
                    ]
                    if column in df.columns
                ],
                title="Quick Score vs Overnight Score"
            )
            apply_dark_chart_layout(
                quick_overnight_fig,
                x_title="Quick Score",
                y_title="Overnight Score"
            )
        else:
            quick_overnight_fig = empty_figure("Quick Score vs Overnight Score")

        if "price_position_7d_percent" in df.columns:
            trend_position_fig = px.scatter(
                df,
                x="price_position_7d_percent",
                y="weekly_change_percent" if "weekly_change_percent" in df.columns else "roi_percent",
                size="chart_size" if "chart_size" in df.columns else None,
                color="weekly_trend" if "weekly_trend" in df.columns else None,
                hover_name="item_name",
                hover_data=[
                    column for column in [
                        "window_name",
                        "flip_category",
                        "seven_day_low",
                        "seven_day_high",
                        "trend_confidence",
                        "trend_warning",
                        "overnight_score"
                    ]
                    if column in df.columns
                ],
                title="7-Day Price Position vs Weekly Change"
            )
            apply_dark_chart_layout(
                trend_position_fig,
                x_title="Price Position in 7-Day Range %",
                y_title="Weekly Change %"
            )
        else:
            trend_position_fig = empty_figure("7-Day Price Position")

        roi_volume_fig = px.scatter(
            df,
            x="roi_percent",
            y="volume",
            size="chart_size" if "chart_size" in df.columns else None,
            color="flip_category" if "flip_category" in df.columns else None,
            hover_name="item_name",
            hover_data=[
                column for column in [
                    "window_name",
                    "price_source",
                    "target_buy",
                    "target_sell",
                    "quantity",
                    "total_profit",
                    "signal",
                    "confidence",
                    "liquidity_score",
                    "expected_fill_time"
                ]
                if column in df.columns
            ],
            title="ROI vs Volume"
        )
        apply_dark_chart_layout(
            roi_volume_fig,
            x_title="ROI %",
            y_title="Window Volume"
        )

        display_df = build_latest_display_df(df)

        recurring_df = get_best_recurring_flips(limit=limit)

        latest_data = display_df.to_dict("records")
        latest_columns = [{"name": column, "id": column} for column in display_df.columns]

        recurring_data = recurring_df.to_dict("records")
        recurring_columns = [{"name": column, "id": column} for column in recurring_df.columns]

        return (
            cards,
            top_profit_fig,
            quick_overnight_fig,
            trend_position_fig,
            roi_volume_fig,
            latest_data,
            latest_columns,
            recurring_data,
            recurring_columns
        )






    @app.callback(
        Output("item-history-chart", "figure"),
        Input("market-item-dropdown", "value"),
        Input("auto-refresh", "n_intervals"),
        Input("main-tabs", "value"),
    )
    def update_item_history(selected_item, _, active_tab):
        if active_tab != "market-data":
            return no_update

        if not selected_item:
            return empty_figure("Select an item to view margin history")

        item_df = get_item_history_for_item(selected_item)

        if item_df.empty:
            return empty_figure(f"No history for {selected_item}")

        if "raw_margin" not in item_df.columns:
            return empty_figure(f"No raw margin data for {selected_item}")

        fig = px.line(
            item_df,
            x="scanned_at",
            y="raw_margin",
            color="window_name" if "window_name" in item_df.columns else None,
            hover_data=[
                column for column in [
                    "price_source",
                    "target_buy",
                    "target_sell",
                    "profit_per_item",
                    "total_profit",
                    "roi_percent",
                    "volume",
                    "signal",
                    "flip_category",
                    "quick_score",
                    "overnight_score",
                    "daily_trend",
                    "weekly_trend",
                    "trend_warning"
                ]
                if column in item_df.columns
            ],
            title=f"Margin History: {selected_item}"
        )

        apply_dark_chart_layout(
            fig,
            x_title="Scan Time",
            y_title="Raw Margin"
        )

        return fig




    @app.callback(
        Output("trade-import-status", "children"),
        Output("trade-kpi-cards", "children"),
        Output("trade-profit-chart", "figure"),
        Output("trade-item-profit-chart", "figure"),
        Output("live-ge-offers-table", "data"),
        Output("live-ge-offers-table", "columns"),
        Output("completed-trades-table", "data"),
        Output("completed-trades-table", "columns"),
        Output("open-trades-table", "data"),
        Output("open-trades-table", "columns"),
        Input("refresh-trades-button", "n_clicks"),
        Input("auto-refresh", "n_intervals"),
        Input("dashboard-refresh-status-button", "n_clicks"),
        Input("omit-items-version", "data"),
        Input("main-tabs", "value"),
        State("my-trades-limit", "value")
    )
    def update_trade_dashboard(refresh_clicks, intervals, dashboard_refresh_clicks, omitted_items_version, active_tab, row_limit):
        if active_tab not in {"my-trades", "trade-board", "trading"}:
            return (
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update
            )

        triggered_id = ctx.triggered_id

        if triggered_id in {"refresh-trades-button", "auto-refresh", "dashboard-refresh-status-button"}:
            import_status = refresh_runelite_trades_for_dashboard()

            try:
                clear_trade_dashboard_cache()
            except Exception:
                pass

            try:
                clear_dashboard_cache()
            except Exception:
                pass

            if triggered_id == "auto-refresh":
                import_status = f"Auto refreshed live RuneLite telemetry. {import_status}"
            elif triggered_id == "dashboard-refresh-status-button":
                import_status = f"Refreshed from dashboard command. {import_status}"
        else:
            import_status = "Loaded saved trade data and live GE offers from OSRSFlipper RuneLite telemetry."

        limit = parse_positive_int(row_limit, default=100, minimum=10, maximum=500)

        summary = get_trade_summary()

        cards = [
            make_card("Realized P/L", f"{format_gp(summary.get('realized_profit', 0))} gp", "matched completed flips"),
            make_card("Completed Flips", str(int(summary.get("completed_count", 0))), "buy/sell pairs matched"),
            make_card("Average ROI", format_percent(summary.get("avg_roi", 0)), "completed flips"),
            make_card("Best Trade", f"{format_gp(summary.get('best_trade', 0))} gp", "single matched flip"),
            make_card("Worst Trade", f"{format_gp(summary.get('worst_trade', 0))} gp", "single matched flip"),
            make_card("Open Buy Value", f"{format_gp(summary.get('open_buy_value', 0))} gp", f"{int(summary.get('open_event_count', 0))} open events")
        ]

        history_df = get_completed_trade_history()

        if history_df.empty:
            profit_fig = empty_figure("Cumulative Realized Profit")
            item_fig = empty_figure("Profit by Item")
        else:
            profit_fig = px.line(
                history_df,
                x="sell_time",
                y="cumulative_profit",
                hover_data=["item_name", "total_profit", "roi_percent"],
                title="Cumulative Realized Profit"
            )
            apply_dark_chart_layout(
                profit_fig,
                x_title="Sell Time",
                y_title="Cumulative Profit"
            )

            item_df = history_df.groupby("item_name", as_index=False)["total_profit"].sum()
            item_df = item_df.sort_values("total_profit", ascending=False).head(15)

            item_fig = px.bar(
                item_df,
                x="item_name",
                y="total_profit",
                title="Profit by Item"
            )
            item_fig.update_layout(xaxis_tickangle=-45)
            apply_dark_chart_layout(
                item_fig,
                x_title="Item",
                y_title="Total Profit",
                bottom_margin=130
            )

        completed_df = clean_trade_display_df(get_transaction_history_rows(limit=limit))
        live_offers_df = clean_trade_display_df(get_live_ge_offer_rows(limit=limit))
        open_df = clean_trade_display_df(get_open_trade_rows(limit=limit))

        live_offers_data = live_offers_df.to_dict("records")
        live_offers_columns = trade_table_columns(live_offers_df)

        completed_data = completed_df.to_dict("records")
        completed_columns = trade_table_columns(completed_df)

        open_data = open_df.to_dict("records")
        open_columns = trade_table_columns(open_df)

        return (
            import_status,
            cards,
            profit_fig,
            item_fig,
            live_offers_data,
            live_offers_columns,
            completed_data,
            completed_columns,
            open_data,
            open_columns
        )

    @app.callback(
        Output("ai-advice-output", "children"),
        Output("ai-status", "children"),
        Input("generate-ai-button", "n_clicks"),
        State("ai-risk-profile", "value"),
        State("ai-limit", "value"),
        prevent_initial_call=True
    )
    def update_ai_advice(n_clicks, risk_profile, limit):
        if not n_clicks:
            return read_saved_ai_advice(), ""

        try:
            advice = generate_ai_advice(
                risk_profile=risk_profile,
                limit=limit
            )
            usage_summary = get_ai_usage_summary()
            latest_usage = usage_summary.get("latest") or {}
            latest_tokens = int(latest_usage.get("total_tokens") or 0)
            latest_cost = latest_usage.get("estimated_cost")
            if latest_cost is None:
                cost_text = "cost estimate off"
            else:
                cost_text = f"estimated cost ${float(latest_cost):.4f}"

            status = (
                "AI advice generated successfully. "
                f"Risk profile: {risk_profile}. "
                f"Candidate source limit: {limit}. "
                f"Last prompt: {latest_tokens:,} tokens, {cost_text}."
            )

            return advice, status

        except Exception as error:
            return (
                read_saved_ai_advice(),
                f"AI advice failed: {error}"
            )



    @app.callback(
        Output("trade-account-scope", "children"),
        Input("auto-refresh", "n_intervals"),
        Input("dashboard-refresh-status-button", "n_clicks"),
        Input("main-tabs", "value"),
    )
    def update_trade_account_scope(_, dashboard_refresh_clicks, active_tab):
        if active_tab not in {"my-trades", "trade-board", "trading"}:
            return no_update

        scope = get_current_trade_scope()
        return f"Showing trades for local user: {scope['app_username']} | OSRS/RuneLite account: {scope['osrs_account_name']}"




    @app.callback(
        Output("openai-key-status", "children"),
        Input("auto-refresh", "n_intervals"),
        Input("main-tabs", "value"),
    )
    def update_openai_key_status(_, active_tab):
        if active_tab != "admin":
            return no_update

        status = get_api_key_status()

        if not status.get("has_key"):
            return (
                "No saved OpenAI API key for this account. "
                "AI Advisor will use .env fallback only if one exists."
            )

        return (
            f"Saved key: {status.get('key_hint')} | "
            f"Updated: {status.get('updated_at') or 'n/a'} | "
            f"Last used: {status.get('last_used_at') or 'n/a'}"
        )


    @app.callback(
        Output("openai-usage-status", "children"),
        Input("auto-refresh", "n_intervals"),
        Input("main-tabs", "value"),
    )
    def update_openai_usage_status(_, active_tab):
        if active_tab != "admin":
            return no_update

        init_ai_usage_db()
        summary = get_ai_usage_summary()

        return format_ai_usage_summary(summary)


    @app.callback(
        Output("openai-key-action-status", "children"),
        Output("setting-openai-api-key", "value"),
        Input("save-openai-key-button", "n_clicks"),
        Input("delete-openai-key-button", "n_clicks"),
        State("setting-openai-api-key", "value"),
        State("confirm-delete-openai-key", "value"),
        prevent_initial_call=True
    )
    def save_or_delete_openai_key(save_clicks, delete_clicks, api_key, confirm_delete):
        triggered_id = ctx.triggered_id

        try:
            if triggered_id == "save-openai-key-button":
                api_key = str(api_key or "").strip()
                valid, message = validate_key_shape(api_key)

                if not valid:
                    return f"Key was not saved: {message}", ""

                result = save_api_key(api_key)
                return f"Encrypted OpenAI API key saved for this account: {result['key_hint']}", ""

            if triggered_id == "delete-openai-key-button":
                if str(confirm_delete or "").strip() != "DELETE API KEY":
                    return "Type DELETE API KEY before deleting the saved key.", ""

                deleted = delete_api_key()
                return f"Deleted saved OpenAI API key rows: {deleted}", ""

            return "No API key action selected.", ""

        except Exception as error:
            return f"API key action failed: {error}", ""


    @app.callback(
        Output("settings-account-scope", "children"),
        Input("auto-refresh", "n_intervals"),
        Input("main-tabs", "value"),
    )
    def update_settings_account_scope(_, active_tab):
        if active_tab != "admin":
            return no_update

        scope = get_current_trade_scope()
        return f"Settings are saved for local user: {scope['app_username']} | OSRS/RuneLite account: {scope['osrs_account_name']}"


    @app.callback(
        Output("core-settings-status", "children"),
        Input("save-core-settings-button", "n_clicks"),
        State("setting-cash-stack", "value"),
        State("setting-capital-budget-mode", "value"),
        State("setting-minimum-profit", "value"),
        State("setting-risk-profile", "value"),
        State("setting-watch-seconds", "value"),
        State("setting-start-dashboard", "value"),
        State("setting-start-collector", "value"),
        State("setting-start-trade-watcher", "value"),
        State("setting-open-browser", "value"),
        State("setting-dashboard-open-mode", "value"),
        State("setting-control-center-status-mode", "value"),
        prevent_initial_call=True
    )
    def save_core_settings(
        n_clicks,
        cash_stack,
        capital_budget_mode,
        minimum_profit,
        risk_profile,
        watch_seconds,
        start_dashboard,
        start_collector,
        start_trade_watcher,
        open_browser,
        dashboard_open_mode,
        control_center_status_mode,
    ):
        if not n_clicks:
            return ""

        try:
            set_setting("cash_stack", int(cash_stack or 0), "int")
            set_setting("capital_budget_mode", capital_budget_mode or "live_capped", "str")
            set_setting("minimum_profit", int(minimum_profit or 0), "int")
            set_setting("risk_profile", risk_profile or "medium", "str")
            set_setting("watch_seconds", int(watch_seconds or 10), "int")
            set_setting("start_dashboard", start_dashboard == "true", "bool")
            set_setting("start_collector", start_collector == "true", "bool")
            set_setting("start_trade_watcher", start_trade_watcher == "true", "bool")
            set_setting("open_browser", open_browser == "true", "bool")
            set_setting("dashboard_open_mode", dashboard_open_mode or "app", "str")
            set_setting("control_center_status_mode", control_center_status_mode or "quiet", "str")

            return "Startup / collector settings saved. Restart the control center for startup changes to take effect."

        except Exception as error:
            return f"Settings save failed: {error}"


    @app.callback(
        Output("ai-settings-status", "children"),
        Input("save-ai-settings-button", "n_clicks"),
        State("setting-ai-source-row-limit", "value"),
        State("setting-ai-quick-choices", "value"),
        State("setting-ai-overnight-choices", "value"),
        State("setting-ai-value-choices", "value"),
        State("setting-exclude-items-traded-today", "value"),
        State("setting-max-ai-requests-per-day", "value"),
        State("setting-ai-input-cost-per-1m-tokens", "value"),
        State("setting-ai-output-cost-per-1m-tokens", "value"),
        State("setting-overnight-slot-target", "value"),
        State("setting-min-overnight-raw-margin", "value"),
        State("setting-min-overnight-roi-percent", "value"),
        State("setting-max-small-loss-percent", "value"),
        State("setting-max-medium-loss-percent", "value"),
        prevent_initial_call=True
    )
    def save_ai_settings(
        n_clicks,
        source_limit,
        quick_choices,
        overnight_choices,
        value_choices,
        exclude_today,
        max_ai_requests,
        input_cost_per_1m,
        output_cost_per_1m,
        overnight_slot_target,
        min_margin,
        min_roi,
        small_loss,
        medium_loss,
    ):
        if not n_clicks:
            return ""

        try:
            set_setting("ai_source_row_limit", int(source_limit or 350), "int")
            set_setting("ai_quick_choices", int(quick_choices or 10), "int")
            set_setting("ai_overnight_choices", int(overnight_choices or 10), "int")
            set_setting("ai_value_choices", int(value_choices or 10), "int")
            set_setting("exclude_items_traded_today", exclude_today == "true", "bool")
            set_setting("max_ai_requests_per_day", int(max_ai_requests or 0), "int")
            set_setting("ai_input_cost_per_1m_tokens", float(input_cost_per_1m or 0), "float")
            set_setting("ai_output_cost_per_1m_tokens", float(output_cost_per_1m or 0), "float")
            target_slots = max(0, min(2, int(overnight_slot_target or 1)))
            set_setting("overnight_slot_target", target_slots, "int")
            set_setting("min_overnight_raw_margin", int(min_margin or 10000), "int")
            set_setting("min_overnight_roi_percent", float(min_roi or 5.0), "float")
            set_setting("max_small_loss_percent", float(small_loss or 2.0), "float")
            set_setting("max_medium_loss_percent", float(medium_loss or 5.0), "float")

            return "AI settings saved. New AI runs will use these values."

        except Exception as error:
            return f"AI settings save failed: {error}"



    @app.callback(
        Output("status-log-cards", "children"),
        Input("auto-refresh", "n_intervals"),
        Input("main-tabs", "value"),
    )
    def update_status_log_cards(_, active_tab):
        if active_tab != "admin":
            return no_update

        summary = get_status_summary()
        return build_status_cards(summary)


    @app.callback(
        Output("log-file-output", "children"),
        Input("log-file-select", "value"),
        Input("log-line-count", "value"),
        Input("auto-refresh", "n_intervals"),
        Input("main-tabs", "value"),
    )
    def update_log_file_output(log_file_name, line_count, _, active_tab):
        if active_tab != "admin":
            return no_update

        if not log_file_name:
            return "No log file selected."

        safe_name = os.path.basename(log_file_name)
        log_path = os.path.join(LOG_DIR, safe_name)

        return read_last_lines(log_path, max_lines=int(line_count or 80))



    @app.callback(
        Output("maintenance-status", "children"),
        Output("maintenance-download", "data"),
        Output("health-check-output", "children"),
        Output("release-check-output", "children"),
        Output("backup-release-status", "children"),
        Input("backup-database-button", "n_clicks"),
        Input("run-health-check-button", "n_clicks"),
        Input("optimize-database-button", "n_clicks"),
        Input("run-migrations-button", "n_clicks"),
        Input("run-release-check-button", "n_clicks"),
        Input("create-private-backup-button", "n_clicks"),
        Input("prepare-clean-release-button", "n_clicks"),
        Input("update-installer-dry-run-button", "n_clicks"),
        Input("import-runelite-now-button", "n_clicks"),
        Input("export-completed-trades-button", "n_clicks"),
        Input("export-trade-events-button", "n_clicks"),
        Input("export-ai-notes-button", "n_clicks"),
        Input("export-latest-scan-button", "n_clicks"),
        Input("clear-ai-notes-button", "n_clicks"),
        Input("clear-logs-button", "n_clicks"),
        Input("reset-ai-advice-button", "n_clicks"),
        State("confirm-clear-ai-notes", "value"),
        State("confirm-clear-logs", "value"),
        State("confirm-reset-ai-advice", "value"),
        prevent_initial_call=True
    )
    def run_maintenance_action(
        backup_clicks,
        health_check_clicks,
        optimize_clicks,
        migration_clicks,
        release_check_clicks,
        private_backup_clicks,
        prepare_release_clicks,
        update_installer_dry_run_clicks,
        import_runelite_clicks,
        completed_clicks,
        events_clicks,
        notes_clicks,
        scan_clicks,
        clear_ai_notes_clicks,
        clear_logs_clicks,
        reset_ai_advice_clicks,
        confirm_clear_ai_notes,
        confirm_clear_logs,
        confirm_reset_ai_advice
    ):
        triggered_id = ctx.triggered_id

        if not triggered_id:
            return "No action selected.", no_update, no_update, no_update, no_update

        try:
            if triggered_id == "backup-database-button":
                path = backup_database_file()
                return f"Database backup created: {path}", no_update, no_update, no_update, no_update

            if triggered_id == "run-health-check-button":
                text, report_path = run_health_check_report()
                return f"Health check complete. Report saved to: {report_path}", no_update, text, no_update, no_update

            if triggered_id == "optimize-database-button":
                backup_path = optimize_database_file()
                return f"Database optimized. Backup created first: {backup_path}", no_update, no_update, no_update, no_update

            if triggered_id == "run-migrations-button":
                result = run_app_migrations(force=True, write_report=True)
                return f"Database repair/migrations complete. Report: {result.get('report_path')}", no_update, no_update, no_update, no_update

            if triggered_id == "run-release-check-button":
                result = run_release_check(strict=False, write_report=True)
                status = result.get("status", "UNKNOWN")
                report_path = result.get("report_path", "")
                return f"Release check finished with status {status}. Report: {report_path}", no_update, no_update, result.get("report", ""), no_update

            if triggered_id == "create-private-backup-button":
                result = create_private_backup(reason="dashboard")
                message = (
                    f"Private backup created: {result.get('path')} | "
                    f"files: {result.get('file_count')} | "
                    f"missing optional files: {result.get('missing_count')}. "
                    "Do not share this backup publicly."
                )
                return "Private backup complete.", no_update, no_update, no_update, message

            if triggered_id == "prepare-clean-release-button":
                result = prepare_clean_release_package(include_exe=True, zip_release=True, run_check=True)
                message = (
                    f"Clean release folder: {result.get('release_dir')} | "
                    f"zip: {result.get('zip_path')} | "
                    f"files: {result.get('file_count')} | "
                    f"warnings: {result.get('warning_count')} | "
                    f"missing: {result.get('missing_count')}. "
                    "Private database, .env, logs, backups, exports, and runtime files are excluded."
                )
                return "Clean release package prepared.", no_update, no_update, no_update, message

            if triggered_id == "update-installer-dry-run-button":
                result = install_update(
                    source_root=BASE_DIR,
                    target_root=BASE_DIR,
                    dry_run=True,
                    no_backup=True,
                    no_migrations=True,
                    no_release_check=True,
                    allow_same_folder=True
                )
                message = (
                    f"Update installer dry run complete. "
                    f"Would copy {len(result.get('copied_files', []))} release files. "
                    "No files were changed."
                )
                return "Update installer dry run complete.", no_update, no_update, no_update, message

            if triggered_id == "import-runelite-now-button":
                result = import_runelite_now()
                return (
                    "RuneLite import finished: "
                    f"imported {result.get('imported', 0)}, "
                    f"skipped {result.get('skipped', 0)}, "
                    f"matched {result.get('matched', 0)}. "
                    f"File: {result.get('file', '')}"
                ), no_update, no_update, no_update, no_update

            if triggered_id == "export-completed-trades-button":
                path = export_completed_trades_csv()
                return f"Completed trades exported: {path}", dcc.send_file(path), no_update, no_update, no_update

            if triggered_id == "export-trade-events-button":
                path = export_trade_events_csv()
                return f"Trade events exported: {path}", dcc.send_file(path), no_update, no_update, no_update

            if triggered_id == "export-ai-notes-button":
                path = export_ai_notes_csv()
                return f"AI notes exported: {path}", dcc.send_file(path), no_update, no_update, no_update

            if triggered_id == "export-latest-scan-button":
                path = export_latest_scan_csv()
                return f"Latest scan exported: {path}", dcc.send_file(path), no_update, no_update, no_update

            if triggered_id == "clear-ai-notes-button":
                if str(confirm_clear_ai_notes or "").strip() != "CLEAR AI NOTES":
                    return "Type CLEAR AI NOTES before clearing current account AI notes.", no_update, no_update, no_update, no_update

                backup_path, deleted = clear_current_account_ai_notes()
                return f"Cleared {deleted} AI notes for the current account. Backup created first: {backup_path}", no_update, no_update, no_update, no_update

            if triggered_id == "clear-logs-button":
                if str(confirm_clear_logs or "").strip() != "CLEAR LOGS":
                    return "Type CLEAR LOGS before clearing logs.", no_update, no_update, no_update, no_update

                cleared = clear_log_files()
                return f"Cleared {cleared} log files.", no_update, no_update, no_update, no_update

            if triggered_id == "reset-ai-advice-button":
                if str(confirm_reset_ai_advice or "").strip() != "RESET AI":
                    return "Type RESET AI before resetting saved AI advice.", no_update, no_update, no_update, no_update

                backup_path = reset_ai_advice_file()

                if backup_path:
                    return f"Saved AI advice moved to backup: {backup_path}", no_update, no_update, no_update, no_update

                return "No saved AI advice file existed to reset.", no_update, no_update, no_update, no_update

            return "Unknown maintenance action.", no_update, no_update, no_update, no_update

        except Exception as error:
            return f"Maintenance action failed: {error}", no_update, no_update, no_update, no_update



    @app.callback(
        Output("setup-checklist-table", "data"),
        Input("auto-refresh", "n_intervals"),
        Input("main-tabs", "value"),
    )
    def update_setup_checklist(_, active_tab):
        if active_tab != "admin":
            return no_update

        return get_setup_summary_items()


    @app.callback(
        Output("setup-api-key-status", "children"),
        Output("setup-openai-api-key", "value"),
        Input("setup-save-openai-key-button", "n_clicks"),
        State("setup-openai-api-key", "value"),
        prevent_initial_call=True
    )
    def setup_save_openai_key(n_clicks, api_key):
        if not n_clicks:
            return "", ""

        try:
            api_key = str(api_key or "").strip()
            valid, message = validate_key_shape(api_key)

            if not valid:
                return f"Key was not saved: {message}", ""

            result = save_api_key(api_key)
            return f"Encrypted OpenAI API key saved: {result['key_hint']}", ""

        except Exception as error:
            return f"Could not save OpenAI API key: {error}", ""


    @app.callback(
        Output("setup-settings-status", "children"),
        Input("setup-save-settings-button", "n_clicks"),
        State("setup-cash-stack", "value"),
        State("setup-minimum-profit", "value"),
        State("setup-risk-profile", "value"),
        State("setup-max-ai-requests", "value"),
        prevent_initial_call=True
    )
    def setup_save_quick_settings(n_clicks, cash_stack, minimum_profit, risk_profile, max_ai_requests):
        if not n_clicks:
            return ""

        try:
            set_setting("cash_stack", int(cash_stack or 0), "int")
            set_setting("minimum_profit", int(minimum_profit or 0), "int")
            set_setting("risk_profile", str(risk_profile or "medium"), "str")
            set_setting("max_ai_requests_per_day", int(max_ai_requests or 0), "int")

            return "Setup settings saved."

        except Exception as error:
            return f"Could not save setup settings: {error}"



    @app.callback(
        Output("account-manager-users-table", "data"),
        Output("account-manager-current-user", "children"),
        Input("auto-refresh", "n_intervals"),
        Input("main-tabs", "value"),
    )
    def update_account_manager_table(_, active_tab):
        if active_tab != "admin":
            return no_update, no_update

        current = get_current_session() or {}
        current_text = (
            f"Current session: {current.get('username', 'none')} / "
            f"{current.get('osrs_account_name', 'none')}"
        )

        return get_account_manager_rows(), current_text


    @app.callback(
        Output("account-pin-status", "children"),
        Input("account-pin-button", "n_clicks"),
        State("account-pin-password", "value"),
        State("account-pin-new", "value"),
        State("account-pin-confirm", "value"),
        prevent_initial_call=True
    )
    def save_current_dashboard_pin(n_clicks, password, dashboard_pin, confirm_pin):
        if not n_clicks:
            return ""

        current = get_current_session() or {}
        username = str(current.get("username") or "").strip().lower()
        password = str(password or "")
        dashboard_pin = str(dashboard_pin or "").strip()
        confirm_pin = str(confirm_pin or "").strip()

        if not username:
            return "No current local user is signed in."

        if not password:
            return "Enter the current local password."

        if dashboard_pin != confirm_pin:
            return "PINs do not match."

        valid_pin, pin_message = validate_dashboard_pin(dashboard_pin)

        if not valid_pin:
            return pin_message

        try:
            user = set_dashboard_pin(username, password, dashboard_pin)
            save_session(user)
            unlock_dashboard_for_user(username)
            return "Dashboard PIN saved. Future saved-session unlocks can use this PIN."
        except Exception as error:
            return f"Could not save dashboard PIN: {error}"


    @app.callback(
        Output("account-switch-status", "children"),
        Input("account-switch-button", "n_clicks"),
        State("account-switch-username", "value"),
        State("account-switch-password", "value"),
        State("account-switch-pin", "value"),
        prevent_initial_call=True
    )
    def switch_dashboard_user(n_clicks, username, password, dashboard_pin):
        if not n_clicks:
            return ""

        username = str(username or "").strip().lower()
        password = str(password or "")
        dashboard_pin = str(dashboard_pin or "").strip()

        if not username or not password:
            return "Enter username and password."

        user = authenticate_user(username, password)

        if not user:
            return "Invalid username or password."

        if user_has_dashboard_pin(username) and not dashboard_pin:
            return "Enter the dashboard PIN for this account."

        if dashboard_pin and not verify_dashboard_pin(username, dashboard_pin):
            return "Invalid dashboard PIN."

        save_session(user)
        unlock_dashboard_for_user(user["username"])
        apply_account_env(
            app_username=user["username"],
            osrs_account_name=user["osrs_account_name"]
        )

        return (
            f"Switched dashboard session to {user['username']} / {user['osrs_account_name']}. "
            "Restart the control center so collector and trade watcher use this account too."
        )


    @app.callback(
        Output("account-create-status", "children"),
        Input("account-create-button", "n_clicks"),
        State("account-create-username", "value"),
        State("account-create-password", "value"),
        State("account-create-confirm-password", "value"),
        State("account-create-pin", "value"),
        State("account-create-confirm-pin", "value"),
        State("account-create-osrs-account", "value"),
        prevent_initial_call=True
    )
    def create_dashboard_user(n_clicks, username, password, confirm_password, dashboard_pin, confirm_pin, osrs_account_name):
        if not n_clicks:
            return ""

        username = str(username or "").strip().lower()
        password = str(password or "")
        confirm_password = str(confirm_password or "")
        dashboard_pin = str(dashboard_pin or "").strip()
        confirm_pin = str(confirm_pin or "").strip()
        osrs_account_name = str(osrs_account_name or "").strip()

        if not username:
            return "Username is required."

        if not osrs_account_name:
            return "RuneLite/OSRS account name is required."

        if password != confirm_password:
            return "Passwords do not match."

        if len(password) < 6:
            return "Password must be at least 6 characters."

        if dashboard_pin != confirm_pin:
            return "PINs do not match."

        valid_pin, pin_message = validate_dashboard_pin(dashboard_pin)

        if not valid_pin:
            return pin_message

        try:
            user = create_user(
                username=username,
                password=password,
                osrs_account_name=osrs_account_name,
                dashboard_pin=dashboard_pin
            )

            authenticated = authenticate_user(username, password)

            if authenticated:
                save_session(authenticated)
                unlock_dashboard_for_user(authenticated["username"])
                apply_account_env(
                    app_username=authenticated["username"],
                    osrs_account_name=authenticated["osrs_account_name"]
                )

            return (
                f"Created user {user['username']} linked to {user['osrs_account_name']}. "
                "Add this user's OpenAI key in Setup or Settings."
            )

        except Exception as error:
            return f"Could not create user: {error}"


    @app.callback(
        Output("account-update-status", "children"),
        Input("account-update-button", "n_clicks"),
        State("account-update-username", "value"),
        State("account-update-osrs-account", "value"),
        prevent_initial_call=True
    )
    def update_dashboard_user_osrs_account(n_clicks, username, osrs_account_name):
        if not n_clicks:
            return ""

        username = str(username or "").strip().lower()
        osrs_account_name = str(osrs_account_name or "").strip()

        if not username or not osrs_account_name:
            return "Enter username and new RuneLite/OSRS account name."

        try:
            user = update_osrs_account(username, osrs_account_name)
            current = get_current_session() or {}

            if str(current.get("username") or "").strip().lower() == username:
                apply_account_env(
                    app_username=user["username"],
                    osrs_account_name=user["osrs_account_name"]
                )

            return (
                f"Updated {user['username']} to linked RuneLite/OSRS account {user['osrs_account_name']}. "
                "Restart the control center if collector/trade watcher are running."
            )

        except Exception as error:
            return f"Could not update linked account: {error}"



    @app.callback(
        Output("openai-key-test-status", "children"),
        Input("test-openai-key-button", "n_clicks"),
        prevent_initial_call=True
    )
    def test_settings_openai_key(n_clicks):
        if not n_clicks:
            return ""

        result = test_current_account_openai_key()
        prefix = "PASS" if result.get("ok") else "FAIL"

        return f"{prefix}: {result.get('message', '')}"


    @app.callback(
        Output("setup-api-key-test-status", "children"),
        Input("setup-test-openai-key-button", "n_clicks"),
        prevent_initial_call=True
    )
    def test_setup_openai_key(n_clicks):
        if not n_clicks:
            return ""

        result = test_current_account_openai_key()
        prefix = "PASS" if result.get("ok") else "FAIL"

        return f"{prefix}: {result.get('message', '')}"



    @app.callback(
        Output("safety-review-kpi-cards", "children"),
        Output("safety-review-table", "data"),
        Output("safety-review-table", "columns"),
        Output("safety-review-status", "children"),
        Input("refresh-safety-review-button", "n_clicks"),
        Input("auto-refresh", "n_intervals"),
        Input("main-tabs", "value"),
        Input("trading-workspace-tabs", "value"),
        State("safety-review-limit", "value"),
        State("safety-max-cash-percent", "value"),
        State("safety-max-test-quantity", "value")
    )
    def update_safety_review_table(
        refresh_clicks,
        intervals,
        active_tab,
        trading_tab,
        limit,
        max_cash_percent,
        max_test_quantity,
    ):
        if active_tab not in {"trading", "trade-board"} or trading_tab != "next-moves":
            return no_update, no_update, no_update, no_update

        try:
            set_setting("max_single_item_cash_percent", float(max_cash_percent or 10.0), "float")
            set_setting("max_test_quantity", int(max_test_quantity or 25), "int")

            df = build_safety_review(limit=int(limit or 25))

            if df.empty:
                cards = [
                    make_card("Risk Check", "No data", "run collector/scanner"),
                    make_card("Safer Tests", "0", "candidate count"),
                    make_card("Avoid", "0", "candidate count"),
                ]
                return cards, [], [], "No scan rows found yet. Run the collector/scanner first."

            visible_columns = [
                "Safety Verdict",
                "Item",
                "Suggested Test Qty",
                "Buy Price",
                "Sell Price",
                "Net Margin/Item",
                "Net ROI %",
                "Projected Test Profit",
                "Cash Exposure",
                "Expected Fill",
                "Flags",
            ]
            visible_columns = [column for column in visible_columns if column in df.columns]
            display_df = df[visible_columns].copy()
            verdict_counts = df["Safety Verdict"].value_counts().to_dict() if "Safety Verdict" in df.columns else {}

            cards = [
                make_card("Safer Tests", str(int(verdict_counts.get("Safer Test", 0))), "lowest friction candidates"),
                make_card("Test First", str(int(verdict_counts.get("Test First", 0))), "small test before full qty"),
                make_card("Tiny Test", str(int(verdict_counts.get("Watch / Test Tiny", 0))), "watch or use minimum size"),
                make_card("Avoid", str(int(verdict_counts.get("Avoid", 0))), "do not lead with these"),
            ]

            columns = [{"name": column, "id": column} for column in display_df.columns]
            status = f"Risk check loaded: {len(display_df)} relevant candidates."
            return cards, display_df.to_dict("records"), columns, status

        except Exception as error:
            cards = [
                make_card("Risk Check", "Error", str(error)[:80]),
            ]
            return cards, [], [], f"Risk check failed: {error}"


    @app.callback(
        Output("safety-review-download", "data"),
        Input("export-safety-review-button", "n_clicks"),
        State("safety-review-limit", "value"),
        prevent_initial_call=True
    )
    def export_safety_review(n_clicks, limit):
        if not n_clicks:
            return no_update

        try:
            path, df = write_safety_review(limit=int(limit or 100))
            return dcc.send_file(str(path))

        except Exception:
            return no_update
