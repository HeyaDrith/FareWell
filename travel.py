"""SerpApi client: flights and hotels.

Both functions return simple, normalized dicts so the UI never touches raw SerpApi JSON.
In demo mode (or if no key is set) they return cached data from demo_data/.
"""
import base64
import json
import unicodedata
import math
import os
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlencode

DEMO_DIR = Path(__file__).parent / "demo_data"


def _load_demo(name: str):
    # UTF-8 explicitly: Windows defaults to cp1252, which can't read accented place names.
    return json.loads((DEMO_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _airports() -> dict:
    # IATA code -> [lat, lon, city]; large/medium airports from OurAirports (public domain).
    return _load_demo("airports.json")


def airport_codes() -> list[str]:
    """Every known IATA airport code, A-Z (for the searchable airport dropdowns)."""
    return sorted(_airports())


def airport_label(code: str) -> str:
    """Dropdown label like "CUN · Cancún (Cancun)" so typing a code, a city, or the city without
    accents all match. Unknown codes are shown as typed."""
    code = (code or "").strip().upper()
    found = _airports().get(code)
    city = str(found[2]) if found and len(found) > 2 and found[2] else ""
    if not city:
        return code
    plain = unicodedata.normalize("NFKD", city).encode("ascii", "ignore").decode()
    return f"{code} · {city}" + (f" ({plain})" if plain and plain != city else "")


def airport_city(code: str) -> str:
    """City name for an IATA code ("" if unknown)."""
    found = _airports().get((code or "").strip().upper())
    return str(found[2]) if found and len(found) > 2 and found[2] else ""


def airport_location(code: str) -> dict | None:
    """{"code", "lat", "lon", "city"} for an IATA airport code, or None if unknown."""
    code = str(code or "").strip().upper()
    found = _airports().get(code)
    if not found:
        return None
    lat, lon, city = found
    return {"code": code, "lat": lat, "lon": lon, "city": city}


def _coordinates(gps) -> tuple[float | None, float | None]:
    """(lat, lon) from SerpApi's gps_coordinates, or (None, None) if missing or invalid."""
    try:
        lat, lon = float(gps["latitude"]), float(gps["longitude"])
    except (KeyError, TypeError, ValueError):
        return None, None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return lat, lon


def flight_booking_url(airline: str, origin: str, dest: str, depart: str, ret: str,
                       flight_numbers: list[str] | None = None) -> str:
    """Google Flights results for this round trip, filtered to the picked flight's airline.

    SerpApi gives no plain booking URL for a flight (its booking step is a form post to Google),
    and Google Flights ignores free-text ?q= links. Its results pages take a "tfs" parameter:
    URL-safe base64 of a small protobuf (field numbers from the open-source fast-flights project).
    The app shows the flight number and time so the user can tap the matching listing.
    """
    code = (flight_numbers or [""])[0].split(" ")[0].upper()
    airlines = [code] if len(code) == 2 and code.isalnum() else []
    tfs = _flights_tfs([(depart, origin, dest), (ret, dest, origin)], airlines)
    return "https://www.google.com/travel/flights/search?" + urlencode({"tfs": tfs, "hl": "en", "curr": "USD"})


def _flights_tfs(legs: list[tuple[str, str, str]], airlines: list[str]) -> str:
    """Encode legs [(YYYY-MM-DD, from, to), ...] as Google Flights' tfs value (round trip,
    1 adult, economy)."""
    def varint(n: int) -> bytes:
        out = bytearray()
        while True:
            byte, n = n & 0x7F, n >> 7
            out.append(byte | (0x80 if n else 0))
            if not n:
                return bytes(out)

    def num(field: int, value: int) -> bytes:
        return varint(field << 3) + varint(value)

    def blob(field: int, data: bytes | str) -> bytes:
        data = data.encode() if isinstance(data, str) else data
        return varint(field << 3 | 2) + varint(len(data)) + data

    def airport(code: str) -> bytes:
        return num(1, 1) + blob(2, code.upper())

    body = num(1, 28) + num(2, 2)
    for day, frm, to in legs:
        leg = blob(2, day) + b"".join(blob(6, a) for a in airlines) + blob(13, airport(frm)) + blob(14, airport(to))
        body += blob(3, leg)
    body += num(8, 1) + num(9, 1) + num(19, 1)  # 1 adult, economy, round trip
    return base64.urlsafe_b64encode(body).decode().rstrip("=")


def hotel_booking_url(name: str, city: str, check_in: str, check_out: str,
                      property_token: str = "") -> str:
    """This hotel's own Google Hotels page (all booking sites + prices) when its ID is known;
    otherwise a Google Hotels search for the hotel name, city and dates."""
    if property_token:
        return "https://www.google.com/travel/hotels/entity/" + quote(property_token, safe="")
    query = f"{name} {city}".strip()
    return "https://www.google.com/travel/hotels?" + urlencode(
        {"q": query, "checkin": check_in, "checkout": check_out})


def _web_link(value) -> str:
    """Keep only http(s) links from the provider."""
    link = str(value or "").strip()
    return link if link.startswith(("https://", "http://")) else ""


def _image_link(value) -> str:
    """Keep only https image links from the provider (pictures load in the viewer's browser)."""
    link = str(value or "").strip()
    return link if link.startswith("https://") else ""


_PICTURE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")  # raster only, never SVG
MAX_PICTURE_BYTES = 1_500_000


@lru_cache(maxsize=256)
def picture_data(url: str) -> str:
    """The picture at an https link, downloaded by the server, as a data: URI ("" if it can't be used).

    Photo hosts (vacation rentals especially) often refuse images embedded on another site, so the
    browser showed a broken image. Fetching here avoids that and tells us when a picture is
    unusable, so the page can draw its stand-in instead.
    """
    if not _image_link(url):
        return ""
    import requests
    try:
        with requests.get(url, timeout=5, stream=True, headers={"User-Agent": "Mozilla/5.0 (FareWell trip planner)"}) as reply:
            kind = reply.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if reply.status_code != 200 or kind not in _PICTURE_TYPES:
                return ""
            body = b""
            for chunk in reply.iter_content(64 * 1024):
                body += chunk
                if len(body) > MAX_PICTURE_BYTES:
                    return ""
    except requests.RequestException:
        return ""
    return f"data:{kind};base64,{base64.b64encode(body).decode()}" if body else ""


def prefetch_pictures(urls: list[str]):
    """Download a page's pictures in parallel, so six slow hosts don't take six times as long."""
    from concurrent.futures import ThreadPoolExecutor
    wanted = list(dict.fromkeys(u for u in urls if _image_link(u)))
    if wanted:
        with ThreadPoolExecutor(max_workers=min(8, len(wanted))) as pool:
            list(pool.map(picture_data, wanted))


def _hotel_image(images) -> str:
    """The first usable photo from Google Hotels' images list ("" if none)."""
    for image in images if isinstance(images, list) else []:
        if isinstance(image, dict):
            link = _image_link(image.get("thumbnail") or image.get("original_image"))
            if link:
                return link
    return ""


def place_url(query: str) -> str:
    """Google Maps search for a restaurant or activity."""
    return "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": query.strip()})


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

    Returns [{"airline", "price", "duration_min", "stops", "flight_numbers", "departs", "route", "logo"}],
    cheapest first. flight_numbers (e.g. ["WN 1234"]) and departs (e.g. "2027-01-22 07:05")
    identify the exact listing; route is the outbound airports in order, layovers included
    (e.g. ["AUS", "MEX", "CUN"]); logo is the airline's logo image (https). All are empty for
    sample data that doesn't have them.
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
            "stops": max(0, len(legs) - 1),  # outbound legs; 0 = nonstop
            "flight_numbers": [leg["flight_number"] for leg in legs if leg.get("flight_number")],
            "departs": str((legs[0].get("departure_airport") or {}).get("time") or ""),
            "route": _route(legs),
            "logo": _image_link(f.get("airline_logo") or legs[0].get("airline_logo")),
        })
    return sorted(flights, key=lambda x: x["price"])


def _route(legs: list[dict]) -> list[str]:
    """Outbound airport codes in order: first departure, then every arrival."""
    stops = [(legs[0].get("departure_airport") or {}).get("id")]
    stops += [(leg.get("arrival_airport") or {}).get("id") for leg in legs]
    codes = [str(code).upper() for code in stops if code]
    return codes if len(codes) == len(stops) else []  # a gap would draw a wrong path


def search_hotels(query: str, check_in: str, check_out: str, demo: bool = False) -> list[dict]:
    """query is free text, e.g. "hotels in Cancun".

    Returns [{"name", "per_night", "total", "rating", "property_token", "website", "lat", "lon", "image"}],
    cheapest first. property_token is Google's ID for that exact hotel (its Google Hotels page
    lists every booking site); website is the hotel's own site; image is its first photo (https).
    All three are "" when not provided. lat/lon place the hotel on the map; None when not provided.
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
        lat, lon = _coordinates(p.get("gps_coordinates"))
        hotels.append({
            "name": p.get("name", "Unknown"),
            "per_night": per_night,
            "total": total,
            "rating": float(p.get("overall_rating", 0) or 0),
            "property_token": str(p.get("property_token") or ""),
            "website": _web_link(p.get("link")),
            "lat": lat,
            "lon": lon,
            "image": _hotel_image(p.get("images")),
        })
    return sorted(hotels, key=lambda x: x["total"])
