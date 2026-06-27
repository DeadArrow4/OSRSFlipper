"""
Dash callback registration for the OSRSFlipper dashboard.

Keep callbacks here so dashboard.py can stay small and easy to scan.
"""
import os

import pandas as pd
import plotly.express as px
from dash import dcc, html, Input, Output, State, ALL, ctx, no_update

from account_context import apply_account_env
from account_manager import (
    authenticate_user,
    create_user,
    get_current_session,
    save_session,
    update_osrs_account,
)
from advisor import generate_ai_advice
from backup_manager import create_private_backup
from migration_manager import run_app_migrations
from openai_key_manager import save_api_key, delete_api_key, validate_key_shape
from openai_key_tester import test_current_account_openai_key
from openai_usage_manager import get_ai_usage_summary, init_ai_usage_db
from prepare_release import prepare_clean_release_package
from release_check import run_release_check
from safety_manager import build_safety_review, write_safety_review
from settings_manager import set_setting
from update_install import install_update

from dashboard_data import *
from dashboard_formatters import *
from dashboard_tabs import build_status_cards
from dashboard_theme import (
empty_figure,
    apply_dark_chart_layout,
    make_card,
)
from data_health import build_data_health_snapshot, build_data_trend_snapshot, ensure_data_health_schema, rebuild_daily_item_metrics
from data_health import build_item_trend_explorer_snapshot

def register_dashboard_callbacks(app):




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
        def columns_for(rows):
            if not rows:
                return []
            return [{"name": str(key), "id": str(key)} for key in rows[0].keys()]

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
                    columns_for(matches),
                    rows,
                    columns_for(rows),
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
                columns_for(matches),
                rows,
                columns_for(rows),
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
                columns_for(error_rows),
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
        def columns_for(rows):
            if not rows:
                return []
            return [{"name": str(key), "id": str(key)} for key in rows[0].keys()]

        try:
            snapshot = build_data_trend_snapshot(limit=25)

            readiness = snapshot.get("readiness", [])
            top_trends = snapshot.get("top_trends", [])

            return (
                readiness,
                columns_for(readiness),
                top_trends,
                columns_for(top_trends),
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
                columns_for(readiness),
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
        Input("refresh-data-health-button", "n_clicks"),
        Input("apply-data-health-schema-button", "n_clicks"),
        Input("rebuild-daily-metrics-button", "n_clicks"),
        State("daily-metrics-days", "value"),
    )
    def update_data_health(refresh_clicks, schema_clicks, rebuild_clicks, rebuild_days):
        try:
            from dash import ctx as dash_ctx

            triggered_id = dash_ctx.triggered_id or "initial-load"
            action_status = ""

            if triggered_id == "apply-data-health-schema-button":
                result = ensure_data_health_schema()
                action_status = result.get("status", "Schema/index check complete.")
            elif triggered_id == "rebuild-daily-metrics-button":
                result = rebuild_daily_item_metrics(days=rebuild_days or 120)
                action_status = result.get("status", "Daily metrics rebuild complete.")

            snapshot = build_data_health_snapshot()

            def columns_for(rows):
                if not rows:
                    return []
                return [{"name": str(key), "id": str(key)} for key in rows[0].keys()]

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

            return (
                status,
                cards,
                tables,
                columns_for(tables),
                time_rows,
                columns_for(time_rows),
                index_rows,
                columns_for(index_rows),
                metric_rows,
                columns_for(metric_rows),
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
    )
    def update_open_slot_actions(n_clicks):
        try:
            from datetime import datetime

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
                f"Last update {refreshed_at}. Refresh clicks={n_clicks or 0}."
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
    )
    def update_trade_board_phase1(
        n_clicks,
        risk_profile,
        limit,
        minimum_profit,
        action_filter,
        confidence_filter,
        fill_filter,
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

            visible_count = len(board_df)
            filtered_count = int(summary.get("filtered_count", visible_count))
            source_count = int(summary.get("filter_source_count", filtered_count))

            cards = [
                make_card("Latest Run", str(summary.get("latest_run_id", "n/a")), f"{summary.get('candidate_count', 0):,} ranked candidates"),
                make_card("Buy Now", str(summary.get("buy_now_count", 0)), "strict quick candidates"),
                make_card("Test Small", str(summary.get("test_small_count", 0)), "promising but cautious"),
                make_card("Overnight", str(summary.get("overnight_count", 0)), "overnight candidates"),
                make_card("Avoid / Wait", str(summary.get("avoid_count", 0)), "filtered or warning rows"),
                make_card("Visible Rows", f"{visible_count}/{filtered_count}", f"from {source_count} ranked rows"),
                make_card("Best Profit", f"{format_gp(summary.get('best_profit', 0))} gp", f"min {format_gp(summary.get('minimum_profit', 0))} gp"),
            ]

            status = (
                f"{summary.get('status', 'Trade Board updated.')} "
                f"Last update {refreshed_at}. Trigger: {triggered_id}. "
                f"Risk={risk_profile or 'medium'}, Rows={visible_limit}, Min profit={format_gp(summary.get('minimum_profit', 0))} gp. "
                f"Action filter={summary.get('action_filter', action_filter or 'all')}, "
                f"Confidence filter={summary.get('confidence_filter', confidence_filter or 'all')}, "
                f"Fill filter={summary.get('fill_filter', fill_filter or 'all')}. "
                f"Showing {visible_count} of {filtered_count} matching rows from {source_count} ranked rows. "
                f"Refresh clicks={n_clicks or 0}."
            )

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
            cards = [
                make_card("Trade Board", "Error", "send the status line"),
                make_card("Phase", "deep filters", "single-table callback"),
            ]
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
        Input("auto-refresh", "n_intervals")
    )
    def update_dashboard(
        window_filter,
        result_type_filter,
        signal_filter,
        category_filter,
        trend_filter,
        limit,
        _
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
        Output("completed-trades-table", "data"),
        Output("completed-trades-table", "columns"),
        Output("open-trades-table", "data"),
        Output("open-trades-table", "columns"),
        Input("refresh-trades-button", "n_clicks"),
        Input("auto-refresh", "n_intervals"),
        Input("main-tabs", "value"),
        State("my-trades-limit", "value")
    )
    def update_trade_dashboard(refresh_clicks, intervals, active_tab, row_limit):
        if active_tab != "my-trades":
            return (
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

        if triggered_id == "refresh-trades-button":
            import_status = refresh_runelite_trades_for_dashboard()

            try:
                clear_trade_dashboard_cache()
            except Exception:
                pass

            try:
                clear_dashboard_cache()
            except Exception:
                pass

        elif triggered_id == "auto-refresh":
            import_status = "Auto refreshed saved trade data. RuneLite import only runs when you click Import RuneLite & Refresh Trades."
        else:
            import_status = "Loaded saved trade data. Click Import RuneLite & Refresh Trades to import the latest RuneLite file."

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

        completed_df = clean_trade_display_df(get_completed_trade_rows(limit=limit))
        open_df = clean_trade_display_df(get_open_trade_rows(limit=limit))

        completed_data = completed_df.to_dict("records")
        completed_columns = trade_table_columns(completed_df)

        open_data = open_df.to_dict("records")
        open_columns = trade_table_columns(open_df)

        return (
            import_status,
            cards,
            profit_fig,
            item_fig,
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

            status = (
                "AI advice generated successfully. "
                f"Risk profile: {risk_profile}. "
                f"Candidate source limit: {limit}."
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
        Input("main-tabs", "value"),
    )
    def update_trade_account_scope(_, active_tab):
        if active_tab != "my-trades":
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

        today = summary["today"]
        all_time = summary["all_time"]
        limit = summary["daily_limit"]

        return (
            f"AI usage today: {today.get('total_requests', 0)}/{limit} requests, "
            f"{int(today.get('total_tokens', 0) or 0):,} tokens. "
            f"All time: {all_time.get('total_requests', 0)} requests, "
            f"{int(all_time.get('total_tokens', 0) or 0):,} tokens."
        )


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
        State("setting-minimum-profit", "value"),
        State("setting-risk-profile", "value"),
        State("setting-watch-seconds", "value"),
        State("setting-start-dashboard", "value"),
        State("setting-start-collector", "value"),
        State("setting-start-trade-watcher", "value"),
        State("setting-open-browser", "value"),
        prevent_initial_call=True
    )
    def save_core_settings(n_clicks, cash_stack, minimum_profit, risk_profile, watch_seconds, start_dashboard, start_collector, start_trade_watcher, open_browser):
        if not n_clicks:
            return ""

        try:
            set_setting("cash_stack", int(cash_stack or 0), "int")
            set_setting("minimum_profit", int(minimum_profit or 0), "int")
            set_setting("risk_profile", risk_profile or "medium", "str")
            set_setting("watch_seconds", int(watch_seconds or 10), "int")
            set_setting("start_dashboard", start_dashboard == "true", "bool")
            set_setting("start_collector", start_collector == "true", "bool")
            set_setting("start_trade_watcher", start_trade_watcher == "true", "bool")
            set_setting("open_browser", open_browser == "true", "bool")

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
        State("setting-min-overnight-raw-margin", "value"),
        State("setting-min-overnight-roi-percent", "value"),
        State("setting-max-small-loss-percent", "value"),
        State("setting-max-medium-loss-percent", "value"),
        prevent_initial_call=True
    )
    def save_ai_settings(n_clicks, source_limit, quick_choices, overnight_choices, value_choices, exclude_today, max_ai_requests, min_margin, min_roi, small_loss, medium_loss):
        if not n_clicks:
            return ""

        try:
            set_setting("ai_source_row_limit", int(source_limit or 350), "int")
            set_setting("ai_quick_choices", int(quick_choices or 10), "int")
            set_setting("ai_overnight_choices", int(overnight_choices or 10), "int")
            set_setting("ai_value_choices", int(value_choices or 10), "int")
            set_setting("exclude_items_traded_today", exclude_today == "true", "bool")
            set_setting("max_ai_requests_per_day", int(max_ai_requests or 0), "int")
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
        Output("account-switch-status", "children"),
        Input("account-switch-button", "n_clicks"),
        State("account-switch-username", "value"),
        State("account-switch-password", "value"),
        prevent_initial_call=True
    )
    def switch_dashboard_user(n_clicks, username, password):
        if not n_clicks:
            return ""

        username = str(username or "").strip().lower()
        password = str(password or "")

        if not username or not password:
            return "Enter username and password."

        user = authenticate_user(username, password)

        if not user:
            return "Invalid username or password."

        save_session(user)
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
        State("account-create-osrs-account", "value"),
        prevent_initial_call=True
    )
    def create_dashboard_user(n_clicks, username, password, confirm_password, osrs_account_name):
        if not n_clicks:
            return ""

        username = str(username or "").strip().lower()
        password = str(password or "")
        confirm_password = str(confirm_password or "")
        osrs_account_name = str(osrs_account_name or "").strip()

        if not username:
            return "Username is required."

        if not osrs_account_name:
            return "RuneLite/OSRS account name is required."

        if password != confirm_password:
            return "Passwords do not match."

        if len(password) < 6:
            return "Password must be at least 6 characters."

        try:
            user = create_user(
                username=username,
                password=password,
                osrs_account_name=osrs_account_name
            )

            authenticated = authenticate_user(username, password)

            if authenticated:
                save_session(authenticated)
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
        Output("safety-review-table", "data"),
        Output("safety-review-table", "columns"),
        Output("safety-review-status", "children"),
        Input("refresh-safety-review-button", "n_clicks"),
        Input("auto-refresh", "n_intervals"),
        Input("main-tabs", "value"),
        State("safety-review-limit", "value"),
        State("safety-max-cash-percent", "value"),
        State("safety-max-test-quantity", "value")
    )
    def update_safety_review_table(refresh_clicks, intervals, active_tab, limit, max_cash_percent, max_test_quantity):
        if active_tab != "safety-review":
            return no_update, no_update, no_update

        try:
            set_setting("max_single_item_cash_percent", float(max_cash_percent or 10.0), "float")
            set_setting("max_test_quantity", int(max_test_quantity or 25), "int")

            df = build_safety_review(limit=int(limit or 100))

            if df.empty:
                return [], [], "No scan rows found yet. Run the collector/scanner first."

            columns = [{"name": column, "id": column} for column in df.columns]
            return df.to_dict("records"), columns, f"Safety review loaded: {len(df)} candidates."

        except Exception as error:
            return [], [], f"Safety review failed: {error}"


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
