"""Manual weekly funding in FareWell's shared beach-and-card theme."""
from datetime import date, timedelta
import math
import os

import streamlit as st

import accounts
import bank
import funding
import ui

ss = st.session_state
today = date.today()
demo = ss.get("demo_bank", True) or not os.getenv("NESSIE_API_KEY")
mode = "demo" if demo else "nessie"
funds = ss.setdefault("weekly_funds", {})
fund = funds.get(mode)

with st.container(key="hero-fund"):
    st.title("A little each week. A trip to remember.")
    st.html("<div class='ts-hero-sub'>Set your goal, build your Trip Fund, and get closer to takeoff.</div>")
st.caption("Demo money · each contribution advances the plan by one week." if demo else
           "Nessie sandbox · manual weekly contributions, no real money moves.")
st.caption("Trip Fund contributions are separate from the savings-versus-typical shown in your trip budget.")

trip_cost = None
departure = None
if ss.get("trip"):
    try:
        summary = bank.get_summary(ss.trip)
        trip_cost = summary["final_total"] if summary["picks"] else summary["budget"]
        departure = ss.details[3]
    except Exception:
        st.info("Your trip budget is unavailable. You can still set a savings target below.")

with st.container(key="card-fund-goal"):
    st.header("1. Set your savings goal")
    target_key, deadline_key = f"fund_target_{mode}", f"fund_deadline_{mode}"
    ss.setdefault(target_key, int(fund["target"] if fund else math.ceil(trip_cost or 1500)))
    ss.setdefault(deadline_key, fund["deadline"] if fund else max(today, (departure or today + timedelta(days=90)) - timedelta(days=7)))
    if trip_cost is not None:
        if st.button("Use current trip cost", disabled=bool(fund and fund["pending"])):
            ss[target_key] = int(math.ceil(trip_cost))
        st.caption(f"Current trip target: ${trip_cost:,.0f}. Import again after changing your picks.")
    a, b = st.columns(2)
    target = a.number_input("Savings target ($)", min_value=1, step=50, key=target_key)
    deadline = b.date_input("Have it saved by", key=deadline_key)
    error = None
    try:
        funding.validate(target, deadline, today, departure)
    except ValueError as exc:
        error = str(exc)
        st.warning(error)
    if departure:
        st.caption(f"Save by your departure on {departure:%b %d, %Y} or earlier.")
    if st.button("Update savings plan" if fund else "Create Trip Fund", type="primary",
                 disabled=bool(error or (fund and fund["pending"]))):
        try:
            if fund:
                fund.update(target=target, deadline=deadline)
            else:
                funds[mode] = funding.create(target, deadline, demo, today, departure)
            st.rerun()
        except (ValueError, bank.BankError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("The banking service could not create your fund. Please try again later.")

if not fund:
    st.info("Create your Trip Fund to see a weekly plan. Checking starts with $3,000 of simulated money.")
    ui.powered_by()
    st.stop()

if st.button("Refresh balances"):
    try:
        funding.reconcile(fund)
    except Exception:
        st.error("Balances could not be refreshed. Please try again later.")
try:
    checking, saved = funding.balances(fund)
except Exception:
    st.error("Balances are unavailable. Contributions are paused until the bank responds.")
    st.stop()

changed = (target, deadline) != (fund["target"], fund["deadline"])
rows = funding.plan(fund, saved, today)
remaining = max(0, fund["target"] - saved)
weekly = rows[0]["Contribution ($)"] if rows else 0
with st.container(key="card-fund-progress"):
    st.header("2. Grow your Trip Fund")
    a, b, c = st.columns(3)
    a.metric("Funded", ui.dollars(saved, cents=True))
    b.metric("Still to save", ui.dollars(remaining, cents=True))
    c.metric("Next contribution", ui.dollars(weekly, cents=True))
    st.progress(min(1.0, saved / fund["target"]))
    st.caption(f"Target \\${fund['target']:,.0f} · deadline {fund['deadline']:%b %d, %Y} · checking \\${checking:,.2f}")
    if changed:
        st.info("Your goal changed. Update the savings plan before contributing; your existing balance stays intact.")
    if remaining == 0:
        st.success("Your trip is fully funded! You're ready for the next adventure.")
    elif not rows and not demo:
        st.warning("No contribution dates remain. Update your deadline to continue saving.")
    # A demo can simulate as many weeks as it likes: no limit on amount, goal, deadline or money.
    extra = demo and not rows
    if extra:
        st.caption("Demo: the plan is finished, but you can keep depositing to simulate more weeks.")
    if remaining > checking:
        st.warning("Your checking balance won't cover the full remaining target. "
                   + ("Add demo money below." if demo else "Lower the goal or add funds in the sandbox."))
    if fund["pending"]:
        st.warning("A transfer has an uncertain result. Further contributions are paused. Refresh balances to check whether both sides completed. If it stays unresolved, reconcile the withdrawal and deposit in Nessie before continuing.")
    waiting = not demo and today < fund["next_due"]
    if waiting:
        st.info(f"This week's contribution is complete. Your next contribution is due {fund['next_due']:%b %d, %Y}.")
    st.caption("Contributions round up to whole dollars; the last contribution covers only what's left. "
               "You can change this week's amount below. Nothing runs automatically.")
    if demo and rows:
        st.caption(f"Next simulated contribution: {rows[0]['Date']:%b %d, %Y}.")
    amount = weekly
    if rows or extra:
        # Put in less when money is tight, or more to get ahead; the later weeks adjust. The key
        # follows the week and its planned amount, so the box resets to the plan after each transfer.
        week = rows[0]["Date"] if rows else fund["next_due"]
        amount = int(st.number_input("Amount this week ($)", min_value=1,
                                     max_value=None if demo else max(1, int(remaining)),
                                     value=int(min(weekly, remaining)) if rows else 50, step=5,
                                     key=f"fund_amount_{mode}_{week}_{weekly}",
                                     help=(f"The plan suggests \\${weekly:,.0f}. " if rows else "")
                                          + "Change it for this week only."))
        if rows and amount != weekly:
            later = funding.plan_after(fund, saved, amount, today)
            left_after = remaining - amount
            if left_after <= 0:
                st.caption("This contribution completes your goal."
                           + (" The extra stays in your Trip Fund." if left_after < 0 else ""))
            elif later:
                st.caption(f"Then about \\${later[0]['Contribution ($)']:,.0f}/week for {len(later)} more "
                           f"week{'s' * (len(later) != 1)} to reach your target by the deadline.")
            else:
                st.warning(f"No weeks remain before your deadline, so \\${left_after:,.0f} would still be "
                           "left to save. Contribute more or move your deadline.")
        if amount > checking:
            st.warning(f"Checking has \\${checking:,.2f}, less than \\${amount:,.0f}. "
                       + ("Add demo money below." if demo else "Choose a smaller amount."))
    custom = not rows or amount != weekly
    run, top_up = st.columns([1, 1])
    if run.button("Run this week's transfer", type="primary", disabled=bool(
            error or changed or not (rows or extra) or amount > checking or fund["pending"] or waiting)):
        try:
            funding.contribute(fund, today, amount=amount if custom else None)
        except (ValueError, bank.BankError) as exc:
            ss.fund_notice = str(exc).replace("$", "\\$")
        else:
            ss.fund_notice = (f"Contributed \\${amount:,.0f}. Your Trip Fund is growing!"
                              + (" The rest of your plan has adjusted." if rows and custom and amount < remaining else ""))
        st.rerun()
    if demo and top_up.button(f"💵 Add \\${funding.DEMO_TOP_UP:,} demo money to checking",
                              disabled=bool(fund["pending"])):
        try:
            funding.add_demo_money(fund)
        except (ValueError, bank.BankError) as exc:
            ss.fund_notice = str(exc).replace("$", "\\$")
        else:
            ss.fund_notice = f"Added \\${funding.DEMO_TOP_UP:,} of simulated money to checking."
        st.rerun()
    if notice := ss.pop("fund_notice", None):
        st.info(notice)

left, right = st.columns(2)
with left.container(key="card-fund-schedule"):
    st.subheader("Your weekly plan")
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.caption("No upcoming contributions.")
with right.container(key="card-fund-history"):
    st.subheader("Contribution history")
    if fund["history"]:
        st.dataframe(fund["history"][::-1], hide_index=True, width="stretch")
    else:
        st.caption("Your first contribution starts the story.")
if accounts.current_user():
    st.caption("Your Trip Funds and history are saved to your account, demo balances included. "
               "Demo and Nessie funds stay separate when switching data sources.")
else:
    st.caption("Funds and history belong to this browser session (sign in to keep them). Demo balances "
               "reset when the server restarts. Demo and Nessie funds stay separate when switching data sources.")
st.page_link("views/plan.py", label="Back to your trip", icon=":material/flight_takeoff:")
ui.powered_by()
