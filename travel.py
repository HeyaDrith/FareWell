"""SerpApi client: flights and hotels.

Both functions return simple, normalized dicts so the UI never touches raw SerpApi JSON.
In demo mode (or if no key is set) they return cached data from demo_data/.
"""
import json
import os
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

DEMO_DIR = Path(__file__).parent / "demo_data"


def _load_demo(name: str):
    return json.loads((DEMO_DIR / name).read_text())


def _client(params: dict) -> dict:
    from serpapi import GoogleSearch  # imported lazily so demo mode needs no key

    data = GoogleSearch({**params, "api_key": os.environ["SERPAPI_KEY"]}).get_dict()
    if not isinstance(data, dict) or data.get("error"):
        raise RuntimeError("The travel search service could not return prices.")
    return data


def _stay_nights(check_in: str, check_out: str) -> int:
    try:
        nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
    except (TypeError, ValueError):
        raise ValueError("Choose valid departure and return dates.") from None
    if nights <= 0:
        raise ValueError("Return must be after departure.")
    return nights


def _price(value) -> float | None:
    """Skip missing, nonfinite, zero, and negative quotes instead of funding them."""
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0:
            return None
        rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return float(rounded) if rounded > 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def search_flights(origin: str, dest: str, depart: str, ret: str, demo: bool = False) -> list[dict]:
    """origin/dest are airport codes (e.g. AUS, CUN); dates are YYYY-MM-DD.

    Returns [{"airline": str, "price": float, "duration_min": int}], cheapest first.
    """
    _stay_nights(depart, ret)
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
        price = _price(f.get("price"))
        if price is None:
            continue
        flights.append({
            "airline": legs[0].get("airline", "Unknown"),
            "price": price,
            "duration_min": int(f.get("total_duration", 0)),
        })
    return sorted(flights, key=lambda x: x["price"])


def search_hotels(query: str, check_in: str, check_out: str, demo: bool = False) -> list[dict]:
    """query is free text, e.g. "hotels in Cancun".

    Returns [{"name": str, "per_night": float, "total": float, "rating": float}], cheapest first.
    Live hotels without a complete stay total are omitted. Demo nightly rates are
    multiplied by the requested stay length; these are illustrative prices only.
    """
    nights = _stay_nights(check_in, check_out)
    if demo or not os.getenv("SERPAPI_KEY"):
        return [{**hotel, "total": round(hotel["per_night"] * nights, 2)}
                for hotel in _load_demo("hotels.json")]

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
        per_night = _price((p.get("rate_per_night") or {}).get("extracted_lowest"))
        total = _price((p.get("total_rate") or {}).get("extracted_lowest"))
        if per_night is None or total is None:
            continue
        hotels.append({
            "name": p.get("name", "Unknown"),
            "per_night": per_night,
            "total": total,
            "rating": float(p.get("overall_rating", 0) or 0),
        })
    return sorted(hotels, key=lambda x: x["total"])
