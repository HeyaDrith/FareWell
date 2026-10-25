"""Trip Saver: type a budget and destination, pick the options that fit, and see the savings.

Run:  streamlit run app.py

This file is the router: shared setup, the data-source switches and the top navigation.
The pages are views/home.py (dashboard) and views/plan.py (the trip planner).
"""
import os

import streamlit as st
from dotenv import load_dotenv

import ui

load_dotenv()
# On Streamlit Community Cloud, keys live in st.secrets instead of .env.
try:
    for k in ("SERPAPI_KEY", "NESSIE_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL"):
        if k in st.secrets:
            os.environ.setdefault(k, st.secrets[k])
except Exception:
    pass

st.set_page_config(page_title="Trip Saver", page_icon="✈️", layout="wide")
ui.inject_css()

home = st.Page("views/home.py", title="Home", icon=":material/home:", default=True)
plan = st.Page("views/plan.py", title="Trip Planner", icon=":material/flight_takeoff:", url_path="plan")
page = st.navigation([home, plan], position="top")

# Data-source switches live in a small settings menu on every page, so each API key works on
# its own and the choice carries between pages. (Order matters to the tests: search, bank, AI.)
_, settings = st.columns([4, 1])
with settings.popover("Data sources", icon=":material/tune:", use_container_width=True):
    st.toggle("Sample travel prices (no SerpApi calls)", value=not os.getenv("SERPAPI_KEY"), key="demo_search")
    st.toggle("Demo bank (no Nessie calls)", value=not os.getenv("NESSIE_API_KEY"), key="demo_bank")
    st.toggle("Demo AI drafts (no Gemini calls)", value=not os.getenv("GEMINI_API_KEY"), key="demo_ai")
    st.caption("Turn a switch off to use the live API once its key is set in `.env`.")

page.run()
