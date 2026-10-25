"""Weekly Trip Fund state and projections, independent of Streamlit."""
from datetime import date, timedelta
import math

import bank
import planner


def validate(target, deadline, today=None, departure=None):
    if not math.isfinite(target) or target <= 0 or target != int(target):
        raise ValueError("Choose a positive whole-dollar savings target.")
    planner.validate_deadline(deadline, today=today, departure=departure)


def create(target, deadline, demo, today=None, departure=None):
    today = today or date.today()
    validate(target, deadline, today, departure)
    return {**bank.setup_accounts(demo=demo), "demo": demo, "target": target,
            "deadline": deadline, "next_due": today, "history": [], "pending": None}


def balances(fund):
    return (bank.get_balance(fund["checking_id"], demo=fund["demo"]),
            bank.get_balance(fund["fund_id"], demo=fund["demo"]))


def plan(fund, saved, today=None):
    today = today or date.today()
    due = max(today, fund["next_due"])
    remaining = max(0, fund["target"] - saved)
    if remaining == 0 or due > fund["deadline"]:
        return []
    amount = math.ceil(planner.weekly_amount(fund["target"], saved, fund["deadline"], due))
    rows = []
    while remaining > 0 and due <= fund["deadline"]:
        contribution = min(amount, remaining)
        saved += contribution
        remaining -= contribution
        rows.append({"Date": due, "Contribution ($)": contribution, "Projected fund ($)": saved})
        due += timedelta(days=7)
    return rows


def contribute(fund, today=None):
    today = today or date.today()
    if fund["pending"]:
        raise bank.BankError("A previous transfer needs reconciliation before another contribution.")
    if not fund["demo"] and today < fund["next_due"]:
        raise ValueError("This week's contribution is already complete.")
    checking, saved = balances(fund)
    rows = plan(fund, saved, today)
    if not rows:
        raise ValueError("The target is funded or the funding deadline has passed.")
    row = rows[0]
    amount = row["Contribution ($)"]
    if amount > checking:
        raise ValueError("Not enough money in checking for this week's contribution.")
    # Save intent BEFORE the two-request live operation. An uncertain result must never
    # expose a retry button that could debit checking twice.
    fund["pending"] = {"checking": checking, "saved": saved, "row": row}
    try:
        bank.transfer(fund["checking_id"], fund["fund_id"], amount, demo=fund["demo"])
    except ValueError:
        fund["pending"] = None  # adapter validation happens before writes
        raise
    except Exception:
        if fund["demo"]:
            fund["pending"] = None
        raise bank.BankError("The contribution could not be confirmed. Refresh balances before continuing.") from None
    _finish(fund)


def _finish(fund):
    row = fund["pending"]["row"]
    fund["history"].append({"Date": row["Date"], "Amount ($)": row["Contribution ($)"]})
    fund["next_due"] = row["Date"] + timedelta(days=7)
    fund["pending"] = None


def reconcile(fund):
    """Only release an uncertain transfer when both expected balances are observed."""
    checking, saved = balances(fund)
    pending = fund["pending"]
    if pending:
        amount = pending["row"]["Contribution ($)"]
        if (checking == pending["checking"] - amount and saved == pending["saved"] + amount):
            _finish(fund)
    return checking, saved
