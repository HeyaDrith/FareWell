"""Trip Saver: type a budget and destination, pick the options that fit, and see the savings.

Run:  streamlit run app.py
"""
import os
from datetime import date, timedelta

import streamlit as st
from dotenv import load_dotenv

import bank
import planner
import travel

load_dotenv()
# On Streamlit Community Cloud, keys live in st.secrets instead of .env.
try:
    for k in ("SERPAPI_KEY", "NESSIE_API_KEY"):
        if k in st.secrets:
            os.environ.setdefault(k, st.secrets[k])
except Exception:
    pass

st.set_page_config(page_title="Trip Saver", page_icon="✈️")
st.title("✈️ Trip Saver")
st.caption("Tell us your budget and destination. We'll find the trip that fits and track what you save.")

# Separate switches, so a Nessie key works without a SerpApi key (and vice versa).
demo_search = st.sidebar.toggle("Sample travel prices (no SerpApi calls)", value=not os.getenv("SERPAPI_KEY"))
demo_bank = st.sidebar.toggle("Demo bank (no Nessie calls)", value=not os.getenv("NESSIE_API_KEY"))
bank_demo = demo_bank or not os.getenv("NESSIE_API_KEY")
ss = st.session_state


def money(amount: float, cents: bool = False) -> str:
    """Dollar text for markdown. "$" is escaped so Streamlit doesn't treat pairs as math."""
    return f"\\${amount:,.2f}" if cents else f"\\${amount:,.0f}"


def esc(text: str) -> str:
    """Escape "$" in user-typed text for markdown."""
    return str(text).replace("$", "\\$")


def run_bank(fn, *args):
    """Call the bank; show a safe message instead of crashing (never raw exception text)."""
    try:
        return fn(*args)
    except (ValueError, bank.BankError) as error:  # both carry user-safe messages
        st.error(str(error))
    except Exception:
        st.error("The banking service didn't respond. Try again in a moment.")
    return None


# ---- 1. Trip details ----
st.header("1. Your trip")
budget = st.number_input("Total trip budget ($)", min_value=50, max_value=50000, value=1500, step=50)
c1, c2 = st.columns(2)
origin = c1.text_input("From (airport code)", "AUS").upper()
dest = c2.text_input("To (airport code)", "CUN").upper()
depart = c1.date_input("Depart", date.today() + timedelta(days=90))
ret = c2.date_input("Return", date.today() + timedelta(days=97))
city = st.text_input("Hotel search", "hotels in Cancun")

date_error = None
if depart is None:
    date_error = "Choose a departure date."
elif ret is None:
    date_error = "Choose a return date."
elif depart < date.today():
    date_error = "Departure must be today or later."
elif ret <= depart:
    date_error = "Return must be after departure."

start = st.button("Start planning", type="primary", disabled=bool(date_error))
if date_error:
    st.warning(date_error)
    st.stop()

details = (float(budget), origin, dest, depart, ret, city, demo_search, bank_demo,
           bool(os.getenv("SERPAPI_KEY")))
if start:
    trip = run_bank(bank.create_trip, budget, bank_demo)
    if trip:
        cached = demo_search or not os.getenv("SERPAPI_KEY")
        failed = False
        with st.spinner("Searching flights and hotels..."):
            try:
                flights = travel.search_flights(origin, dest, str(depart), str(ret), demo_search)
                hotels = travel.search_hotels(city, str(depart), str(ret), demo_search)
            except Exception:  # never show the exception: it may contain an API key
                failed = cached = True
                flights = travel.search_flights(origin, dest, str(depart), str(ret), True)
                hotels = travel.search_hotels(city, str(depart), str(ret), True)
        ss.update(trip=trip, flights=flights, hotels=hotels, details=details,
                  cached_prices=cached, search_failed=failed)

if "trip" not in ss:
    st.stop()
if ss.details != details:
    st.info("Trip details changed. Click **Start planning** to search again with a fresh budget.")
    st.stop()
if ss.search_failed:
    st.warning("Live search was unavailable. Showing sample prices, not live quotes.")
elif ss.cached_prices:
    st.caption("Sample prices for the demo; these are not live travel quotes.")

trip = ss.trip
flights, hotels = ss.flights, ss.hotels

# ---- 2. Budget tracker (Nessie) ----
summary = run_bank(bank.get_summary, trip)
if summary is None:
    st.stop()
remaining = summary["remaining"]

st.header("2. Your budget")
st.caption("Spending is tracked in simulated demo money." if trip["demo"]
           else "Spending is tracked in the Nessie sandbox (whole dollars).")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Budget", f"${summary['budget']:,.0f}")
m2.metric("Spent", f"${summary['spent']:,.0f}")
m3.metric("Remaining", f"${remaining:,.0f}")
m4.metric("Saved", f"${summary['saved']:,.0f}", help="Saved vs. typical prices (Trip Savings account)")
st.progress(min(1.0, summary["spent"] / summary["budget"]) if summary["budget"] else 0.0)
if summary["over_budget"]:
    st.error(f"You're {money(-remaining)} over budget. Remove something or pick a cheaper option.")


def fit_label(price: float) -> str:
    return "✅ fits" if price <= remaining else f"⚠️ {money(price - remaining)} over"


def save_label(saved: float) -> str:
    return f" · 💰 saves {money(saved)}" if saved >= 1 else ""


def add(category: str, description: str, amount: float, saved: float = 0.0):
    if run_bank(bank.record_pick, trip, category, description, amount, saved):
        st.rerun()


# ---- 3. Options ----
st.header("3. Pick your options")
if not (flights and hotels):
    st.warning("No matching flights or hotels with complete prices. Try different dates or a different destination.")

if flights:
    typical = planner.typical_price([f["price"] for f in flights])
    st.subheader("Flights")
    st.caption(f"Typical round-trip price: {money(typical)}")
    for i, f in enumerate(flights[:6]):
        saved = planner.savings_vs_typical(f["price"], typical)
        a, b, c = st.columns([4, 3, 1])
        a.markdown(f"**{f['airline']}** · {f['duration_min'] // 60}h {f['duration_min'] % 60}m")
        b.markdown(f"{money(f['price'])} · {fit_label(f['price'])}{save_label(saved)}")
        if c.button("Add", key=f"flight-{i}"):
            add("Flight", f"{f['airline']} flight {origin}→{dest}", f["price"], saved)

if hotels:
    typical = planner.typical_price([h["total"] for h in hotels])
    st.subheader("Hotels")
    st.caption(f"Typical stay: {money(typical)} total")
    for i, h in enumerate(hotels[:6]):
        saved = planner.savings_vs_typical(h["total"], typical)
        a, b, c = st.columns([4, 3, 1])
        a.markdown(f"**{h['name']}** · {h['rating']}★ · {money(h['per_night'])}/night")
        b.markdown(f"{money(h['total'])} total · {fit_label(h['total'])}{save_label(saved)}")
        if c.button("Add", key=f"hotel-{i}"):
            add("Hotel", h["name"], h["total"], saved)

st.subheader("Food & activities")
with st.form("extra", clear_on_submit=True):
    a, b, c = st.columns([2, 4, 2])
    category = a.selectbox("Type", ["Food", "Activity", "Other"])
    description = b.text_input("What", placeholder="e.g. Dinner at Taqueria El Fogón")
    amount = c.number_input("Cost ($)", min_value=1.0, value=40.0, step=5.0)
    if st.form_submit_button("Add to trip"):
        add(category, description or category, amount)

# ---- 4. Trip summary ----
st.header("4. Your trip")
if not summary["picks"]:
    st.caption("Nothing added yet. Pick a flight, hotel or activity above.")
for p in summary["picks"]:
    a, b, c = st.columns([5, 3, 1])
    a.markdown(f"{p['category']}: {esc(p['description'])}")
    b.markdown(f"–{money(p['amount'])}" + (f" · saved {money(p['saved'])}" if p["saved"] else ""))
    if c.button("✕", key=f"rm-{p['id']}", help="Remove"):
        run_bank(bank.remove_pick, trip, p["id"])
        st.rerun()
if summary["picks"]:
    st.success(f"**Final trip cost: {money(summary['final_total'])}** · "
               f"saved {money(summary['saved'])} vs. typical prices · "
               f"{money(remaining)} of your budget left")
