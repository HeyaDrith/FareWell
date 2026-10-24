"""Trip Saver: plan a trip with live prices and fund it automatically.

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
st.caption("Find a trip, then let your Trip Fund save for it automatically.")

demo = st.sidebar.toggle("Demo mode (cached data, no API calls)", value=not os.getenv("SERPAPI_KEY"))

# ---- 1. Search ----
st.header("1. Plan your trip")
c1, c2 = st.columns(2)
origin = c1.text_input("From (airport code)", "AUS").upper()
dest = c2.text_input("To (airport code)", "CUN").upper()
depart = c1.date_input("Depart", date.today() + timedelta(days=90))
ret = c2.date_input("Return", date.today() + timedelta(days=97))
city = st.text_input("Hotel search", "hotels in Cancun")

if st.button("Search prices", type="primary"):
    with st.spinner("Searching..."):
        try:
            st.session_state.flights = travel.search_flights(origin, dest, str(depart), str(ret), demo)
            st.session_state.hotels = travel.search_hotels(city, str(depart), str(ret), demo)
        except Exception as e:  # keep the demo alive if an API hiccups
            st.warning(f"Live search failed ({e}). Showing cached demo data.")
            st.session_state.flights = travel.search_flights(origin, dest, str(depart), str(ret), True)
            st.session_state.hotels = travel.search_hotels(city, str(depart), str(ret), True)
    # remember last price for the trend message
    st.session_state.prev_price = st.session_state.get("last_price")

flights = st.session_state.get("flights")
hotels = st.session_state.get("hotels")

if flights and hotels:
    f_pick = st.selectbox("Flight", range(len(flights)),
                          format_func=lambda i: f"{flights[i]['airline']} - ${flights[i]['price']:.0f}")
    h_pick = st.selectbox("Hotel", range(len(hotels)),
                          format_func=lambda i: f"{hotels[i]['name']} - ${hotels[i]['total']:.0f} total "
                                                f"({hotels[i]['rating']}★)")
    activities = st.number_input("Activities / food budget ($)", 0, 5000, 200, step=50)
    budget = planner.trip_budget(flights[f_pick]["price"], hotels[h_pick]["total"], activities)
    st.session_state.last_price = budget
    st.metric("Trip budget", f"${budget:,.0f}")
    st.info(planner.price_trend(st.session_state.get("prev_price"), budget))

    # ---- 2. Fund ----
    st.header("2. Fund it")
    deadline = st.date_input("Save by", date.today() + timedelta(days=60), key="deadline")

    if depart is None:
        st.warning("Choose a departure date before setting up your savings plan.")
        st.stop()
    try:
        planner.validate_deadline(deadline, departure=depart)
    except ValueError as error:
        st.warning(str(error))
        st.stop()

    bank_demo = demo or not os.getenv("NESSIE_API_KEY")
    wallets = st.session_state.setdefault("wallets", {})
    wallet = wallets.setdefault("demo" if bank_demo else "nessie", {})
    st.caption("Funding uses simulated demo money." if bank_demo else "Funding uses the Nessie sandbox.")
    if "accounts" not in wallet:
        if st.button("Create my Trip Fund"):
            try:
                wallet["accounts"] = bank.setup_accounts(bank_demo)
            except Exception:
                st.error("Could not create the Trip Fund. Check the banking service before trying again.")
            else:
                st.rerun()
    else:
        acc = wallet["accounts"]
        try:
            saved = bank.get_balance(acc["fund_id"], bank_demo)
            checking = bank.get_balance(acc["checking_id"], bank_demo)
        except Exception:
            st.error("Could not load account balances. Funding is paused until balances are available.")
            st.stop()
        weekly = planner.weekly_amount(budget, saved, deadline)

        st.progress(min(1.0, saved / budget) if budget else 0.0,
                    text=f"${saved:,.0f} of ${budget:,.0f} saved")
        contribution_timing = "today" if deadline == date.today() else "per week"
        st.write(f"**Plan:** move **${weekly:,.2f} {contribution_timing}** from checking "
                 f"(balance ${checking:,.2f}).")

        if weekly == 0:
            st.success("🎉 Trip fully funded. Time to book!")
        elif wallet.get("transfer_pending"):
            st.warning("A transfer was submitted or could not be confirmed. Check its status in Nessie before sending more money. Further transfers are paused in this session.")
        elif weekly > checking:
            st.warning("Not enough money in checking for this contribution. Add funds or revise your plan.")
        else:
            # A click submits one contribution; it does not advance the date.
            transfer_label = "Transfer today" if deadline == date.today() else "Run this week's transfer"
            if st.button(f"{transfer_label} (${weekly:,.2f})"):
                wallet["transfer_pending"] = not bank_demo
                try:
                    bank.transfer(acc["checking_id"], acc["fund_id"], weekly, bank_demo)
                except ValueError:
                    wallet["transfer_pending"] = False
                    st.error("The transfer was not sent. Check the amount and available checking funds.")
                except Exception:
                    st.error("Could not confirm the transfer. Check its status before trying again.")
                else:
                    st.rerun()
