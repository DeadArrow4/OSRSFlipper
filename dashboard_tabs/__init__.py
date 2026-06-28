"""Dash tab and page-layout builders for the OSRSFlipper dashboard."""
from .admin import (
    build_about_tab,
    build_account_manager_tab,
    build_admin_tab,
    build_data_health_tab,
    build_log_dropdown_options,
    build_maintenance_tab,
    build_safety_review_tab,
    build_settings_tab,
    build_setup_tab,
    build_status_cards,
    build_status_logs_tab,
)
from .ai import build_ai_panel
from .app_layout import build_app_layout
from .market import (
    build_item_trend_explorer_tab,
    build_market_data_tab,
    build_market_item_history_tab,
)
from .overview import (
    build_filters,
    build_item_history_tab,
    build_latest_table,
    build_recurring_table,
)
from .trade_board import build_trade_board_tab, build_trading_workspace_tab
from .trades import build_current_trades_tab, build_my_trades_tab, build_trade_history_tab

__all__ = [
    "build_about_tab",
    "build_account_manager_tab",
    "build_admin_tab",
    "build_ai_panel",
    "build_app_layout",
    "build_data_health_tab",
    "build_filters",
    "build_current_trades_tab",
    "build_item_history_tab",
    "build_item_trend_explorer_tab",
    "build_latest_table",
    "build_log_dropdown_options",
    "build_maintenance_tab",
    "build_market_data_tab",
    "build_market_item_history_tab",
    "build_my_trades_tab",
    "build_recurring_table",
    "build_safety_review_tab",
    "build_settings_tab",
    "build_setup_tab",
    "build_status_cards",
    "build_status_logs_tab",
    "build_trade_board_tab",
    "build_trade_history_tab",
    "build_trading_workspace_tab",
]
