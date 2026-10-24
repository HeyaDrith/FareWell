"""Nessie (Capital One hackathon API) client for the Trip Fund.

Nessie is a sandbox: accounts and money are fake. Docs: https://nessieisreal.com
In demo mode (or with no key) everything runs against an in-memory fake so the app still works.
"""
import os
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
        if not isinstance(result, dict):
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
        value = float(_get(f"/accounts/{account_id}")["balance"])
        if not Decimal(str(value)).is_finite() or value < 0:
            raise ValueError
        return value
    except (KeyError, TypeError, ValueError):
        raise BankError("Nessie returned an invalid account balance.") from None


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
    _post(f"/accounts/{from_id}/transfers", {
        "medium": "balance",
        "payee_id": to_id,
        "amount": float(value),
        "transaction_date": date.today().isoformat(),
        "description": "Weekly Trip Fund deposit",
    })
