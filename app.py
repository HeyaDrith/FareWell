"""Trip Saver: type a budget and destination, pick the options that fit, and see the savings.

Run:  streamlit run app.py
"""
import os
from datetime import date, datetime, timedelta

import streamlit as st
from dotenv import load_dotenv

import bank
import draft_ui
import planner
import travel
import trip_map

load_dotenv()
# On Streamlit Community Cloud, keys live in st.secrets instead of .env.
try:
    for k in ("SERPAPI_KEY", "NESSIE_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL"):
        if k in st.secrets:
            os.environ.setdefault(k, st.secrets[k])
except Exception:
    pass

st.set_page_config(page_title="Trip Saver", page_icon="✈️")
st.title("✈️ Trip Saver")
st.caption("Tell us your budget and destination. We'll find the trip that fits and track what you save.")

# Separate switches, so each API key works on its own.
demo_search = st.sidebar.toggle("Sample travel prices (no SerpApi calls)", value=not os.getenv("SERPAPI_KEY"),
                                key="demo_search")
demo_bank = st.sidebar.toggle("Demo bank (no Nessie calls)", value=not os.getenv("NESSIE_API_KEY"),
                              key="demo_bank")
demo_ai = st.sidebar.toggle("Demo AI drafts (no Gemini calls)", value=not os.getenv("GEMINI_API_KEY"),
                            key="demo_ai")
bank_demo = demo_bank or not os.getenv("NESSIE_API_KEY")
ss = st.session_state

# Optional: turn a group chat or screenshot into reviewed trip details (Gemini).
draft_ui.render_draft_panel(demo_ai)


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
# Keyed widgets with session defaults, so an applied Gemini draft can fill them in.
for key, default in {
    "trip_budget": 1500, "trip_origin": "AUS", "trip_destination": "CUN",
    "trip_city": "hotels in Cancun", "trip_depart": date.today() + timedelta(days=90),
    "trip_return": date.today() + timedelta(days=97),
}.items():
    ss.setdefault(key, default)
budget = st.number_input("Total trip budget ($)", min_value=50, max_value=50000, step=50, key="trip_budget")
c1, c2 = st.columns(2)
# Searchable airport dropdowns: type a city or code and the list filters as you type.
airports = travel.airport_codes()
for key in ("trip_origin", "trip_destination"):
    code = (ss.get(key) or "").strip().upper()
    ss[key] = code or None
    if code and code not in airports:  # e.g. a smaller airport typed in or from a Gemini draft
        airports = [code] + airports


def follow_destination():
    """Picking a destination fills in the hotel search for that city."""
    code = (ss.get("trip_destination") or "").strip().upper()
    if travel.airport_city(code):
        ss.trip_city = f"hotels in {travel.airport_city(code)}"


origin = (c1.selectbox("From", airports, index=None, key="trip_origin", format_func=travel.airport_label,
                       accept_new_options=True, placeholder="Type a city or airport code")
          or "").strip().upper()
dest = (c2.selectbox("To", airports, index=None, key="trip_destination", format_func=travel.airport_label,
                     accept_new_options=True, placeholder="Type a city or airport code",
                     on_change=follow_destination) or "").strip().upper()
depart = c1.date_input("Depart", value=None, key="trip_depart")
ret = c2.date_input("Return", value=None, key="trip_return")
city = st.text_input("Hotel search", key="trip_city") or ""

date_error = planner.trip_input_error(origin, dest, depart, ret)

start = st.button("Start planning", type="primary", disabled=bool(date_error))
if date_error:
    st.warning(date_error)
    st.stop()

search_fields = {"trip_origin": origin, "trip_destination": dest, "trip_city": city,
                 "trip_depart": depart, "trip_return": ret}
draft_ui.render_planning_notes(search_fields)

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
locked = trip.get("locked")
links = ss.setdefault("links", {})  # pick id -> [(button label, url), ...]
picked = {p["category"] for p in summary["picks"]}
days = max(1, (ret - depart).days + 1)
place = city.removeprefix("hotels in ").strip() or dest

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
if summary["picks"]:
    draft_ui.render_planning_notes(search_fields, summary["final_total"])

spent_on = {c: sum(p["amount"] for p in summary["picks"] if p["category"] == c) for c in planner.BUDGET_SPLIT}
# For a part already picked, its budget includes what swapping it would give back.
allowance = {c: planner.category_allowance(c, remaining + spent_on[c], picked - {c})
             for c in planner.BUDGET_SPLIT}
split = [f"{label} {money(allowance[c])}" for c, label in
         (("Flight", "✈️ Flights"), ("Hotel", "🏨 Hotel"), ("Food", "🍽️ Food"), ("Activity", "🎟️ Activities"))
         if c not in picked]
if split and not summary["over_budget"]:
    st.caption("Suggested split of what's left: " + " · ".join(split)
               + (f" (food ≈ {money(allowance['Food'] / days)}/day)" if "Food" not in picked else ""))


def fit_label(price: float) -> str:
    return "✅ fits" if price <= remaining else f"⚠️ {money(price - remaining)} over"


def save_label(saved: float) -> str:
    return f" · 💰 saves {money(saved)}" if saved >= 1 else ""


def badges(i: int, chosen: dict) -> str:
    tags = [tag for key, tag in (("recommended", "⭐ Recommended"), ("cheapest", "💰 Cheapest"),
                                 ("best_quality", "✨ Best quality")) if chosen[key] == i]
    return " · ".join(tags)


def explain(chosen: dict, names: list[str], prices: list[float], budget_label: str, budget: float):
    rec, best = chosen["recommended"], chosen["best_quality"]
    if rec is None:
        return
    fits = prices[rec] <= budget
    reason = (f"best quality that fits your {money(budget)} {budget_label} budget" if fits
              else f"nothing fits your {money(budget)} {budget_label} budget, so this is the cheapest")
    line = f"⭐ **Recommended: {esc(names[rec])}** ({money(prices[rec])}), {reason}."
    if best != rec:
        line += f" ✨ Upgrade: **{esc(names[best])}** for {money(prices[best] - prices[rec])} more."
    st.markdown(line)


def add(category: str, description: str, amount: float, saved: float = 0.0, buttons=()):
    pick = run_bank(bank.record_pick, trip, category, description, amount, saved)
    if pick:
        links[pick["id"]] = [(label, url) for label, url in buttons if url]
        st.rerun()


def clock(departs: str) -> str:
    """'2027-01-22 07:05' -> '7:05 AM' (blank if unknown)."""
    try:
        return datetime.strptime(departs, "%Y-%m-%d %H:%M").strftime("%I:%M %p").lstrip("0")
    except (TypeError, ValueError):
        return ""


def flight_id(f: dict) -> str:
    """Flight number(s) and departure time that identify the exact listing, if known."""
    parts = [" / ".join(f.get("flight_numbers") or [])]
    if clock(f.get("departs", "")):
        parts.append(f"departs {clock(f['departs'])}")
    return ", ".join(part for part in parts if part)


def book_buttons(pick: dict):
    """Big buttons that open the booking page for this pick in a new tab."""
    for label, url in links.get(pick["id"], []):
        st.link_button(label, url)


def view_links(buttons) -> str:
    """Small markdown links so an option can be checked before adding it (opens a new tab)."""
    def safe(url: str) -> str:  # keep provider URLs from breaking the markdown link syntax
        return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
    return " · ".join(f"[{label}]({safe(url)})" for label, url in buttons if url)


def flight_buttons(f: dict) -> list[tuple[str, str]]:
    return [("Book on Google Flights ↗", travel.flight_booking_url(
        f["airline"], origin, dest, str(depart), str(ret), f.get("flight_numbers")))]


def hotel_buttons(h: dict) -> list[tuple[str, str]]:
    return [("Book this hotel ↗" if h.get("property_token") else "Find this hotel ↗",
             travel.hotel_booking_url(h["name"], place, str(depart), str(ret), h.get("property_token", ""))),
            ("Hotel website ↗", h.get("website", ""))]


# ---- 3. Options ----
st.header("3. Pick your options")
if locked:
    st.info("Your trip is locked in. Unlock it below to change your picks.")
if not (flights and hotels):
    st.warning("No matching flights or hotels with complete prices. Try different dates or a different destination.")

flights_shown, hotels_shown = flights[:6], hotels[:6]
shortest = min((f["duration_min"] for f in flights_shown if f["duration_min"]), default=0)
flight_chosen = planner.pick_options([f["price"] for f in flights_shown],
                                     [planner.flight_quality(f, shortest) for f in flights_shown], allowance["Flight"])
hotel_chosen = planner.pick_options([h["total"] for h in hotels_shown],
                                    [planner.hotel_quality(h) for h in hotels_shown], allowance["Hotel"])

# ---- Map: the flight path (picked, else recommended) and the hotels near the destination ----
if flights_shown or hotels_shown:
    picked_names = {p["description"] for p in summary["picks"] if p["category"] == "Hotel"}
    recommended_hotel = (hotels_shown[hotel_chosen["recommended"]]["name"]
                         if hotel_chosen["recommended"] is not None else None)
    stops, flight_label = trip_map.flight_path([], origin, dest), f"{origin} → {dest}"
    if flights_shown:
        default = ss.get("map_flight", flight_chosen["recommended"] or 0)
        i = st.selectbox("Show the flight path for", range(len(flights_shown)), index=min(default, len(flights_shown) - 1),
                         format_func=lambda i: f"{flights_shown[i]['airline']} · ${flights_shown[i]['price']:,.0f}"
                                               + (" · ⭐ Recommended" if i == flight_chosen["recommended"] else ""))
        stops = trip_map.flight_path(flights_shown[i].get("route") or [], origin, dest)
        flight_label = esc(flights_shown[i]["airline"])
    trip_map.render(flight_label, stops,
                    trip_map.hotel_points(hotels_shown, travel.airport_location(dest), picked_names, recommended_hotel),
                    esc(place))

if flights:
    shown = flights_shown
    prices = [f["price"] for f in shown]
    chosen = flight_chosen
    typical = planner.typical_price([f["price"] for f in flights])
    st.subheader("Flights")
    st.caption(f"Typical round-trip price: {money(typical)}. Quality = shorter trip, fewer stops.")
    explain(chosen, [f["airline"] for f in shown], prices, "flight", allowance["Flight"])
    for i, f in enumerate(shown):
        saved = planner.savings_vs_typical(f["price"], typical)
        stops = f.get("stops", 0)
        a, b, c = st.columns([4, 3, 1])
        a.markdown(f"**{esc(f['airline'])}** · " + (f"{esc(flight_id(f))} · " if flight_id(f) else "")
                   + f"{f['duration_min'] // 60}h {f['duration_min'] % 60}m · "
                   f"{'Nonstop' if not stops else f'{stops} stop' + ('s' if stops > 1 else '')}"
                   + (f"  \n{badges(i, chosen)}" if badges(i, chosen) else ""))
        b.markdown(f"{money(f['price'])} · {fit_label(f['price'])}{save_label(saved)}  \n"
                   + view_links([("View on Google Flights ↗", flight_buttons(f)[0][1])]))
        if c.button("Add", key=f"flight-{i}", disabled=bool(locked)):
            ss.map_flight = i  # the map follows the flight you add
            add("Flight", f"{f['airline']} flight {origin}→{dest}"
                + (f" ({flight_id(f)})" if flight_id(f) else ""), f["price"], saved, flight_buttons(f))

if hotels:
    shown = hotels_shown
    prices = [h["total"] for h in shown]
    chosen = hotel_chosen
    typical = planner.typical_price([h["total"] for h in hotels])
    st.subheader("Hotels")
    st.caption(f"Typical stay: {money(typical)} total. Quality = guest rating.")
    explain(chosen, [h["name"] for h in shown], prices, "hotel", allowance["Hotel"])
    for i, h in enumerate(shown):
        saved = planner.savings_vs_typical(h["total"], typical)
        a, b, c = st.columns([4, 3, 1])
        a.markdown(f"**{esc(h['name'])}** · {h['rating']}★ · {money(h['per_night'])}/night"
                   + (f"  \n{badges(i, chosen)}" if badges(i, chosen) else ""))
        views = [("View hotel ↗" if h.get("property_token") else "Find hotel ↗", hotel_buttons(h)[0][1]),
                 ("Website ↗", h.get("website", ""))]
        b.markdown(f"{money(h['total'])} total · {fit_label(h['total'])}{save_label(saved)}  \n"
                   + view_links(views))
        if c.button("Add", key=f"hotel-{i}", disabled=bool(locked)):
            add("Hotel", h["name"], h["total"], saved, hotel_buttons(h))

st.subheader("Food & activities")
if "Food" not in picked:
    st.caption(f"Food budget ≈ {money(allowance['Food'] / days)}/day for {days} days.")
with st.form("extra", clear_on_submit=True):
    a, b, c = st.columns([2, 4, 2])
    category = a.selectbox("Type", ["Food", "Activity", "Other"])
    description = b.text_input("What", placeholder="e.g. Dinner at Taqueria El Fogón")
    amount = c.number_input("Cost ($)", min_value=1.0, value=40.0, step=5.0)
    if st.form_submit_button("Add to trip", disabled=bool(locked)):
        add(category, description or category, amount, 0.0,
            [("Open in Google Maps ↗", travel.place_url(f"{description or category} {place}"))])

# ---- 4. Trip summary ----
st.header("4. Your trip")
if not summary["picks"]:
    st.caption("Nothing added yet. Pick a flight, hotel or activity above.")
for p in summary["picks"]:
    a, b, c = st.columns([5, 3, 1])
    a.markdown(f"{p['category']}: {esc(p['description'])}")
    if not locked:  # once locked, the buttons move to the confirmation below
        with a:
            book_buttons(p)
    b.markdown(f"–{money(p['amount'])}" + (f" · saved {money(p['saved'])}" if p["saved"] else ""))
    if not locked and c.button("✕", key=f"rm-{p['id']}", help="Remove"):
        run_bank(bank.remove_pick, trip, p["id"])
        st.rerun()
if summary["picks"]:
    st.markdown(f"**Final trip cost: {money(summary['final_total'])}** · "
                f"saved {money(summary['saved'])} vs. typical prices · "
                f"{money(remaining)} of your budget left")

# ---- 5. Lock it in ----
st.header("5. Lock in your trip")
if locked:
    if ss.pop("celebrate", False):
        st.balloons()
    st.success(f"🎉 **Trip locked in!** Confirmation **{locked['confirmation']}** · {locked['locked_on']}  \n"
               f"{origin} → {dest}, {depart:%b %d} to {ret:%b %d} · total {money(summary['final_total'])} · "
               f"saved {money(summary['saved'])}")
    st.subheader("Book each part of your trip")
    for p in summary["picks"]:
        st.markdown(f"**{p['category']}: {esc(p['description'])}** · {money(p['amount'])}")
        book_buttons(p)
    if ss.cached_prices:
        st.caption("These are sample listings, so the buttons open a matching search, not a specific listing.")
    st.caption("Demo confirmation: nothing is reserved or charged. The buttons open each booking page "
               "in a new tab. In a full version this step would pay from your Capital One account.")
    if st.button("Unlock to make changes"):
        run_bank(bank.unlock_trip, trip)
        st.rerun()
else:
    blocked = ("Pick at least one option first." if not summary["picks"] else
               "Get under budget first." if summary["over_budget"] else "")
    st.caption(blocked or "Happy with your picks? Lock them in to get your trip summary and booking links.")
    if st.button("🔒 Lock in my trip", type="primary", disabled=bool(blocked)):
        if run_bank(bank.lock_trip, trip):
            ss.celebrate = True
            st.rerun()
