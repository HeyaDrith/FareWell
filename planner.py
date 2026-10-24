"""Savings-plan logic. Pure functions, no API calls, easy to test."""
import math
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP


def weeks_until(deadline: date, today: date | None = None) -> int:
    """Whole weeks from today to the deadline (minimum 1)."""
    today = today or date.today()
    days = (deadline - today).days
    return max(1, math.ceil(days / 7))


def weekly_amount(target: float, saved: float, deadline: date, today: date | None = None) -> float:
    """Return a dollar amount rounded up to cents so the plan covers its target.

    Keep the float interface used by the UI and bank client. Normalize the
    remaining balance to cents before division to avoid floating-point noise.
    Recalculate after contributions so the final payment covers only the gap.
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
