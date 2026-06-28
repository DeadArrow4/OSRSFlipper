import time
import requests


# =========================
# API SETTINGS
# =========================

HEADERS = {
    "User-Agent": "Mitchel-OSRS-Flip-Scanner/0.5 trend-analysis personal project"
}

BASE_URL = "https://prices.runescape.wiki/api/v1/osrs"
JAGEX_BASE_URL = "https://secure.runescape.com/m=itemdb_oldschool/api"

URL_LATEST = f"{BASE_URL}/latest"
URL_5M = f"{BASE_URL}/5m"
URL_1H = f"{BASE_URL}/1h"
URL_24H = f"{BASE_URL}/24h"
MAPPING_URL = f"{BASE_URL}/mapping"
TIMESERIES_URL = f"{BASE_URL}/timeseries"
JAGEX_DETAIL_URL = f"{JAGEX_BASE_URL}/catalogue/detail.json"
JAGEX_GRAPH_URL = f"{JAGEX_BASE_URL}/graph"

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


def load_market_data_with_24h():
    """
    Loads scanner data plus the rolling 24h market reference.

    Returns:
    latest_data, recent_data, older_data, daily_data, item_lookup
    """
    latest_data, recent_data, older_data, item_lookup = load_market_data()
    daily_data = load_24h_data()

    return latest_data, recent_data, older_data, daily_data, item_lookup


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
# OPTIONAL JAGEX CROSS-CHECK HELPERS
# =========================

def load_jagex_item_detail(item_id):
    """
    Loads official Jagex item detail for one item.

    This is intentionally not used in the normal collector loop. It is useful
    as a slower, official sanity check for top candidates.
    """
    params = {"item": int(item_id)}

    return get_json(JAGEX_DETAIL_URL, params=params).get("item", {})


def load_jagex_item_graph(item_id):
    """
    Loads official Jagex 180-day graph data for one item.

    The graph is coarser than Wiki prices and does not include high/low side
    volume, so it should supplement rather than replace the Wiki source.
    """
    url = f"{JAGEX_GRAPH_URL}/{int(item_id)}.json"

    return get_json(url)


def load_jagex_crosscheck(item_id):
    detail = load_jagex_item_detail(item_id)
    graph = load_jagex_item_graph(item_id)

    return {
        "item_id": int(item_id),
        "detail": detail,
        "graph": graph,
    }


def load_jagex_crosschecks_for_items(item_ids, max_items=10):
    """
    Loads official Jagex cross-check data for a small set of items.

    Keep this capped. Jagex endpoints are one item at a time and are not
    suitable for scanning the whole market every cycle.
    """
    checks = {}
    limited_item_ids = list(dict.fromkeys(item_ids))[:max_items]

    for index, item_id in enumerate(limited_item_ids, start=1):
        try:
            print(f"Jagex cross-check {index}/{len(limited_item_ids)}: item {item_id}")
            checks[item_id] = load_jagex_crosscheck(item_id)
            time.sleep(REQUEST_DELAY_SECONDS)
        except Exception as error:
            print(f"Could not load Jagex cross-check for item {item_id}: {error}")
            checks[item_id] = {"item_id": item_id, "error": str(error)}

    return checks


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
