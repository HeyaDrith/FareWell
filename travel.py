"""SerpApi client: flights and hotels.

Both functions return simple, normalized dicts so the UI never touches raw SerpApi JSON.
In demo mode (or if no key is set) they return cached data from demo_data/.
"""
import json
import os
from pathlib import Path

DEMO_DIR = Path(__file__).parent / "demo_data"


def _load_demo(name: str):
    return json.loads((DEMO_DIR / name).read_text())


def _client(params: dict) -> dict:
    from serpapi import GoogleSearch  # imported lazily so demo mode needs no key

    return GoogleSearch({**params, "api_key": os.environ["SERPAPI_KEY"]}).get_dict()


def search_flights(origin: str, dest: str, depart: str, ret: str, demo: bool = False) -> list[dict]:
    """origin/dest are airport codes (e.g. AUS, CUN); dates are YYYY-MM-DD.

    Returns [{"airline": str, "price": float, "duration_min": int}], cheapest first.
    """
    if demo or not os.getenv("SERPAPI_KEY"):
        return _load_demo("flights.json")

    data = _client({
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": dest,
        "outbound_date": depart,
        "return_date": ret,
        "currency": "USD",
    })
    flights = []
    for f in data.get("best_flights", []) + data.get("other_flights", []):
        legs = f.get("flights") or [{}]
        if "price" not in f:
            continue
        flights.append({
            "airline": legs[0].get("airline", "Unknown"),
            "price": float(f["price"]),
            "duration_min": int(f.get("total_duration", 0)),
        })
    return sorted(flights, key=lambda x: x["price"])


def search_hotels(query: str, check_in: str, check_out: str, demo: bool = False) -> list[dict]:
    """query is free text, e.g. "hotels in Cancun".

    Returns [{"name": str, "per_night": float, "total": float, "rating": float}], cheapest first.
    """
    if demo or not os.getenv("SERPAPI_KEY"):
        return _load_demo("hotels.json")

    data = _client({
        "engine": "google_hotels",
        "q": query,
        "check_in_date": check_in,
        "check_out_date": check_out,
        "adults": 1,
        "currency": "USD",
    })
    hotels = []
    for p in data.get("properties", []):
        per_night = p.get("rate_per_night", {}).get("extracted_lowest")
        total = p.get("total_rate", {}).get("extracted_lowest")
        if per_night is None:
            continue
        hotels.append({
            "name": p.get("name", "Unknown"),
            "per_night": float(per_night),
            "total": float(total if total is not None else per_night),
            "rating": float(p.get("overall_rating", 0) or 0),
        })
    return sorted(hotels, key=lambda x: x["total"])
