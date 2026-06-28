# =========================
# SCANNER SETTINGS
# =========================

GE_TAX_RATE = 0.02
GE_TAX_CAP = 5_000_000
GE_TAX_MIN_PRICE = 100

MAX_ROI_PERCENT = 25
MIN_PROFIT_PER_ITEM = 1

# Warn when latest target prices are far away from window averages.
PRICE_DIVERGENCE_WARNING_PERCENT = 5

from market_features import build_24h_market_context


def parse_gp(value):
    """
    Supports:
    1000000
    1,000,000
    1_000_000
    1m
    1.5m
    500k
    2b
    """
    value = value.lower().replace(",", "").replace("_", "").strip()

    if value.endswith("k"):
        return int(float(value[:-1]) * 1_000)

    if value.endswith("m"):
        return int(float(value[:-1]) * 1_000_000)

    if value.endswith("b"):
        return int(float(value[:-1]) * 1_000_000_000)

    return int(value)


def format_gp(value):
    if value is None:
        return "N/A"

    return f"{int(value):,}"


def ge_tax(sell_price):
    if sell_price < GE_TAX_MIN_PRICE:
        return 0

    return min(int(sell_price * GE_TAX_RATE), GE_TAX_CAP)


def confidence_from_volume(volume, window):
    if window == "5m":
        if volume >= 1000:
            return "High"
        elif volume >= 100:
            return "Medium"
        else:
            return "Low"

    if window == "1h":
        if volume >= 5000:
            return "High"
        elif volume >= 500:
            return "Medium"
        else:
            return "Low"

    return "Unknown"


def calculate_score(total_profit, roi, volume, utilization):
    volume_score = min(volume, 10_000)

    score = (
        total_profit * 0.60 +
        (roi * 10_000) * 0.25 +
        volume_score * 0.15
    )

    return score * max(utilization, 0.10)


def get_latest_prices(item_id, latest_data):
    """
    Gets latest live prices for an item.

    /latest fields:
    high = latest high price
    low = latest low price
    highTime = timestamp for high price
    lowTime = timestamp for low price
    """
    item_latest = latest_data.get(str(item_id))

    if not item_latest:
        return None

    latest_low = item_latest.get("low")
    latest_high = item_latest.get("high")
    latest_low_time = item_latest.get("lowTime")
    latest_high_time = item_latest.get("highTime")

    if latest_low is None or latest_high is None:
        return None

    if latest_low <= 0 or latest_high <= 0:
        return None

    return {
        "latest_low": latest_low,
        "latest_high": latest_high,
        "latest_low_time": latest_low_time,
        "latest_high_time": latest_high_time
    }


def get_total_volume(data):
    high_volume = data.get("highPriceVolume") or 0
    low_volume = data.get("lowPriceVolume") or 0
    total_volume = high_volume + low_volume

    return total_volume, high_volume, low_volume


def get_hourly_volume(item_id, hourly_data, fallback_volume=0):
    """
    Returns 1h volume for an item.

    For 5m scans, this compares suggested quantity to the 1h market.
    For 1h scans, this usually matches the current window volume.
    """
    if not hourly_data:
        return fallback_volume

    item_hourly = hourly_data.get(str(item_id))

    if not item_hourly:
        return fallback_volume

    hourly_total, _, _ = get_total_volume(item_hourly)

    return hourly_total


def calculate_liquidity_score(quantity, hourly_volume):
    """
    Compares suggested quantity to 1h volume.

    Higher score = easier expected fill.
    """
    if hourly_volume <= 0:
        return 0

    ratio = quantity / hourly_volume

    if ratio <= 0.05:
        return 100

    if ratio <= 0.10:
        return 90

    if ratio <= 0.25:
        return 75

    if ratio <= 0.50:
        return 55

    if ratio <= 1.00:
        return 35

    return 15


def liquidity_rating_from_score(score):
    if score >= 85:
        return "Excellent"

    if score >= 65:
        return "Good"

    if score >= 45:
        return "Moderate"

    if score >= 25:
        return "Thin"

    return "Poor"


def estimate_time_to_fill(quantity, hourly_volume):
    """
    Rough fill estimate based on recent 1h volume.

    Uses 50% of total hourly volume as a conservative side-volume estimate.
    This is not guaranteed. Actual fill depends on offer price, competition,
    active buyers/sellers, and market movement.
    """
    if hourly_volume <= 0:
        return None, "Unknown"

    estimated_side_volume_per_hour = max(hourly_volume * 0.50, 1)
    fill_hours = quantity / estimated_side_volume_per_hour

    if fill_hours < 0.10:
        return fill_hours, "< 6 min"

    if fill_hours < 0.25:
        return fill_hours, "6-15 min"

    if fill_hours < 0.50:
        return fill_hours, "15-30 min"

    if fill_hours < 1:
        return fill_hours, "30-60 min"

    if fill_hours < 2:
        return fill_hours, "1-2 hr"

    if fill_hours < 4:
        return fill_hours, "2-4 hr"

    return fill_hours, "4+ hr"


def percent_difference(current, average):
    if average is None or average == 0:
        return None

    return ((current - average) / average) * 100


def build_price_warning(target_buy, target_sell, avg_low, avg_high):
    """
    Flags when /latest prices differ sharply from 5m or 1h averages.

    This catches suspicious latest prices that may not be realistic fills.
    """
    warnings = []

    buy_diff = percent_difference(target_buy, avg_low)
    sell_diff = percent_difference(target_sell, avg_high)

    if buy_diff is not None and abs(buy_diff) >= PRICE_DIVERGENCE_WARNING_PERCENT:
        warnings.append(
            f"Target buy differs from avg low by {round(buy_diff, 2)}%"
        )

    if sell_diff is not None and abs(sell_diff) >= PRICE_DIVERGENCE_WARNING_PERCENT:
        warnings.append(
            f"Target sell differs from avg high by {round(sell_diff, 2)}%"
        )

    if not warnings:
        return "OK", buy_diff, sell_diff

    return "; ".join(warnings), buy_diff, sell_diff


def scan_market(
    price_data,
    item_lookup,
    window_name,
    min_volume,
    cash_stack,
    minimum_profit,
    latest_data=None,
    use_latest=True,
    hourly_data=None,
    daily_data=None
):
    results = []
    watchlist = []

    if latest_data is None:
        latest_data = {}

    if hourly_data is None:
        hourly_data = {}

    if daily_data is None:
        daily_data = {}

    for item_id_str, data in price_data.items():
        item_id = int(item_id_str)

        if item_id not in item_lookup:
            continue

        item = item_lookup[item_id]

        name = item.get("name", "Unknown Item")
        buy_limit = item.get("limit", 0)

        if not buy_limit:
            continue

        avg_low = data.get("avgLowPrice")
        avg_high = data.get("avgHighPrice")

        volume, high_volume, low_volume = get_total_volume(data)

        if avg_low is None or avg_high is None:
            continue

        if avg_low <= 0 or avg_high <= 0:
            continue

        if volume < min_volume:
            continue

        latest_prices = get_latest_prices(item_id, latest_data)

        if use_latest and latest_prices:
            target_buy = latest_prices["latest_low"]
            target_sell = latest_prices["latest_high"]
            price_source = "latest"
            latest_low_time = latest_prices["latest_low_time"]
            latest_high_time = latest_prices["latest_high_time"]
        else:
            target_buy = avg_low
            target_sell = avg_high
            price_source = window_name
            latest_low_time = None
            latest_high_time = None

        if target_buy <= 0 or target_sell <= 0:
            continue

        quantity = min(buy_limit, cash_stack // target_buy)

        if quantity < 1:
            continue

        hourly_volume = get_hourly_volume(
            item_id=item_id,
            hourly_data=hourly_data,
            fallback_volume=volume if window_name == "1h" else 0
        )

        liquidity_score = calculate_liquidity_score(
            quantity=quantity,
            hourly_volume=hourly_volume
        )

        liquidity_rating = liquidity_rating_from_score(liquidity_score)

        fill_hours, fill_time = estimate_time_to_fill(
            quantity=quantity,
            hourly_volume=hourly_volume
        )

        price_warning, buy_diff_avg_low, sell_diff_avg_high = build_price_warning(
            target_buy=target_buy,
            target_sell=target_sell,
            avg_low=avg_low,
            avg_high=avg_high
        )

        market_context = build_24h_market_context(
            item_id=item_id,
            window_name=window_name,
            avg_low=avg_low,
            avg_high=avg_high,
            volume=volume,
            daily_data=daily_data
        )

        tax = ge_tax(target_sell)
        raw_margin = target_sell - target_buy
        profit_per_item = raw_margin - tax

        roi = (profit_per_item / target_buy) * 100 if target_buy > 0 else 0
        raw_roi = (raw_margin / target_buy) * 100 if target_buy > 0 else 0

        total_cost = target_buy * quantity
        total_profit = profit_per_item * quantity

        confidence = confidence_from_volume(volume, window_name)
        utilization = total_cost / cash_stack if cash_stack > 0 else 0

        score = calculate_score(
            total_profit=total_profit,
            roi=roi,
            volume=volume,
            utilization=utilization
        )

        # Liquidity penalty:
        # Huge paper profits should rank lower if the quantity is unrealistic
        # compared to 1h volume.
        score = score * (0.50 + liquidity_score / 200)

        # Price divergence penalty:
        # If latest prices are far from window averages, reduce confidence.
        if price_warning != "OK":
            score *= 0.75

        market_context_warning = market_context.get("Market Context Warning", "OK")
        if market_context_warning != "OK":
            if "far above" in market_context_warning or "thin volume" in market_context_warning:
                score *= 0.90
            elif "wide 24h spread" in market_context_warning:
                score *= 0.95

        row = {
            "Item ID": item_id,
            "Item": name,
            "Window": window_name,
            "Price Source": price_source,

            "Target Buy": target_buy,
            "Target Sell": target_sell,

            "Avg Low": avg_low,
            "Avg High": avg_high,
            **market_context,

            "Latest Low Time": latest_low_time,
            "Latest High Time": latest_high_time,

            "Buy vs Avg Low %": (
                round(buy_diff_avg_low, 2)
                if buy_diff_avg_low is not None
                else None
            ),
            "Sell vs Avg High %": (
                round(sell_diff_avg_high, 2)
                if sell_diff_avg_high is not None
                else None
            ),
            "Price Warning": price_warning,

            "Qty": quantity,
            "Cost": total_cost,
            "Tax": tax,
            "Raw Margin": raw_margin,
            "Profit/Item": profit_per_item,
            "Total Profit": total_profit,
            "ROI %": round(roi, 2),
            "Raw ROI %": round(raw_roi, 2),

            "Volume": volume,
            "Hourly Volume": hourly_volume,
            "Liquidity Score": round(liquidity_score, 2),
            "Liquidity Rating": liquidity_rating,
            "Expected Fill Hours": (
                round(fill_hours, 2)
                if fill_hours is not None
                else None
            ),
            "Expected Fill Time": fill_time,

            "High Volume": high_volume,
            "Low Volume": low_volume,
            "Buy Limit": buy_limit,
            "Confidence": confidence,
            "Score": round(score, 2)
        }

        if (
            total_profit >= minimum_profit
            and profit_per_item >= MIN_PROFIT_PER_ITEM
            and roi <= MAX_ROI_PERCENT
        ):
            results.append(row)

        elif raw_margin > 0 and raw_roi <= MAX_ROI_PERCENT:
            watchlist.append(row)

    # Keep 5m and 1h rankings separate because this function is called once
    # for each window.
    results.sort(key=lambda x: x["Score"], reverse=True)
    watchlist.sort(key=lambda x: (x["Volume"], x["Raw ROI %"]), reverse=True)

    for index, row in enumerate(results, start=1):
        row["Window Rank"] = index

    for index, row in enumerate(watchlist, start=1):
        row["Window Rank"] = index

    return results, watchlist
