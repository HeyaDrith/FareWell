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
