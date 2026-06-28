def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def safe_number(value, default=0):
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_warning(value):
    if value is None:
        return "OK"

    value = str(value).strip()

    if not value:
        return "OK"

    return value


def get_confidence_score(confidence):
    if confidence == "High":
        return 100

    if confidence == "Medium":
        return 65

    if confidence == "Low":
        return 30

    return 10


def get_signal_score(signal):
    if signal == "Strong margin spike":
        return 100

    if signal == "Above average":
        return 80

    if signal == "Normal":
        return 55

    if signal == "New / Not enough history":
        return 30

    if signal == "Below average":
        return 15

    if signal == "Watch only":
        return 5

    return 25


def get_history_score(hist_samples):
    """
    Heavier penalty for low sample counts.

    This makes the recommender trust items less until they have
    enough saved scanner history.
    """
    hist_samples = safe_number(hist_samples)

    if hist_samples >= 50:
        return 100

    if hist_samples >= 25:
        return 85

    if hist_samples >= 10:
        return 65

    if hist_samples >= 5:
        return 45

    if hist_samples >= 3:
        return 30

    if hist_samples >= 1:
        return 10

    return 0


def get_volume_score(volume):
    """
    Scores raw window volume.
    Liquidity Score handles suggested quantity vs 1h volume separately.
    """
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
    """
    Scores total potential profit.

    1,000,000+ profit gets max score.
    """
    total_profit = safe_number(total_profit)
    return clamp((total_profit / 1_000_000) * 100, 0, 100)


def get_roi_score(roi):
    """
    Scores ROI.

    5%+ ROI gets max score.
    """
    roi = safe_number(roi)
    return clamp((roi / 5) * 100, 0, 100)


def get_liquidity_score(row):
    return safe_number(row.get("Liquidity Score"), 0)


def has_price_warning(row):
    warning = normalize_warning(row.get("Price Warning", "OK"))
    return warning != "OK"


def has_margin_warning(row):
    warning = normalize_warning(row.get("Margin Warning", "OK"))
    return warning != "OK"


def has_market_context_warning(row):
    warning = normalize_warning(row.get("Market Context Warning", "OK"))
    return warning != "OK"


def get_risk_level(row):
    confidence = row.get("Confidence")
    hist_samples = safe_number(row.get("Hist Samples", 0))
    volume = safe_number(row.get("Volume", 0))
    hourly_volume = safe_number(row.get("Hourly Volume", 0))
    liquidity_score = get_liquidity_score(row)
    liquidity_rating = row.get("Liquidity Rating")
    signal = row.get("Signal")

    price_warning = has_price_warning(row)
    margin_warning = has_margin_warning(row)
    market_warning = has_market_context_warning(row)

    if price_warning:
        return "High"

    market_warning_text = normalize_warning(row.get("Market Context Warning", "OK")).lower()

    if (
        market_warning
        and market_warning_text not in (
            "24h data unavailable",
            "unusual volume surge vs 24h baseline",
        )
    ):
        return "High"

    if liquidity_rating in ("Poor", "Thin"):
        return "High"

    if hist_samples < 3:
        return "High"

    if (
        confidence == "High"
        and hist_samples >= 10
        and volume >= 1_000
        and hourly_volume >= 1_000
        and liquidity_score >= 65
        and not margin_warning
        and signal in ("Normal", "Above average", "Strong margin spike")
    ):
        return "Low"

    if (
        confidence in ("Medium", "High")
        and hist_samples >= 5
        and volume >= 250
        and liquidity_score >= 45
        and signal not in ("Below average", "Watch only")
    ):
        return "Medium"

    return "High"


def risk_allowed(risk_level, risk_profile):
    risk_profile = risk_profile.lower().strip()

    if risk_profile == "low":
        return risk_level == "Low"

    if risk_profile == "medium":
        return risk_level in ("Low", "Medium")

    if risk_profile == "high":
        return risk_level in ("Low", "Medium", "High")

    return risk_level in ("Low", "Medium")


def calculate_recommendation_score(row, risk_profile="medium"):
    total_profit = safe_number(row.get("Total Profit", 0))
    profit_per_item = safe_number(row.get("Profit/Item", 0))
    roi = safe_number(row.get("ROI %", 0))
    volume = safe_number(row.get("Volume", 0))
    confidence = row.get("Confidence")
    signal = row.get("Signal")
    hist_samples = safe_number(row.get("Hist Samples", 0))
    liquidity_score = get_liquidity_score(row)

    if total_profit <= 0 or profit_per_item <= 0 or roi <= 0:
        return 0

    profit_score = get_profit_score(total_profit)
    roi_score = get_roi_score(roi)
    volume_score = get_volume_score(volume)
    confidence_score = get_confidence_score(confidence)
    signal_score = get_signal_score(signal)
    history_score = get_history_score(hist_samples)
    liquidity_component = liquidity_score

    risk_profile = risk_profile.lower().strip()

    if risk_profile == "low":
        score = (
            profit_score * 0.15 +
            roi_score * 0.08 +
            volume_score * 0.15 +
            liquidity_component * 0.25 +
            confidence_score * 0.17 +
            signal_score * 0.08 +
            history_score * 0.12
        )

    elif risk_profile == "high":
        score = (
            profit_score * 0.30 +
            roi_score * 0.22 +
            volume_score * 0.08 +
            liquidity_component * 0.12 +
            confidence_score * 0.08 +
            signal_score * 0.15 +
            history_score * 0.05
        )

    else:
        score = (
            profit_score * 0.25 +
            roi_score * 0.15 +
            volume_score * 0.10 +
            liquidity_component * 0.20 +
            confidence_score * 0.10 +
            signal_score * 0.10 +
            history_score * 0.10
        )

    risk_level = get_risk_level(row)

    if not risk_allowed(risk_level, risk_profile):
        score *= 0.65

    if signal == "Below average":
        score *= 0.70

    if signal == "Watch only":
        score *= 0.50

    # Heavier history penalties.
    if hist_samples < 1:
        score *= 0.45
    elif hist_samples < 3:
        score *= 0.55
    elif hist_samples < 5:
        score *= 0.70
    elif hist_samples < 10:
        score *= 0.85

    # Liquidity penalties.
    if liquidity_score < 25:
        score *= 0.55
    elif liquidity_score < 35:
        score *= 0.65
    elif liquidity_score < 55:
        score *= 0.80

    # Warning penalties.
    if has_price_warning(row):
        score *= 0.75

    if has_margin_warning(row):
        score *= 0.80

    if has_market_context_warning(row):
        warning = normalize_warning(row.get("Market Context Warning", "OK")).lower()
        if "thin volume" in warning or "far above" in warning:
            score *= 0.85
        elif "wide 24h spread" in warning:
            score *= 0.92

    # Far-above-average margins can be real, but they are also often unstable.
    margin_delta_percent = row.get("Margin Delta %")

    if margin_delta_percent is not None:
        margin_delta_percent = safe_number(margin_delta_percent)

        if margin_delta_percent >= 150:
            score *= 0.70
        elif margin_delta_percent >= 100:
            score *= 0.85

    return round(score, 2)


def classify_recommendation(score, risk_level, risk_profile):
    allowed = risk_allowed(risk_level, risk_profile)

    if score >= 80 and allowed:
        return "Best"

    if score >= 65 and allowed:
        return "Good"

    if score >= 45:
        return "Watch"

    return "Avoid"


def get_flip_category(row):
    """
    Categorizes flips by practical use case.

    Quick Flip:
    - Better for active flipping while watching the GE.
    - Usually fast-fill items with good liquidity and no major warnings.

    Overnight Flip:
    - Better for slower flips you can leave in the GE.
    - Usually 1h-window opportunities or slower fills with acceptable liquidity.

    Watch / Test First:
    - Possible opportunity, but test with a small quantity first.

    Avoid:
    - Poor liquidity, suspicious latest pricing, bad signal, or too many warnings.
    """
    window = row.get("Window")
    signal = row.get("Signal")
    confidence = row.get("Confidence")
    hist_samples = safe_number(row.get("Hist Samples", 0))
    liquidity_score = get_liquidity_score(row)
    liquidity_rating = row.get("Liquidity Rating")
    expected_fill_hours = row.get("Expected Fill Hours")
    recommendation_score = safe_number(row.get("Recommendation Score", 0))
    risk_level = get_risk_level(row)

    price_warning = has_price_warning(row)
    margin_warning = has_margin_warning(row)
    market_warning = has_market_context_warning(row)

    if expected_fill_hours is None:
        expected_fill_hours = 999
    else:
        expected_fill_hours = safe_number(expected_fill_hours, 999)

    if recommendation_score <= 0:
        return (
            "Avoid",
            "Not tax-profitable or has invalid profit/ROI data."
        )

    if signal in ("Below average", "Watch only"):
        return (
            "Avoid",
            "Historical signal is weak or below average."
        )

    if liquidity_rating == "Poor":
        return (
            "Avoid",
            "Poor liquidity compared to suggested quantity."
        )

    if price_warning and liquidity_score < 45:
        return (
            "Avoid",
            "Latest target price differs from the average and liquidity is weak."
        )

    if price_warning:
        return (
            "Watch / Test First",
            "Latest target price differs sharply from the average. Test with a small offer first."
        )

    market_warning_text = normalize_warning(row.get("Market Context Warning", "OK")).lower()

    if market_warning and market_warning_text not in ("24h data unavailable",):
        return (
            "Watch / Test First",
            "Daily market context is unusual. Test with a small offer first."
        )

    if margin_warning and hist_samples < 5:
        return (
            "Watch / Test First",
            "Large margin spike with limited history. Test with a small quantity before committing."
        )

    if liquidity_rating == "Thin":
        return (
            "Watch / Test First",
            "Thin liquidity means the full suggested quantity may be slow to fill."
        )

    if hist_samples < 3:
        return (
            "Watch / Test First",
            "Very limited saved history. Confirm with a small test buy/sell."
        )

    if (
        window == "5m"
        and expected_fill_hours <= 0.50
        and liquidity_score >= 65
        and risk_level in ("Low", "Medium")
        and confidence in ("Medium", "High")
    ):
        return (
            "Quick Flip",
            "Fast 5m opportunity with good liquidity and short estimated fill time."
        )

    if (
        expected_fill_hours <= 1.00
        and liquidity_score >= 55
        and risk_level in ("Low", "Medium")
        and confidence in ("Medium", "High")
    ):
        return (
            "Quick Flip",
            "Short expected fill time with acceptable liquidity for active flipping."
        )

    if (
        window == "1h"
        and liquidity_score >= 35
        and expected_fill_hours <= 12
        and signal not in ("Below average", "Watch only")
    ):
        return (
            "Overnight Flip",
            "Slower 1h opportunity that is better suited for leaving offers in the GE."
        )

    if (
        expected_fill_hours > 1
        and expected_fill_hours <= 12
        and liquidity_score >= 25
        and signal not in ("Below average", "Watch only")
    ):
        return (
            "Overnight Flip",
            "Slower expected fill, but still reasonable for overnight offers."
        )

    if (
        expected_fill_hours > 12
        or liquidity_score < 25
        or risk_level == "High"
    ):
        return (
            "Watch / Test First",
            "Slow fill, weaker liquidity, or elevated risk. Use a small test quantity first."
        )

    return (
        "Watch / Test First",
        "Does not clearly fit quick or overnight criteria. Test before committing."
    )


def build_reason(row):
    reasons = []

    signal = row.get("Signal")
    confidence = row.get("Confidence")
    hist_samples = safe_number(row.get("Hist Samples", 0))
    margin_delta_percent = row.get("Margin Delta %")
    total_profit = safe_number(row.get("Total Profit", 0))
    roi = safe_number(row.get("ROI %", 0))
    volume = safe_number(row.get("Volume", 0))

    hourly_volume = safe_number(row.get("Hourly Volume", 0))
    liquidity_score = safe_number(row.get("Liquidity Score", 0))
    liquidity_rating = row.get("Liquidity Rating")
    expected_fill_time = row.get("Expected Fill Time")

    price_warning = normalize_warning(row.get("Price Warning", "OK"))
    margin_warning = normalize_warning(row.get("Margin Warning", "OK"))
    market_context_warning = normalize_warning(row.get("Market Context Warning", "OK"))

    buy_vs_avg_low = row.get("Buy vs Avg Low %")
    sell_vs_avg_high = row.get("Sell vs Avg High %")

    if signal in ("Strong margin spike", "Above average"):
        reasons.append(f"{signal}")

    if margin_delta_percent is not None:
        reasons.append(f"margin {margin_delta_percent}% vs avg")

    if margin_warning != "OK":
        reasons.append("margin warning")

    if price_warning != "OK":
        reasons.append("latest price differs from average")

    if market_context_warning != "OK":
        reasons.append(f"market context: {market_context_warning}")

    if buy_vs_avg_low is not None:
        reasons.append(f"buy vs avg low {buy_vs_avg_low}%")

    if sell_vs_avg_high is not None:
        reasons.append(f"sell vs avg high {sell_vs_avg_high}%")

    if confidence in ("Medium", "High"):
        reasons.append(f"{confidence.lower()} confidence")

    if hist_samples >= 10:
        reasons.append(f"{int(hist_samples)} history samples")
    elif hist_samples >= 3:
        reasons.append(f"limited history: {int(hist_samples)} samples")
    else:
        reasons.append("very limited history")

    if liquidity_rating:
        reasons.append(f"{liquidity_rating.lower()} liquidity")

    if liquidity_score:
        reasons.append(f"liquidity score {liquidity_score}")

    if expected_fill_time:
        reasons.append(f"estimated fill {expected_fill_time}")

    if hourly_volume:
        reasons.append(f"1h volume {int(hourly_volume):,}")

    volume_24h = safe_number(row.get("Volume 24h"), 0)
    window_vs_24h = row.get("Window vs 24h %")
    volume_vs_24h = row.get("Volume vs 24h %")
    market_momentum = row.get("Market Momentum")

    if volume_24h:
        reasons.append(f"24h volume {int(volume_24h):,}")

    if window_vs_24h is not None:
        reasons.append(f"window vs 24h {window_vs_24h}%")

    if volume_vs_24h is not None:
        reasons.append(f"volume vs 24h baseline {volume_vs_24h}%")

    if market_momentum and market_momentum != "Unknown":
        reasons.append(str(market_momentum).lower())

    if volume >= 1000:
        reasons.append("strong window volume")

    if total_profit > 0:
        reasons.append(f"{int(total_profit):,} gp potential")

    if roi > 0:
        reasons.append(f"{roi}% ROI")

    return "; ".join(reasons)


def apply_recommendations(rows, risk_profile="medium"):
    for row in rows:
        risk_level = get_risk_level(row)
        recommendation_score = calculate_recommendation_score(
            row=row,
            risk_profile=risk_profile
        )
        recommendation = classify_recommendation(
            score=recommendation_score,
            risk_level=risk_level,
            risk_profile=risk_profile
        )

        row["Recommendation Score"] = recommendation_score
        row["Recommendation"] = recommendation
        row["Risk Level"] = risk_level
        row["Why"] = build_reason(row)

        flip_category, category_reason = get_flip_category(row)
        row["Flip Category"] = flip_category
        row["Category Reason"] = category_reason

    # This keeps 5m and 1h ranking separate because main.py and collector.py
    # call apply_recommendations separately for each scan window list.
    category_priority = {
        "Quick Flip": 4,
        "Overnight Flip": 3,
        "Watch / Test First": 2,
        "Avoid": 1
    }

    rows.sort(
        key=lambda x: (
            category_priority.get(x.get("Flip Category"), 0),
            x.get("Recommendation Score", 0),
            x.get("Liquidity Score", 0),
            x.get("Total Profit", 0),
            x.get("Volume", 0)
        ),
        reverse=True
    )

    # Refresh recommendation rank inside the current window.
    for index, row in enumerate(rows, start=1):
        row["Recommendation Rank"] = index

    return rows
