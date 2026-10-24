"""Savings-plan logic. Pure functions, no API calls, easy to test."""
import math
from datetime import date


def weeks_until(deadline: date, today: date | None = None) -> int:
    """Whole weeks from today to the deadline (minimum 1)."""
    today = today or date.today()
    days = (deadline - today).days
    return max(1, math.ceil(days / 7))


def weekly_amount(target: float, saved: float, deadline: date, today: date | None = None) -> float:
    """How much to move into the Trip Fund each week to hit `target` by `deadline`."""
    remaining = max(0.0, target - saved)
    return round(remaining / weeks_until(deadline, today), 2)


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
