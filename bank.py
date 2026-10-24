"""Nessie (Capital One hackathon API) client for the Trip Fund.

Nessie is a sandbox: accounts and money are fake. Docs: http://api.nessieisreal.com
In demo mode (or with no key) everything runs against an in-memory fake so the app still works.
"""
import os
from datetime import date

import requests

BASE = "http://api.nessieisreal.com"

# In-memory stand-in for demo mode.
_DEMO = {"checking": 3000.0, "fund": 0.0}


def _key() -> str:
    return os.environ["NESSIE_API_KEY"]


def _use_demo(demo: bool) -> bool:
    return demo or not os.getenv("NESSIE_API_KEY")


def _post(path: str, body: dict) -> dict:
    r = requests.post(f"{BASE}{path}", params={"key": _key()}, json=body, timeout=15)
    r.raise_for_status()
    return r.json()


def _get(path: str) -> dict:
    r = requests.get(f"{BASE}{path}", params={"key": _key()}, timeout=15)
    r.raise_for_status()
    return r.json()


def setup_accounts(demo: bool = False) -> dict:
    """Create a customer plus a checking account and an empty Trip Fund.

    Returns {"checking_id", "fund_id"} (placeholder ids in demo mode).
    """
    if _use_demo(demo):
        _DEMO.update(checking=3000.0, fund=0.0)
        return {"checking_id": "demo-checking", "fund_id": "demo-fund"}

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
        return _DEMO["fund"] if "fund" in account_id else _DEMO["checking"]
    return float(_get(f"/accounts/{account_id}")["balance"])


def transfer(from_id: str, to_id: str, amount: float, demo: bool = False) -> None:
    """Move `amount` from checking into the Trip Fund."""
    if _use_demo(demo):
        _DEMO["checking"] -= amount
        _DEMO["fund"] += amount
        return
    _post(f"/accounts/{from_id}/transfers", {
        "medium": "balance",
        "payee_id": to_id,
        "amount": amount,
        "transaction_date": date.today().isoformat(),
        "description": "Weekly Trip Fund deposit",
    })
