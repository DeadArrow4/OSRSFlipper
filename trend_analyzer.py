import statistics


# =========================
# TREND SETTINGS
# =========================

DAILY_HOURS = 24
WEEKLY_HOURS = 24 * 7

TREND_DATA_MAX_ITEMS = 50

HIGH_VOLATILITY_PERCENT = 8
EXTREME_VOLATILITY_PERCENT = 14

NEAR_7D_HIGH_PERCENT = 85
NEAR_7D_LOW_PERCENT = 15


# =========================
# BASIC HELPERS
# =========================

def safe_number(value, default=0):
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def get_mid_price(point):
    avg_high = point.get("avgHighPrice")
    avg_low = point.get("avgLowPrice")

    if avg_high is not None and avg_low is not None:
        if avg_high > 0 and avg_low > 0:
            return (avg_high + avg_low) / 2

    if avg_high is not None and avg_high > 0:
        return avg_high

    if avg_low is not None and avg_low > 0:
        return avg_low

    return None


def get_point_volume(point):
    high_volume = point.get("highPriceVolume") or 0
    low_volume = point.get("lowPriceVolume") or 0

    return high_volume + low_volume


def clean_series(series):
    """
    Converts raw OSRS Wiki timeseries points into a cleaner list.

    Each output point contains:
    - timestamp
    - mid_price
    - volume
    """
    cleaned = []

    for point in series:
        mid_price = get_mid_price(point)

        if mid_price is None or mid_price <= 0:
            continue

        cleaned.append({
            "timestamp": point.get("timestamp"),
            "mid_price": mid_price,
            "volume": get_point_volume(point)
        })

    cleaned.sort(key=lambda x: x["timestamp"] or 0)

    return cleaned


def percent_change(start_value, end_value):
    if start_value is None or end_value is None:
        return None

    if start_value <= 0:
        return None

    return ((end_value - start_value) / start_value) * 100


def calculate_volatility_percent(points):
    """
    Calculates simple volatility based on percent changes between points.

    This is not financial-grade volatility. It is a practical warning signal:
    higher value = price has been jumping around more.
    """
    if len(points) < 3:
        return None

    changes = []

    for index in range(1, len(points)):
        previous_price = points[index - 1]["mid_price"]
        current_price = points[index]["mid_price"]

        change = percent_change(previous_price, current_price)

        if change is not None:
            changes.append(change)

    if len(changes) < 2:
        return None

    return statistics.stdev(changes)


def trend_label(change_percent, volatility_percent, short_term=False):
    if change_percent is None:
        return "Unknown"

    if volatility_percent is not None:
        if volatility_percent >= EXTREME_VOLATILITY_PERCENT:
            return "Extremely volatile"

        if volatility_percent >= HIGH_VOLATILITY_PERCENT:
            return "Volatile"

    if short_term:
        if change_percent >= 3:
            return "Rising"

        if change_percent <= -3:
            return "Falling"

        return "Stable"

    if change_percent >= 7:
        return "Strong uptrend"

    if change_percent >= 2:
        return "Slight uptrend"

    if change_percent <= -7:
        return "Strong downtrend"

    if change_percent <= -2:
        return "Slight downtrend"

    return "Stable"


def price_position_percent(latest_price, low_price, high_price):
    if latest_price is None or low_price is None or high_price is None:
        return None

    if high_price <= low_price:
        return None

    return ((latest_price - low_price) / (high_price - low_price)) * 100


# =========================
# TREND ANALYSIS
# =========================

def analyze_hourly_trend(hourly_series):
    cleaned = clean_series(hourly_series)

    if not cleaned:
        return {
            "daily_change_percent": None,
            "weekly_change_percent": None,
            "daily_volatility_percent": None,
            "weekly_volatility_percent": None,
            "weekly_high": None,
            "weekly_low": None,
            "price_position_7d_percent": None,
            "daily_trend": "Unknown",
            "weekly_trend": "Unknown",
            "trend_confidence": "No data",
            "hourly_points": 0
        }

    latest_price = cleaned[-1]["mid_price"]

    daily_points = cleaned[-DAILY_HOURS:]
    weekly_points = cleaned[-WEEKLY_HOURS:]

    daily_change = None
    weekly_change = None

    if len(daily_points) >= 2:
        daily_change = percent_change(
            daily_points[0]["mid_price"],
            daily_points[-1]["mid_price"]
        )

    if len(weekly_points) >= 2:
        weekly_change = percent_change(
            weekly_points[0]["mid_price"],
            weekly_points[-1]["mid_price"]
        )

    daily_volatility = calculate_volatility_percent(daily_points)
    weekly_volatility = calculate_volatility_percent(weekly_points)

    weekly_prices = [
        point["mid_price"]
        for point in weekly_points
    ]

    weekly_high = max(weekly_prices) if weekly_prices else None
    weekly_low = min(weekly_prices) if weekly_prices else None

    position_7d = price_position_percent(
        latest_price=latest_price,
        low_price=weekly_low,
        high_price=weekly_high
    )

    if len(cleaned) >= WEEKLY_HOURS:
        trend_confidence = "High"
    elif len(cleaned) >= DAILY_HOURS:
        trend_confidence = "Medium"
    elif len(cleaned) >= 6:
        trend_confidence = "Low"
    else:
        trend_confidence = "Very low"

    return {
        "daily_change_percent": daily_change,
        "weekly_change_percent": weekly_change,
        "daily_volatility_percent": daily_volatility,
        "weekly_volatility_percent": weekly_volatility,
        "weekly_high": weekly_high,
        "weekly_low": weekly_low,
        "price_position_7d_percent": position_7d,
        "daily_trend": trend_label(
            daily_change,
            daily_volatility,
            short_term=True
        ),
        "weekly_trend": trend_label(
            weekly_change,
            weekly_volatility,
            short_term=False
        ),
        "trend_confidence": trend_confidence,
        "hourly_points": len(cleaned)
    }


def analyze_daily_trend(daily_series):
    cleaned = clean_series(daily_series)

    if not cleaned:
        return {
            "long_term_change_percent": None,
            "long_term_trend": "Unknown",
            "daily_points": 0
        }

    long_term_change = None

    if len(cleaned) >= 2:
        long_term_change = percent_change(
            cleaned[0]["mid_price"],
            cleaned[-1]["mid_price"]
        )

    return {
        "long_term_change_percent": long_term_change,
        "long_term_trend": trend_label(
            long_term_change,
            None,
            short_term=False
        ),
        "daily_points": len(cleaned)
    }


def build_trend_warning(hourly_stats, row):
    warnings = []

    weekly_change = hourly_stats.get("weekly_change_percent")
    weekly_volatility = hourly_stats.get("weekly_volatility_percent")
    position_7d = hourly_stats.get("price_position_7d_percent")

    price_warning = row.get("Price Warning", "OK")
    margin_warning = row.get("Margin Warning", "OK")

    if price_warning and price_warning != "OK":
        warnings.append("latest price differs from average")

    if margin_warning and margin_warning != "OK":
        warnings.append("margin is far above historical average")

    if weekly_change is not None and weekly_change <= -7:
        warnings.append("weekly trend is falling")

    if weekly_change is not None and weekly_change >= 12:
        warnings.append("weekly price has risen sharply")

    if weekly_volatility is not None and weekly_volatility >= HIGH_VOLATILITY_PERCENT:
        warnings.append("weekly price is volatile")

    if position_7d is not None and position_7d >= NEAR_7D_HIGH_PERCENT:
        warnings.append("price is near 7-day high")

    if position_7d is not None and position_7d <= NEAR_7D_LOW_PERCENT:
        warnings.append("price is near 7-day low")

    if not warnings:
        return "OK"

    return "; ".join(warnings)


# =========================
# QUICK / OVERNIGHT SCORES
# =========================

def get_fill_score(expected_fill_hours, quick_mode=True):
    if expected_fill_hours is None:
        return 20

    expected_fill_hours = safe_number(expected_fill_hours, 999)

    if quick_mode:
        if expected_fill_hours <= 0.10:
            return 100

        if expected_fill_hours <= 0.50:
            return 85

        if expected_fill_hours <= 1:
            return 70

        if expected_fill_hours <= 2:
            return 45

        return 20

    if expected_fill_hours <= 1:
        return 85

    if expected_fill_hours <= 4:
        return 100

    if expected_fill_hours <= 8:
        return 90

    if expected_fill_hours <= 12:
        return 70

    if expected_fill_hours <= 24:
        return 45

    return 20


def get_window_score(window_name, quick_mode=True):
    if quick_mode:
        if window_name == "5m":
            return 100

        if window_name == "1h":
            return 65

        return 50

    if window_name == "1h":
        return 100

    if window_name == "5m":
        return 65

    return 50


def get_volume_score(volume):
    volume = safe_number(volume)

    if volume >= 10_000:
        return 100

    if volume >= 5_000:
        return 85

    if volume >= 1_000:
        return 70

    if volume >= 500:
        return 55

    if volume >= 100:
        return 40

    return 20


def get_profit_score(total_profit):
    total_profit = safe_number(total_profit)

    return clamp((total_profit / 1_000_000) * 100, 0, 100)


def get_history_score(hist_samples):
    hist_samples = safe_number(hist_samples)

    if hist_samples >= 25:
        return 100

    if hist_samples >= 10:
        return 75

    if hist_samples >= 5:
        return 55

    if hist_samples >= 3:
        return 35

    return 10


def get_trend_safety_score(hourly_stats):
    weekly_change = hourly_stats.get("weekly_change_percent")
    weekly_volatility = hourly_stats.get("weekly_volatility_percent")

    if weekly_change is None:
        return 40

    score = 80

    if -3 <= weekly_change <= 8:
        score += 15
    elif -7 <= weekly_change < -3:
        score -= 10
    elif weekly_change < -7:
        score -= 35
    elif 8 < weekly_change <= 15:
        score -= 10
    elif weekly_change > 15:
        score -= 30

    if weekly_volatility is not None:
        if weekly_volatility >= EXTREME_VOLATILITY_PERCENT:
            score -= 35
        elif weekly_volatility >= HIGH_VOLATILITY_PERCENT:
            score -= 20

    return clamp(score, 0, 100)


def get_price_position_score(position_7d):
    if position_7d is None:
        return 50

    position_7d = safe_number(position_7d)

    if 20 <= position_7d <= 65:
        return 100

    if 65 < position_7d <= 80:
        return 75

    if 10 <= position_7d < 20:
        return 70

    if 80 < position_7d <= 90:
        return 45

    if position_7d > 90:
        return 25

    return 45


def calculate_quick_score(row, hourly_stats):
    liquidity_score = safe_number(row.get("Liquidity Score"), 0)
    expected_fill_hours = row.get("Expected Fill Hours")
    volume = safe_number(row.get("Volume"), 0)
    total_profit = safe_number(row.get("Total Profit"), 0)
    window_name = row.get("Window")

    fill_score = get_fill_score(
        expected_fill_hours,
        quick_mode=True
    )

    volume_score = get_volume_score(volume)
    profit_score = get_profit_score(total_profit)
    window_score = get_window_score(window_name, quick_mode=True)
    trend_safety_score = get_trend_safety_score(hourly_stats)

    score = (
        liquidity_score * 0.30 +
        fill_score * 0.30 +
        volume_score * 0.15 +
        profit_score * 0.10 +
        window_score * 0.10 +
        trend_safety_score * 0.05
    )

    if row.get("Price Warning") and row.get("Price Warning") != "OK":
        score *= 0.70

    if row.get("Margin Warning") and row.get("Margin Warning") != "OK":
        score *= 0.85

    return round(clamp(score, 0, 100), 2)


def calculate_overnight_score(row, hourly_stats):
    liquidity_score = safe_number(row.get("Liquidity Score"), 0)
    expected_fill_hours = row.get("Expected Fill Hours")
    hist_samples = safe_number(row.get("Hist Samples"), 0)
    window_name = row.get("Window")

    fill_score = get_fill_score(
        expected_fill_hours,
        quick_mode=False
    )

    window_score = get_window_score(window_name, quick_mode=False)
    history_score = get_history_score(hist_samples)
    trend_safety_score = get_trend_safety_score(hourly_stats)
    position_score = get_price_position_score(
        hourly_stats.get("price_position_7d_percent")
    )

    score = (
        trend_safety_score * 0.25 +
        position_score * 0.20 +
        liquidity_score * 0.20 +
        history_score * 0.15 +
        fill_score * 0.10 +
        window_score * 0.10
    )

    if row.get("Price Warning") and row.get("Price Warning") != "OK":
        score *= 0.70

    if row.get("Margin Warning") and row.get("Margin Warning") != "OK":
        score *= 0.85

    weekly_change = hourly_stats.get("weekly_change_percent")

    if weekly_change is not None and weekly_change <= -10:
        score *= 0.70

    return round(clamp(score, 0, 100), 2)


# =========================
# PUBLIC ENRICHMENT FUNCTION
# =========================

def enrich_rows_with_trends(rows, trend_data_by_item):
    """
    Adds daily/weekly trend fields to scanner rows.

    Call this after enrich_rows_with_history() and before apply_recommendations().
    """
    for row in rows:
        item_id = row.get("Item ID")

        item_trend_data = trend_data_by_item.get(
            item_id,
            {
                "1h": [],
                "24h": []
            }
        )

        hourly_stats = analyze_hourly_trend(
            item_trend_data.get("1h", [])
        )

        daily_stats = analyze_daily_trend(
            item_trend_data.get("24h", [])
        )

        row["Daily Trend"] = hourly_stats["daily_trend"]
        row["Weekly Trend"] = hourly_stats["weekly_trend"]
        row["Long Term Trend"] = daily_stats["long_term_trend"]

        row["Daily Change %"] = (
            round(hourly_stats["daily_change_percent"], 2)
            if hourly_stats["daily_change_percent"] is not None
            else None
        )

        row["Weekly Change %"] = (
            round(hourly_stats["weekly_change_percent"], 2)
            if hourly_stats["weekly_change_percent"] is not None
            else None
        )

        row["Long Term Change %"] = (
            round(daily_stats["long_term_change_percent"], 2)
            if daily_stats["long_term_change_percent"] is not None
            else None
        )

        row["Daily Volatility %"] = (
            round(hourly_stats["daily_volatility_percent"], 2)
            if hourly_stats["daily_volatility_percent"] is not None
            else None
        )

        row["Weekly Volatility %"] = (
            round(hourly_stats["weekly_volatility_percent"], 2)
            if hourly_stats["weekly_volatility_percent"] is not None
            else None
        )

        row["7D High"] = (
            int(hourly_stats["weekly_high"])
            if hourly_stats["weekly_high"] is not None
            else None
        )

        row["7D Low"] = (
            int(hourly_stats["weekly_low"])
            if hourly_stats["weekly_low"] is not None
            else None
        )

        row["Price Position 7D %"] = (
            round(hourly_stats["price_position_7d_percent"], 2)
            if hourly_stats["price_position_7d_percent"] is not None
            else None
        )

        row["Trend Confidence"] = hourly_stats["trend_confidence"]
        row["Trend Warning"] = build_trend_warning(hourly_stats, row)

        row["Quick Score"] = calculate_quick_score(
            row=row,
            hourly_stats=hourly_stats
        )

        row["Overnight Score"] = calculate_overnight_score(
            row=row,
            hourly_stats=hourly_stats
        )

    return rows
