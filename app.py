"""FareWell: type a budget and destination, pick the options that fit, and see the savings.

Run:  streamlit run app.py

This file is the router: shared setup, the data-source switches and the top navigation.
Pages: views/home.py (dashboard), views/plan.py (trip planner), views/fund.py (weekly funding).
"""
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

import accounts
import ui

load_dotenv()
# On Streamlit Community Cloud, keys live in st.secrets instead of .env.
try:
    for k in ("SERPAPI_KEY", "NESSIE_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL",
              "SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        if k in st.secrets:
            os.environ.setdefault(k, st.secrets[k])
except Exception:
    pass

# Paths from this file, so the app also runs when launched from another folder.
ASSETS = Path(__file__).parent / "assets"
st.set_page_config(page_title="FareWell", page_icon=str(ASSETS / "farewell-icon.svg"), layout="wide")
st.logo(str(ASSETS / "farewell-logo.svg"), size="large")  # the full wordmark in the top bar
ui.inject_css()

home = st.Page("views/home.py", title="Home", icon=":material/home:", default=True)
plan = st.Page("views/plan.py", title="Trip Planner", icon=":material/flight_takeoff:", url_path="plan")
fund = st.Page("views/fund.py", title="Financial Planner", icon=":material/savings:", url_path="fund")
# The Account page isn't in the top menu; the user icon in the top-right corner opens it.
account_page = st.Page("views/account.py", title="Account", icon=":material/account_circle:",
                       url_path="account", visibility="hidden")
page = st.navigation([home, plan, fund, account_page], position="top")

# Data-source switches live in a small settings menu on every page, so each API key works on
# its own and the choice carries between pages. (Order matters to the tests: search, bank, AI.)
_, settings, account = st.columns([6, 2, 1.1], vertical_alignment="center")
user = accounts.current_user()
# A small user icon in the top-right corner: "Account" when signed out, the person's name when in.
with account.container(key="account-link"):
    st.page_link(account_page, label=user["name"][:14] if user else "Account", icon=":material/account_circle:",
                 help=("Your account and saved trips" if user else
                       "Sign in or create an account to keep your trips and Trip Funds"))
with settings.popover("Data sources", icon=":material/tune:", use_container_width=True):
    st.toggle("Sample travel prices (no SerpApi calls)", value=not os.getenv("SERPAPI_KEY"), key="demo_search")
    st.toggle("Demo bank (no Nessie calls)", value=not os.getenv("NESSIE_API_KEY"), key="demo_bank")
    st.toggle("Demo AI drafts (no Gemini calls)", value=not os.getenv("GEMINI_API_KEY"), key="demo_ai")
    st.caption("Turn a switch off to use the live API once its key is set in `.env`.")

# Signed in: load this user's saved trips and Trip Funds once, and save any change from the last
# run (every change ends in a rerun, so it's saved before the next page draws).
accounts.sync(st.session_state)
if accounts.current_user() and st.session_state.get("account_error"):
    st.warning(st.session_state.account_error + " Your work stays on this page and saves once the connection is back.")
page.run()
