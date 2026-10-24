"""Savings-plan logic. Pure functions, no API calls, easy to test."""
import math
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP


def validate_deadline(deadline: date, today: date | None = None,
                      departure: date | None = None) -> None:
    """Raise ValueError for a missing, expired, or post-departure deadline.

    A deadline today is valid and requires the remaining contribution today.
    Departure is optional because the arithmetic helpers do not know the trip.
    """
    today = today or date.today()
    if not isinstance(deadline, date):
        raise ValueError("Choose a booking deadline.")
    if deadline < today:
        raise ValueError("Your booking deadline has passed. Choose today or a later date.")
    if departure is not None and deadline > departure:
        raise ValueError("Your booking deadline must be on or before your departure date.")


def weeks_until(deadline: date, today: date | None = None) -> int:
    """Saving periods until a valid deadline; a deadline today has one period."""
    today = today or date.today()
    validate_deadline(deadline, today=today)
    days = (deadline - today).days
    return max(1, math.ceil(days / 7))


def weekly_amount(target: float, saved: float, deadline: date, today: date | None = None) -> float:
    """Return a dollar amount rounded up to cents so the plan covers its target.

    Keep the float interface used by the UI and bank client. Normalize the
    remaining balance to cents before division to avoid floating-point noise.
    Recalculate after contributions so the final payment covers only the gap.
    Raises ValueError for an expired or missing deadline.
    """
    cent = Decimal("0.01")
    remaining = max(Decimal("0.00"), Decimal(str(target)) - Decimal(str(saved)))
    remaining = remaining.quantize(cent, rounding=ROUND_HALF_UP)
    weekly = remaining / weeks_until(deadline, today)
    return float(weekly.quantize(cent, rounding=ROUND_CEILING))


def price_trend(previous: float | None, current: float) -> str:
    """Human-readable price change vs. the last time we checked."""
    if not previous:
        return "First price check"
    change = (current - previous) / previous * 100
    if abs(change) < 1:
        return "Price unchanged"
    direction = "up" if change > 0 else "down"
    return f"Price is {direction} {abs(change):.1f}% since last check"


def trip_budget(flight_price: float, hotel_total: float, activities: float = 0.0) -> float:
    return round(flight_price + hotel_total + activities, 2)


def typical_price(prices: list[float]) -> float:
    """The median of the search results' prices, used as the "typical" option."""
    values = sorted(p for p in prices if p and p > 0)
    if not values:
        return 0.0
    mid = len(values) // 2
    return round(values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2, 2)


def savings_vs_typical(price: float, typical: float) -> float:
    """How much cheaper than typical an option is (0 if it costs the same or more)."""
    return round(max(0.0, typical - price), 2)


# ---------- Budget split and recommendations ----------

# Default share of the trip budget for each part of the trip.
BUDGET_SPLIT = {"Flight": 0.35, "Hotel": 0.40, "Food": 0.15, "Activity": 0.10}


def category_allowance(category: str, remaining: float, picked: set[str] | list[str] = ()) -> float:
    """How much of what's left to plan for `category`.

    Money left over in a part of the trip rolls into the parts not picked yet: the remaining
    budget is split by BUDGET_SPLIT among `category` and every category not in `picked`.
    """
    if category not in BUDGET_SPLIT or remaining <= 0:
        return 0.0
    pool = {c for c in BUDGET_SPLIT if c not in set(picked)} | {category}
    share = BUDGET_SPLIT[category] / sum(BUDGET_SPLIT[c] for c in pool)
    return round(remaining * share, 2)


def flight_quality(flight: dict, shortest_min: int) -> float:
    """0-5 score: shorter trips and fewer stops score higher."""
    duration = flight.get("duration_min") or 0
    speed = (shortest_min / duration) if duration and shortest_min else 0.5
    return round(max(0.0, min(5.0, 5 * speed - 0.75 * int(flight.get("stops") or 0))), 2)


def hotel_quality(hotel: dict) -> float:
    """0-5 score from the guest rating (missing ratings count as 0)."""
    try:
        return round(max(0.0, min(5.0, float(hotel.get("rating") or 0))), 2)
    except (TypeError, ValueError):
        return 0.0


def pick_options(prices: list[float], qualities: list[float], allowance: float) -> dict:
    """Indexes for the three highlighted options (None when there are no options).

    - "cheapest": lowest price.
    - "recommended": best quality that fits `allowance` (ties go to the cheaper option);
      if nothing fits, the cheapest.
    - "best_quality": best quality overall (ties go to the cheaper option).
    """
    if not prices:
        return {"recommended": None, "cheapest": None, "best_quality": None}
    idx = range(len(prices))
    cheapest = min(idx, key=lambda i: (prices[i], -qualities[i]))
    best = max(idx, key=lambda i: (qualities[i], -prices[i]))
    fitting = [i for i in idx if prices[i] <= allowance]
    recommended = max(fitting, key=lambda i: (qualities[i], -prices[i])) if fitting else cheapest
    return {"recommended": recommended, "cheapest": cheapest, "best_quality": best}


def trip_input_error(origin: str, dest: str, depart: date | None, ret: date | None,
                     today: date | None = None) -> str | None:
    """Why the trip form can't be planned yet, or None when airports and dates are usable."""
    today = today or date.today()
    if not origin or not dest:
        return "Choose where you're flying from and to."
    if not (len(origin) == 3 and origin.isalpha() and len(dest) == 3 and dest.isalpha()):
        return "Airports need a 3-letter code. Pick one from the list."
    if origin == dest:
        return "Choose two different airports."
    if depart is None:
        return "Choose a departure date."
    if ret is None:
        return "Choose a return date."
    if depart < today:
        return "Departure must be today or later."
    if ret <= depart:
        return "Return must be after departure."
    return None
