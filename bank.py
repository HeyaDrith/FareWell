"""Nessie (Capital One hackathon API) client.

Two features share this module:
  * Trip budget tracker (used by the website): create_trip, record_pick, remove_pick,
    list_picks, get_summary. The user's typed budget becomes a "Trip Budget" account; every
    option they pick is a purchase on it, and money saved vs. the typical price is a deposit
    into a "Trip Savings" account.
  * Trip Fund savings (kept for a future "save for it" step): setup_accounts, get_balance,
    transfer.

Nessie is a sandbox: accounts and money are fake. Docs: https://nessieisreal.com
In demo mode (or with no key) everything runs against an in-memory fake so the app still works.

Live sandbox behavior (verified 2026-10-24): purchases, deposits and withdrawals need a
"status" field; amounts are kept as whole dollars only; account balances are never updated;
purchases cannot be deleted.
"""
import math
import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from threading import RLock
from uuid import uuid4

import requests

BASE = "https://prod-api.nessieisreal.com"

# In-memory stand-in for demo mode.
_DEMO: dict[str, dict[str, float]] = {}
_DEMO_LOCK = RLock()


class BankError(RuntimeError):
    """A safe message for a bank operation that could not be confirmed."""


def _demo_account(account_id: str) -> tuple[dict, str]:
    group, _, kind = account_id.rpartition("-")
    if group not in _DEMO or kind not in ("checking", "fund"):
        raise ValueError("This demo account is unavailable. Create a new Trip Fund.")
    return _DEMO[group], kind


def _amount(amount: float) -> Decimal:
    try:
        value = Decimal(str(amount))
        if not value.is_finite() or value <= 0 or value != value.quantize(Decimal("0.01")):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValueError("Choose a positive transfer amount with at most two decimal places.") from None
    return value


def _key() -> str:
    return os.environ["NESSIE_API_KEY"]


def _use_demo(demo: bool) -> bool:
    return demo or not os.getenv("NESSIE_API_KEY")


def _post(path: str, body: dict) -> dict:
    return _request("POST", path, body)


def _get(path: str) -> dict:
    return _request("GET", path)


def _request(method: str, path: str, body: dict | None = None) -> dict:
    # Never follow a redirect with a query-string credential or fall back to HTTP.
    try:
        r = requests.request(method, f"{BASE}{path}", params={"key": _key()},
                             json=body, timeout=15, allow_redirects=False)
        if not 200 <= r.status_code < 300:
            raise BankError("Nessie could not confirm the request. Check the service and your credentials.")
        result = r.json()
        if not isinstance(result, (dict, list)):
            raise BankError("Nessie returned an unexpected response.")
        return result
    except (requests.RequestException, ValueError):
        raise BankError("Nessie could not confirm the request. Check the service and your credentials.") from None


def setup_accounts(demo: bool = False) -> dict:
    """Create a customer plus a checking account and an empty Trip Fund.

    Returns {"checking_id", "fund_id"}; demo IDs belong to an isolated account pair.
    """
    if _use_demo(demo):
        group = f"demo-{uuid4().hex}"
        with _DEMO_LOCK:
            _DEMO[group] = {"checking": 3000.0, "fund": 0.0}
        return {"checking_id": f"{group}-checking", "fund_id": f"{group}-fund"}

    customer = _post("/customers", {
        "first_name": "Trip", "last_name": "Saver",
        "address": {"street_number": "1", "street_name": "Congress Ave",
                    "city": "Austin", "state": "TX", "zip": "78701"},
    })["objectCreated"]
    cid = customer["_id"]
    checking = _post(f"/customers/{cid}/accounts", {
        "type": "Checking", "nickname": "Everyday", "rewards": 0, "balance": 3000,
    })["objectCreated"]
    fund = _post(f"/customers/{cid}/accounts", {
        "type": "Savings", "nickname": "Trip Fund", "rewards": 0, "balance": 0,
    })["objectCreated"]
    return {"checking_id": checking["_id"], "fund_id": fund["_id"]}


def get_balance(account_id: str, demo: bool = False) -> float:
    if _use_demo(demo):
        with _DEMO_LOCK:
            account, kind = _demo_account(account_id)
            return account[kind]
    if account_id.startswith("demo-"):
        raise ValueError("Demo accounts cannot be used with Nessie.")
    try:
        # The Nessie sandbox records deposits and withdrawals but never updates the
        # account's own balance, so add the completed records to the opening balance.
        value = float(_get(f"/accounts/{account_id}")["balance"])
        value += _completed_total(account_id, "deposits")
        value -= _completed_total(account_id, "withdrawals")
        if not Decimal(str(value)).is_finite() or value < 0:
            raise ValueError
        return value
    except (KeyError, TypeError, ValueError):
        raise BankError("Nessie returned an invalid account balance.") from None


def _completed_total(account_id: str, kind: str) -> float:
    records = _get(f"/accounts/{account_id}/{kind}")
    if not isinstance(records, list):
        raise ValueError
    return sum(float(r["amount"]) for r in records if r.get("status") == "completed")


def transfer(from_id: str, to_id: str, amount: float, demo: bool = False) -> None:
    """Move a positive cent amount; reject insufficient funds before submitting.

    Live submission does not imply settlement. Callers must not blindly retry an
    uncertain request. Nessie remains responsible for concurrent live balances.
    """
    value = _amount(amount)
    if from_id == to_id:
        raise ValueError("Choose two different accounts.")
    if _use_demo(demo):
        with _DEMO_LOCK:
            source, source_kind = _demo_account(from_id)
            destination, destination_kind = _demo_account(to_id)
            if source is not destination or source_kind != "checking" or destination_kind != "fund":
                raise ValueError("Transfer from checking to its matching Trip Fund.")
            if value > Decimal(str(source[source_kind])):
                raise ValueError("Not enough money in checking for this contribution.")
            source[source_kind] = float(Decimal(str(source[source_kind])) - value)
            destination[destination_kind] = float(Decimal(str(destination[destination_kind])) + value)
        return
    if from_id.startswith("demo-") or to_id.startswith("demo-"):
        raise ValueError("Demo accounts cannot be used with Nessie.")
    if value > Decimal(str(get_balance(from_id, demo))):
        raise ValueError("Not enough money in checking for this contribution.")
    if value != value.to_integral_value():
        raise ValueError("Nessie contributions must be whole dollars.")
    # Nessie's transfer endpoint has no destination field, so record the move as a
    # withdrawal from checking plus a matching deposit into the Trip Fund.
    record = {
        "medium": "balance",
        "status": "completed",
        "amount": int(value),
        "transaction_date": date.today().isoformat(),
        "description": "Weekly Trip Fund deposit",
    }
    _post(f"/accounts/{from_id}/withdrawals", record)
    _post(f"/accounts/{to_id}/deposits", record)


# ===================== Trip budget tracker =====================

CATEGORIES = ("Flight", "Hotel", "Food", "Activity", "Other")
_ADDRESS = {"street_number": "1", "street_name": "Congress Ave",
            "city": "Austin", "state": "TX", "zip": "78701"}

# Demo-mode trips: budget account id -> {"picks": [pick, ...]}
_TRIPS: dict[str, dict] = {}
# Nessie purchases must name a merchant; one per category, created once and reused.
_MERCHANTS: dict[str, str] = {}
# Savings deposits are tagged with their purchase: "[for:<purchase id>] Saved on ...".
_TAG = re.compile(r"^\[for:([^\]]+)\]\s*")


def create_trip(budget: float, demo: bool = False) -> dict:
    """Open the Trip Budget and Trip Savings accounts for a typed budget.

    Returns a trip dict to keep in st.session_state:
    {"budget", "budget_id", "savings_id", "demo", "removed": [pick ids]}
    """
    budget = float(_whole_dollars(budget, "Enter a trip budget above $0."))
    if _use_demo(demo):
        budget_id = f"demo-trip-{uuid4().hex}"
        with _DEMO_LOCK:
            _TRIPS[budget_id] = {"picks": []}
        return {"budget": budget, "budget_id": budget_id, "savings_id": f"{budget_id}-sav",
                "demo": True, "removed": []}

    customer = _post("/customers", {"first_name": "Trip", "last_name": "Saver",
                                    "address": _ADDRESS})["objectCreated"]
    accounts = f"/customers/{customer['_id']}/accounts"
    budget_acct = _post(accounts, {"type": "Checking", "nickname": "Trip Budget",
                                   "rewards": 0, "balance": int(budget)})["objectCreated"]
    savings_acct = _post(accounts, {"type": "Savings", "nickname": "Trip Savings",
                                    "rewards": 0, "balance": 0})["objectCreated"]
    return {"budget": budget, "budget_id": budget_acct["_id"], "savings_id": savings_acct["_id"],
            "demo": False, "removed": []}


def record_pick(trip: dict, category: str, description: str, amount: float,
                saved: float = 0.0) -> dict:
    """Record a chosen option as a purchase and deposit what it saved into Trip Savings.

    Nessie keeps whole dollars only, so the cost rounds UP and the savings round DOWN
    (the budget is never understated). Returns
    {"id", "category", "description", "amount", "saved", "date"}.
    """
    cost = _whole_dollars(amount, "Choose a cost above $0.")
    saved_dollars = _saved_dollars(saved)
    category = category if category in CATEGORIES else "Other"
    description = (description or category).strip()[:80] or category
    today = date.today().isoformat()

    if trip["demo"]:
        pick = {"id": f"demo-p-{uuid4().hex[:12]}", "category": category, "description": description,
                "amount": float(cost), "saved": float(saved_dollars), "date": today}
        with _DEMO_LOCK:
            _demo_trip(trip)["picks"].append(pick)
        return pick
    _require_live(trip)

    purchase = _post(f"/accounts/{trip['budget_id']}/purchases", {
        "merchant_id": _merchant_id(category),
        "medium": "balance",
        "purchase_date": today,
        "amount": cost,
        "status": "completed",
        "description": f"[{category}] {description}",  # purchases have no category field
    })["objectCreated"]
    pick = _normalize_purchase(purchase)
    if saved_dollars:
        try:
            _post(f"/accounts/{trip['savings_id']}/deposits", {
                "medium": "balance",
                "transaction_date": today,
                "amount": saved_dollars,
                "status": "completed",
                "description": f"[for:{pick['id']}] Saved on {description}"[:120],
            })
        except BankError:
            # Nessie can't delete the purchase, so hide it from the totals instead.
            trip.setdefault("removed", []).append(pick["id"])
            raise BankError("Couldn't record the savings for this pick, so it wasn't added. "
                            "Try again.") from None
    pick["saved"] = float(saved_dollars)
    return pick


def remove_pick(trip: dict, pick_id: str) -> None:
    """Undo a pick (e.g. switching hotels); its cost and savings leave the totals.

    Live Nessie can't delete purchases, so the trip dict remembers removed picks.
    """
    if trip["demo"]:
        with _DEMO_LOCK:
            t = _demo_trip(trip)
            t["picks"] = [p for p in t["picks"] if p["id"] != pick_id]
        return
    removed = trip.setdefault("removed", [])
    if pick_id not in removed:
        removed.append(pick_id)


def list_picks(trip: dict) -> list[dict]:
    """Every pick still in the trip, in the order it was picked, with what it saved."""
    if trip["demo"]:
        with _DEMO_LOCK:
            return [dict(p) for p in _demo_trip(trip)["picks"]]
    _require_live(trip)
    removed = set(trip.get("removed", []))
    raw = _get(f"/accounts/{trip['budget_id']}/purchases")
    if not isinstance(raw, list):
        raise BankError("Nessie returned an unexpected response.")
    picks = [_normalize_purchase(p) for p in raw
             if p.get("status") != "cancelled" and p.get("_id") not in removed]
    saved_by_pick: dict[str, float] = {}
    for dep in _trip_deposits(trip):
        saved_by_pick[dep["for"]] = saved_by_pick.get(dep["for"], 0.0) + dep["amount"]
    for p in picks:
        p["saved"] = saved_by_pick.get(p["id"], 0.0)
    picks.reverse()  # Nessie lists newest first
    return picks


def get_summary(trip: dict) -> dict:
    """{"budget", "spent", "saved", "remaining", "final_total", "over_budget", "picks"}.

    Totals come from the purchase and deposit records, because the sandbox never updates
    account balances.
    """
    picks = list_picks(trip)
    spent = round(sum(p["amount"] for p in picks), 2)
    saved = round(sum(p["saved"] for p in picks), 2)
    remaining = round(trip["budget"] - spent, 2)
    return {"budget": trip["budget"], "spent": spent, "saved": saved, "remaining": remaining,
            "final_total": spent, "over_budget": remaining < 0, "picks": picks}


def _whole_dollars(amount, message: str) -> int:
    try:
        value = float(amount)
    except (TypeError, ValueError):
        raise ValueError(message) from None
    dollars = int(math.ceil(round(value, 2))) if math.isfinite(value) else 0
    if dollars <= 0:
        raise ValueError(message)
    return dollars


def _saved_dollars(saved) -> int:
    try:
        value = float(saved or 0)
    except (TypeError, ValueError):
        return 0
    return int(math.floor(value)) if math.isfinite(value) and value > 0 else 0


def _require_live(trip: dict) -> None:
    if str(trip.get("budget_id", "")).startswith("demo-"):
        raise ValueError("Demo trips cannot be used with Nessie. Start a new trip.")


def _demo_trip(trip: dict) -> dict:
    if trip["budget_id"] not in _TRIPS:
        raise ValueError("This demo trip is unavailable. Start a new trip.")
    return _TRIPS[trip["budget_id"]]


def _merchant_id(category: str) -> str:
    if category not in _MERCHANTS:
        created = _post("/merchants", {"name": f"Trip Saver {category}", "category": category,
                                       "address": _ADDRESS,
                                       "geocode": {"lat": 30.2672, "lng": -97.7431}})["objectCreated"]
        _MERCHANTS[category] = created["_id"]
    return _MERCHANTS[category]


def _trip_deposits(trip: dict) -> list[dict]:
    raw = _get(f"/accounts/{trip['savings_id']}/deposits")
    if not isinstance(raw, list):
        raise BankError("Nessie returned an unexpected response.")
    out = []
    for d in raw:
        m = _TAG.match(d.get("description", ""))
        if m and d.get("status") != "cancelled":
            out.append({"for": m.group(1), "amount": float(d.get("amount", 0))})
    return out


def _normalize_purchase(p: dict) -> dict:
    desc = p.get("description", "")
    category = "Other"
    if desc.startswith("[") and "]" in desc:
        tag, desc = desc[1:].split("]", 1)
        category = tag if tag in CATEGORIES else "Other"
    return {"id": p.get("_id", ""), "category": category, "description": desc.strip(),
            "amount": float(p.get("amount", 0)), "saved": 0.0, "date": p.get("purchase_date", "")}
