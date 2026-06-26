import time
import requests


# =========================
# API SETTINGS
# =========================

HEADERS = {
    "User-Agent": "Mitchel-OSRS-Flip-Scanner/0.5 trend-analysis personal project"
}

BASE_URL = "https://prices.runescape.wiki/api/v1/osrs"

URL_LATEST = f"{BASE_URL}/latest"
URL_5M = f"{BASE_URL}/5m"
URL_1H = f"{BASE_URL}/1h"
URL_24H = f"{BASE_URL}/24h"
MAPPING_URL = f"{BASE_URL}/mapping"
TIMESERIES_URL = f"{BASE_URL}/timeseries"

REQUEST_DELAY_SECONDS = 0.15


# =========================
# BASIC REQUEST HELPERS
# =========================

def get_json(url, params=None):
    response = requests.get(
        url,
        headers=HEADERS,
        params=params,
        timeout=30
    )

    response.raise_for_status()
    return response.json()


def load_market_data():
    """
    Loads the normal scanner data.

    This keeps the same return format your project already expects:
    latest_data, recent_data, older_data, item_lookup
    """
    print("\nLoading OSRS market data...")

    latest_data = get_json(URL_LATEST)["data"]
    recent_data = get_json(URL_5M)["data"]
    older_data = get_json(URL_1H)["data"]
    mapping_data = get_json(MAPPING_URL)

    item_lookup = {
        item["id"]: item
        for item in mapping_data
    }

    print("Market data loaded.")

    return latest_data, recent_data, older_data, item_lookup


def load_24h_data():
    """
    Loads rolling 24h average price data for all items.

    This is useful as a light daily-volume/daily-average reference.
    """
    print("Loading 24h market data...")

    data = get_json(URL_24H)["data"]

    print("24h market data loaded.")

    return data


# =========================
# TIMESERIES / TREND HELPERS
# =========================

def load_item_timeseries(item_id, timestep="1h"):
    """
    Loads historical timeseries data for one item.

    Common useful timesteps:
    - 5m
    - 1h
    - 6h
    - 24h

    Returns a list of data points.
    """
    params = {
        "id": item_id,
        "timestep": timestep
    }

    data = get_json(TIMESERIES_URL, params=params)

    return data.get("data", [])


def load_item_trend_data(item_id):
    """
    Loads the trend data we need for quick vs overnight scoring.

    1h data:
    - Good for recent intraday / weekly movement.
    - Useful for overnight logic.

    24h data:
    - Good for daily long-term direction.
    - Useful for slower overnight / multi-day stability.
    """
    one_hour_series = load_item_timeseries(
        item_id=item_id,
        timestep="1h"
    )

    time.sleep(REQUEST_DELAY_SECONDS)

    daily_series = load_item_timeseries(
        item_id=item_id,
        timestep="24h"
    )

    return {
        "1h": one_hour_series,
        "24h": daily_series
    }


def load_trend_data_for_items(item_ids, max_items=50):
    """
    Loads trend data for selected item IDs only.

    Important:
    Do not run timeseries requests for every item in the game.
    Only run this on your top scanner candidates.
    """
    trend_data = {}

    limited_item_ids = list(dict.fromkeys(item_ids))[:max_items]

    print(f"Loading trend data for {len(limited_item_ids)} items...")

    for index, item_id in enumerate(limited_item_ids, start=1):
        try:
            print(f"Trend data {index}/{len(limited_item_ids)}: item {item_id}")

            trend_data[item_id] = load_item_trend_data(item_id)

            time.sleep(REQUEST_DELAY_SECONDS)

        except Exception as error:
            print(f"Could not load trend data for item {item_id}: {error}")

            trend_data[item_id] = {
                "1h": [],
                "24h": []
            }

    print("Trend data loaded.")

    return trend_data