def safe_number(value, default=0):
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_total_volume(data):
    if not isinstance(data, dict):
        return 0, 0, 0

    high_volume = int(data.get("highPriceVolume") or 0)
    low_volume = int(data.get("lowPriceVolume") or 0)

    return high_volume + low_volume, high_volume, low_volume


def midpoint(low, high):
    low = safe_number(low, None)
    high = safe_number(high, None)

    if low is None and high is None:
        return None

    if low is None or low <= 0:
        return high if high and high > 0 else None

    if high is None or high <= 0:
        return low if low > 0 else None

    return (low + high) / 2


def percent_change(base, current):
    base = safe_number(base, None)
    current = safe_number(current, None)

    if base is None or current is None or base <= 0:
        return None

    return ((current - base) / base) * 100


def rounded(value, digits=2):
    if value is None:
        return None

    return round(float(value), digits)


def market_momentum_label(change_percent):
    if change_percent is None:
        return "Unknown"

    if change_percent >= 8:
        return "Strong upward pressure"

    if change_percent >= 3:
        return "Upward pressure"

    if change_percent <= -8:
        return "Strong downward pressure"

    if change_percent <= -3:
        return "Downward pressure"

    return "Stable vs 24h"


def expected_window_volume_from_24h(volume_24h, window_name):
    volume_24h = safe_number(volume_24h, 0)

    if volume_24h <= 0:
        return None

    if window_name == "5m":
        return volume_24h / 288

    if window_name == "1h":
        return volume_24h / 24

    if window_name == "24h":
        return volume_24h

    return None


def build_market_context_warning(
    spread_24h_percent,
    window_vs_24h_percent,
    volume_vs_24h_percent,
):
    warnings = []

    if spread_24h_percent is not None and spread_24h_percent >= 6:
        warnings.append("wide 24h spread")

    if window_vs_24h_percent is not None:
        if window_vs_24h_percent >= 10:
            warnings.append("window price far above 24h average")
        elif window_vs_24h_percent <= -10:
            warnings.append("window price far below 24h average")

    if volume_vs_24h_percent is not None:
        if volume_vs_24h_percent <= -70:
            warnings.append("thin volume vs 24h baseline")
        elif volume_vs_24h_percent >= 300:
            warnings.append("unusual volume surge vs 24h baseline")

    if not warnings:
        return "OK"

    return "; ".join(warnings)


def build_24h_market_context(
    item_id,
    window_name,
    avg_low,
    avg_high,
    volume,
    daily_data,
):
    """
    Build long-window context from the OSRS Wiki /24h endpoint.

    These fields compare the current scan window against the daily average and
    expected daily-volume baseline. They are advisory signals, not predictions.
    """
    daily_point = (daily_data or {}).get(str(item_id))

    if not isinstance(daily_point, dict):
        return {
            "Avg Low 24h": None,
            "Avg High 24h": None,
            "Volume 24h": None,
            "High Volume 24h": None,
            "Low Volume 24h": None,
            "Spread 24h": None,
            "Spread 24h %": None,
            "Window vs 24h %": None,
            "Volume vs 24h %": None,
            "Market Momentum": "Unknown",
            "Market Context Warning": "24h data unavailable",
        }

    avg_low_24h = daily_point.get("avgLowPrice")
    avg_high_24h = daily_point.get("avgHighPrice")
    volume_24h, high_volume_24h, low_volume_24h = get_total_volume(daily_point)

    current_mid = midpoint(avg_low, avg_high)
    daily_mid = midpoint(avg_low_24h, avg_high_24h)
    spread_24h = None
    spread_24h_percent = None

    if avg_low_24h is not None and avg_high_24h is not None:
        spread_24h = max(0, int(avg_high_24h) - int(avg_low_24h))
        if daily_mid and daily_mid > 0:
            spread_24h_percent = (spread_24h / daily_mid) * 100

    window_vs_24h_percent = percent_change(daily_mid, current_mid)

    expected_volume = expected_window_volume_from_24h(
        volume_24h=volume_24h,
        window_name=window_name,
    )
    volume_vs_24h_percent = percent_change(expected_volume, volume)

    warning = build_market_context_warning(
        spread_24h_percent=spread_24h_percent,
        window_vs_24h_percent=window_vs_24h_percent,
        volume_vs_24h_percent=volume_vs_24h_percent,
    )

    return {
        "Avg Low 24h": avg_low_24h,
        "Avg High 24h": avg_high_24h,
        "Volume 24h": volume_24h,
        "High Volume 24h": high_volume_24h,
        "Low Volume 24h": low_volume_24h,
        "Spread 24h": spread_24h,
        "Spread 24h %": rounded(spread_24h_percent),
        "Window vs 24h %": rounded(window_vs_24h_percent),
        "Volume vs 24h %": rounded(volume_vs_24h_percent),
        "Market Momentum": market_momentum_label(window_vs_24h_percent),
        "Market Context Warning": warning,
    }
