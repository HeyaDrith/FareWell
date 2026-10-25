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


def plan_after(fund, saved, amount, today=None):
    """The rest of the plan if this week's contribution is `amount` instead of the planned one:
    later weeks grow (or shrink) so the target is still reached by the deadline."""
    today = today or date.today()
    rows = plan(fund, saved, today)
    if not rows:
        return []
    return plan({**fund, "next_due": rows[0]["Date"] + timedelta(days=7)}, saved + amount, today)


def contribute(fund, today=None, amount=None):
    """Move this week's contribution: the planned amount, or `amount` (whole dollars) when the
    person chose to put in less or more this week.

    Demo funds have no limits, so a demo can simulate as many weeks as it likes: any amount,
    and deposits keep going (one simulated week each) after the goal or the deadline.
    """
    today = today or date.today()
    if fund["pending"]:
        raise bank.BankError("A previous transfer needs reconciliation before another contribution.")
    if not fund["demo"] and today < fund["next_due"]:
        raise ValueError("This week's contribution is already complete.")
    checking, saved = balances(fund)
    rows = plan(fund, saved, today)
    if amount is not None and (not math.isfinite(amount) or amount < 1 or amount != int(amount)):
        raise ValueError("Choose a whole-dollar amount of at least $1.")
    if rows:
        row = rows[0]
    elif fund["demo"] and amount is not None:  # an extra simulated week past the goal or deadline
        row = {"Date": max(today, fund["next_due"]), "Contribution ($)": 0, "Projected fund ($)": saved}
    else:
        raise ValueError("The target is funded or the funding deadline has passed.")
    if amount is not None:
        if not fund["demo"] and amount > fund["target"] - saved:
            raise ValueError(f"That's more than the ${fund['target'] - saved:,.0f} still to save.")
        row = {**row, "Contribution ($)": int(amount), "Projected fund ($)": saved + int(amount)}
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


DEMO_TOP_UP = 1000


def add_demo_money(fund, amount=DEMO_TOP_UP):
    """A simulated paycheck into demo checking, so a demo never runs out of money."""
    if not fund["demo"]:
        raise ValueError("Only demo funds can add simulated money.")
    bank.add_demo_money(fund["checking_id"], amount)


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
