"""Homepage dashboard: finances, travel history and goals from this session, plus the planners.

Every number comes from the trip in progress (Nessie or demo money) or trips locked in during
this browser session; with nothing planned yet the cards say so instead of showing samples.
"""
import streamlit as st

import bank
import ui

ss = st.session_state
trip = ss.get("trip")
summary = None
if trip:
    try:
        summary = bank.get_summary(trip)
    except Exception:  # a banking hiccup must not break the homepage
        summary = None
history = ss.get("trip_history", [])

st.markdown("<h1 style='margin-bottom:0'>Welcome to FareWell 👋</h1>", unsafe_allow_html=True)
st.caption("The best trip your budget can buy: plan it, see it on the map, and lock it in.")
st.header("Dashboard Summary")

# ---- Finances: the Nessie trip accounts ----
if summary:
    source = "Demo money" if trip["demo"] else "Nessie sandbox"
    tone = "bad" if summary["over_budget"] else "good"
    finances = ui.glass("Finances", "Trip budget", f"2 accounts · {source}",
                        ui.line("Budget", ui.dollars(summary["budget"]), "Trip Budget account")
                        + ui.line("Spent", ui.dollars(summary["spent"]), f"{len(summary['picks'])} picks")
                        + ui.line("Remaining", ui.dollars(summary["remaining"]), "Left to plan", tone)
                        + ui.line("Saved", ui.dollars(summary["saved"]), "Trip Savings · vs. typical prices", "good"))
else:
    finances = ui.glass("Finances", "Trip budget", "No accounts yet",
                        ui.empty("No trip budget yet",
                                 "Start planning a trip and its Budget and Savings accounts show up here."))

# ---- Travel history: trips locked in this session ----
if history:
    total = sum(t["total"] for t in history)
    rows = "".join(ui.line(t["place"] or t["route"], ui.dollars(t["total"]), f"{t['route']} · {t['dates']}")
                   for t in history[:4])
    travel_history = ui.glass("Travel History", "Locked-in trips",
                              f"{len(history)} trip{'s' * (len(history) != 1)} · {ui.dollars(total, cents=True)}", rows)
else:
    travel_history = ui.glass("Travel History", "Locked-in trips", "0 trips",
                              ui.empty("No trips yet", "Lock in a trip and it lands here with its confirmation."))

# ---- Active goals: progress on the trip in progress ----
if summary:
    picked = {p["category"] for p in summary["picks"]}
    parts = [c for c in ("Flight", "Hotel", "Food", "Activity") if c in picked]
    used = summary["spent"] / summary["budget"] * 100 if summary["budget"] else 0
    goals = (ui.goal("Stay on budget", f"{ui.dollars(summary['spent'])} of {ui.dollars(summary['budget'])} used",
                     used, f"{used:.0f}%")
             + ui.goal("Plan every part", ", ".join(parts) or "Flight, hotel, food, activity",
                       len(parts) / 4 * 100, f"{len(parts)}/4")
             + ui.goal("Lock it in", "Confirmed" if trip.get("locked") else "Not locked yet",
                       100 if trip.get("locked") else 0, "✓" if trip.get("locked") else "—"))
    active = ui.glass("Active Goals", "Current trip", "3 goals", goals)
else:
    active = ui.glass("Active Goals", "Current trip", "0 goals",
                      ui.empty("No goals yet", "Your budget and planning progress appear once a trip starts."))

with st.container(key="hero-home"):
    st.html(f"<div class='ts-glass-row'>{finances}{travel_history}{active}</div>")
    # Opens the Trip Planner with the group-chat panel already open.
    st.page_link("views/plan.py", label="Paste your group chat → get a trip draft", icon="💬",
                 query_params={"start": "chat"})

st.write("")
trip_tile, fin_tile = st.columns(2, gap="large")
with trip_tile.container(key="tile-trip"):
    st.markdown("### Trip Planner")
    st.caption("Budget in, the best trip that fits out: live flights and hotels, a route map, "
               "Recommended / Cheapest / Best-quality picks, and booking links.")
    st.page_link("views/plan.py", label="Continue planning" if trip else "Start a trip",
                 icon=":material/flight_takeoff:")
with fin_tile.container(key="tile-fin"):
    st.markdown("### Financial Planner")
    st.caption("Save toward a trip with weekly transfers from checking into a Trip Fund "
               "(Capital One Nessie). Set a deadline and watch your fund grow.")
    st.page_link("views/fund.py", label="Grow your Trip Fund", icon=":material/savings:")

ui.powered_by()
