"""
Formatting helpers for the OSRSFlipper dashboard.

These functions are intentionally UI-safe and do not touch the database.
"""
import pandas as pd


def format_gp(value):
    if value is None or pd.isna(value):
        return "N/A"

    return f"{int(value):,}"


def format_percent(value):
    if value is None or pd.isna(value):
        return "N/A"

    return f"{round(float(value), 2)}%"


def format_time(value):
    if value is None or pd.isna(value):
        return "N/A"

    try:
        return pd.to_datetime(value).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def parse_positive_int(value, default=100, minimum=10, maximum=500):
    try:
        parsed = int(float(str(value).replace(",", "").strip()))
    except Exception:
        parsed = default

    return max(minimum, min(maximum, parsed))


def summarize_import_result(result):
    if not result:
        return "RuneLite import ran. No details returned."

    if isinstance(result, dict):
        imported = (
            result.get("imported")
            or result.get("imported_rows")
            or result.get("rows_imported")
            or 0
        )
        skipped = (
            result.get("skipped")
            or result.get("skipped_rows")
            or result.get("duplicates")
            or 0
        )
        matched = (
            result.get("matched")
            or result.get("matched_rows")
            or result.get("completed")
            or 0
        )
        status = result.get("status") or "OK"
        message = result.get("message") or ""

        return (
            f"RuneLite import {status}: imported {imported}, "
            f"skipped {skipped}, matched {matched}. {message}"
        ).strip()

    return f"RuneLite import result: {result}"


def clean_trade_display_df(df):
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()

    for column in ["Sell_Time", "Time"]:
        if column in df.columns:
            df[column] = (
                df[column]
                .astype(str)
                .str.replace("T", " ", regex=False)
                .str.replace("+00:00", "", regex=False)
                .str.replace(".000000", "", regex=False)
            )

    return df


def trade_table_columns(df):
    friendly_names = {
        "Sell_Time": "Sell Time",
        "Time": "Time",
        "Item": "Item",
        "Qty": "Qty",
        "Buy_Each": "Buy Each",
        "Sell_Each": "Sell Each",
        "Raw_Margin_Each": "Raw Margin",
        "Tax_Each": "Tax",
        "Net_Profit_Each": "Net Profit Each",
        "Total_Profit": "Total Profit",
        "ROI_Percent": "ROI %",
        "Price_Each": "Price Each",
        "Original_Qty": "Original Qty",
        "Remaining_Qty": "Remaining Qty",
        "Total_Value": "Total Value",
        "Source": "Source",
        "Status": "Status",
        "Notes": "Notes",
        "Side": "Side"
    }

    return [
        {"name": friendly_names.get(column, str(column).replace("_", " ")), "id": column}
        for column in df.columns
    ]


def format_display_number(value, decimals=0, suffix=""):
    if value is None or pd.isna(value):
        return ""

    try:
        number = float(value)
    except Exception:
        return str(value)

    if decimals == 0:
        text = f"{int(round(number)):,}"
    else:
        text = f"{number:,.{decimals}f}"

    return f"{text}{suffix}"


def format_display_bool(value):
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    text = str(value).strip().lower()
    if text in {"1", "true", "yes"}:
        return "Yes"
    if text in {"0", "false", "no"}:
        return "No"
    return str(value)


def format_latest_display_df(df):
    if df is None or df.empty:
        return pd.DataFrame()

    preferred = [
        ("recommendation", "Action"),
        ("recommendation_score", "Score"),
        ("risk_level", "Risk"),
        ("flip_category", "Category"),
        ("item_name", "Item"),
        ("window_name", "Window"),
        ("price_source", "Source"),
        ("target_buy", "Buy"),
        ("target_sell", "Sell"),
        ("raw_margin", "Raw Margin"),
        ("profit_per_item", "Net/Item"),
        ("quantity", "Qty"),
        ("total_profit", "Total Profit"),
        ("roi_percent", "ROI %"),
        ("volume", "Volume"),
        ("expected_fill_time", "Fill Time"),
        ("weekly_trend", "Trend"),
        ("trend_warning", "Warning"),
        ("why", "Why"),
    ]

    out = pd.DataFrame()

    for source, label in preferred:
        if source in df.columns:
            out[label] = df[source]

    money_columns = ["Buy", "Sell", "Raw Margin", "Net/Item", "Total Profit", "Volume", "Qty"]
    for column in money_columns:
        if column in out.columns:
            out[column] = out[column].apply(lambda value: format_display_number(value, decimals=0))

    if "Score" in out.columns:
        out["Score"] = out["Score"].apply(lambda value: format_display_number(value, decimals=2))

    if "ROI %" in out.columns:
        out["ROI %"] = out["ROI %"].apply(lambda value: format_display_number(value, decimals=2, suffix="%"))

    for column in ["Action", "Risk", "Category", "Item", "Window", "Source", "Fill Time", "Trend", "Warning", "Why"]:
        if column in out.columns:
            out[column] = out[column].fillna("").astype(str)

    return out


def format_recurring_display_df(df):
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()

    rename_map = {
        "Avg_Total_Profit": "Avg Profit",
        "Best_Total_Profit": "Best Profit",
        "Avg_Profit_Per_Item": "Avg Net/Item",
        "Avg_ROI_Percent": "Avg ROI %",
        "Avg_Volume": "Avg Volume",
        "Avg_Quick_Score": "Avg Quick",
        "Avg_Overnight_Score": "Avg Overnight",
        "Avg_Recommendation_Score": "Avg Score",
        "Last_Seen": "Last Seen",
    }

    df = df.rename(columns=rename_map)

    preferred = [
        "Item",
        "Window",
        "Appearances",
        "Avg Score",
        "Avg Profit",
        "Best Profit",
        "Avg Net/Item",
        "Avg ROI %",
        "Avg Volume",
        "Avg Quick",
        "Avg Overnight",
        "Last Seen",
    ]

    out = df[[column for column in preferred if column in df.columns]].copy()

    for column in ["Appearances", "Avg Profit", "Best Profit", "Avg Net/Item", "Avg Volume"]:
        if column in out.columns:
            out[column] = out[column].apply(lambda value: format_display_number(value, decimals=0))

    for column in ["Avg Score", "Avg ROI %", "Avg Quick", "Avg Overnight"]:
        if column in out.columns:
            suffix = "%" if column == "Avg ROI %" else ""
            out[column] = out[column].apply(lambda value: format_display_number(value, decimals=2, suffix=suffix))

    if "Last Seen" in out.columns:
        out["Last Seen"] = (
            out["Last Seen"]
            .astype(str)
            .str.replace("T", " ", regex=False)
            .str.replace("+00:00", "", regex=False)
        )

    return out


def build_latest_display_df(df):
    return format_latest_display_df(df)
