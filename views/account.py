"""Account page: sign in or create an account (email + password), then see what's saved.

Opened from the user icon in the top-right corner; hidden from the top menu.
"""
import streamlit as st

import accounts
import ui

ss = st.session_state
user = accounts.current_user()

if user:
    with st.container(key="card-account"):
        st.header(f"Hi, {user['name']} 👋")
        st.caption(f"Signed in as {user['email'] or user['name']}"
                   + (" with Google." if user.get("via") == "google" else "."))
        if not ss.get("account_error"):  # a storage problem is shown under the header on every page
            where = "your account" if isinstance(accounts.store(), accounts.SupabaseStore) else "this server"
            st.success(f"Your locked trips and Trip Funds are saved to {where} automatically.")
        trips, funds = ss.get("trip_history", []), ss.get("weekly_funds", {})
        a, b = st.columns(2)
        a.metric("Locked-in trips", len(trips))
        b.metric("Trip Funds", len(funds))
        if trips:
            st.subheader("Your trips")
            st.dataframe([{"Trip": t["place"] or t["route"], "Route": t["route"], "Dates": t["dates"],
                           "Total": f"${t['total']:,.0f}", "Confirmation": t["confirmation"]} for t in trips],
                         hide_index=True, width="stretch")
        else:
            st.caption("No locked-in trips yet. Plan one and lock it in; it's saved here.")
        left, right = st.columns(2)
        left.page_link("views/plan.py", label="Plan a trip", icon=":material/flight_takeoff:")
        right.page_link("views/fund.py", label="Grow your Trip Fund", icon=":material/savings:")
        st.caption("Saved for your account: your email, locked trips and Trip Funds. Nothing else. "
                   + ("You stay signed in while this tab is open." if user.get("via") == "email" else ""))
        if st.button("Sign out", icon=":material/logout:"):
            if user.get("via") == "google":
                st.logout()
            accounts.sign_out(ss)
            st.rerun()
else:
    with st.container(key="card-account"):
        st.header("Your FareWell account")
        st.write("Sign in to keep your **locked-in trips** and **Trip Funds**, demo money included, "
                 "across visits and devices. You can plan without an account too.")
        sign_in_tab, register_tab = st.tabs(["Sign in", "Create account"])
        with sign_in_tab:
            with st.form("sign_in"):
                email = st.text_input("Email", key="signin_email", autocomplete="email")
                password = st.text_input("Password", type="password", key="signin_password",
                                         autocomplete="current-password")
                if st.form_submit_button("Sign in", type="primary", use_container_width=True):
                    try:
                        ss[accounts.SESSION_KEY] = accounts.sign_in(email, password)
                    except (accounts.AccountError, accounts.StorageError) as error:
                        st.error(str(error))
                    else:
                        st.rerun()
        with register_tab:
            with st.form("register"):
                email = st.text_input("Email", key="register_email", autocomplete="email")
                password = st.text_input(f"Password (at least {accounts.MIN_PASSWORD} characters)", type="password",
                                         key="register_password", autocomplete="new-password")
                confirm = st.text_input("Confirm password", type="password", key="register_confirm",
                                        autocomplete="new-password")
                if st.form_submit_button("Create account", type="primary", use_container_width=True):
                    try:
                        ss[accounts.SESSION_KEY] = accounts.register(email, password, confirm)
                    except (accounts.AccountError, accounts.StorageError) as error:
                        st.error(str(error))
                    else:
                        st.rerun()
            st.caption("Passwords are stored only as a secure hash, never as text. This is a hackathon "
                       "project, so please use a password you don't use anywhere else. There's no "
                       "password reset yet.")
        if accounts.auth_configured():
            st.divider()
            if st.button("Continue with Google", icon=":material/login:"):
                st.login()

ui.powered_by()
