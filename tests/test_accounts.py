"""Accounts: sign-in state, saving to Supabase or a local file, and restoring per user."""
from datetime import date, timedelta
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import requests
from streamlit.testing.v1 import AppTest

import accounts
import bank
import funding
from app_support import APP, DemoAppCase

TODAY = date.today()
ALEX = {"id": "google-123", "email": "alex@example.com", "name": "Alex"}


class TempStoreMixin:
    def temp_store(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return accounts.LocalStore(Path(folder.name) / "accounts.db")


class StorageTests(TempStoreMixin, unittest.TestCase):
    def test_local_store_round_trip_and_overwrite(self):
        store = self.temp_store()
        self.assertIsNone(store.load("nobody"))
        store.save("u1", "a@example.com", {"trip_history": [{"confirmation": "TS-1"}]})
        store.save("u1", "a@example.com", {"trip_history": []})
        store.save("u2", "b@example.com", {"x": 1})
        self.assertEqual(store.load("u1"), {"trip_history": []})
        self.assertEqual(store.load("u2"), {"x": 1})

    def test_supabase_store_requests_and_errors(self):
        reply = MagicMock(status_code=200)
        reply.json.return_value = [{"data": {"trip_history": []}}]
        with patch("requests.request", return_value=reply) as call:
            store = accounts.SupabaseStore("https://abc.supabase.co/", "sb_secret_xyz")
            self.assertEqual(store.load("google-123"), {"trip_history": []})
            method, url = call.call_args.args
            self.assertEqual((method, url), ("GET", "https://abc.supabase.co/rest/v1/farewell_users"))
            self.assertEqual(call.call_args.kwargs["params"], {"user_id": "eq.google-123", "select": "data"})
            self.assertNotIn("Authorization", call.call_args.kwargs["headers"])  # new secret keys aren't JWTs
            self.assertFalse(call.call_args.kwargs["allow_redirects"])
            store.save("google-123", "a@example.com", {"x": 1})
            sent = call.call_args.kwargs
            self.assertEqual(sent["json"]["data"], {"x": 1})
            self.assertIn("merge-duplicates", sent["headers"]["Prefer"])
        self.assertIn("Authorization", accounts.SupabaseStore("https://a.co", "eyJlegacy").headers)
        for pasted in ("https://abc.supabase.co/rest/v1/", "https://abc.supabase.co/rest/v1", " https://abc.supabase.co "):
            self.assertEqual(accounts.SupabaseStore(pasted, "k").endpoint, "https://abc.supabase.co/rest/v1/farewell_users")
        reply.json.return_value = []
        with patch("requests.request", return_value=reply):
            self.assertIsNone(store.load("new-user"))
        for failure in (MagicMock(status_code=401), requests.ConnectionError("down")):
            with self.subTest(failure=failure), self.assertRaises(accounts.StorageError):
                with patch("requests.request", **({"side_effect": failure} if isinstance(failure, Exception)
                                                  else {"return_value": failure})):
                    store.load("google-123")
        bad = MagicMock(status_code=200)
        bad.json.side_effect = ValueError("not json")
        with patch("requests.request", return_value=bad), self.assertRaises(accounts.StorageError):
            store.load("google-123")

    def test_supabase_is_used_only_with_both_settings(self):
        cases = {("https://abc.supabase.co", "key"): accounts.SupabaseStore,
                 ("", "key"): accounts.LocalStore, ("https://abc.supabase.co", ""): accounts.LocalStore,
                 ("http://insecure.example", "key"): accounts.LocalStore}
        for (url, key), kind in cases.items():
            with self.subTest(url=url, key=key), patch.dict(os.environ, {"SUPABASE_URL": url, "SUPABASE_SERVICE_KEY": key}):
                self.assertIsInstance(accounts.store(), kind)


class SaveAndRestoreTests(TempStoreMixin, unittest.TestCase):
    def setUp(self):
        for context in (patch.dict(bank._DEMO, {}, clear=True), patch.dict(os.environ, {"NESSIE_API_KEY": ""})):
            context.start()
            self.addCleanup(context.stop)

    def test_trip_fund_with_demo_money_survives_a_server_restart(self):
        fund = funding.create(500, TODAY + timedelta(days=28), True, TODAY)
        funding.contribute(fund, TODAY, amount=120)
        saved = accounts.snapshot({"weekly_funds": {"demo": fund}, "trip_history": []})
        self.assertEqual(saved["funds"]["demo"]["demo_balances"], {"checking": 2880.0, "fund": 120.0})
        bank._DEMO.clear()  # the server restarted
        ss = {}
        accounts.restore(ss, saved)
        restored = ss["weekly_funds"]["demo"]
        self.assertEqual(restored["deadline"], fund["deadline"])
        self.assertEqual(restored["history"], fund["history"])
        self.assertEqual(funding.balances(restored), (2880.0, 120.0))
        funding.contribute(restored, TODAY, amount=30)  # and it keeps working
        self.assertEqual(funding.balances(restored), (2850.0, 150.0))

    def test_restore_merges_trips_and_skips_damaged_data(self):
        ss = {"trip_history": [{"confirmation": "TS-NEW", "route": "AUS → CUN", "place": "Cancún",
                                "dates": "Jan 1", "total": 500.0, "saved": 20.0}]}
        saved = {"trip_history": [{"confirmation": "TS-NEW", "route": "dup"},
                                  {"confirmation": "TS-OLD", "route": "AUS → MIA", "total": "300"},
                                  {"route": "no confirmation"}, "junk"],
                 "funds": {"demo": {"target": "x"}, "nessie": "junk", "other": {}}}
        accounts.restore(ss, saved)
        self.assertEqual([t["confirmation"] for t in ss["trip_history"]], ["TS-NEW", "TS-OLD"])
        self.assertEqual(ss["trip_history"][1]["total"], 300.0)
        self.assertEqual(ss["weekly_funds"], {})
        accounts.restore(ss, None)  # nothing saved yet: nothing changes
        self.assertEqual(len(ss["trip_history"]), 2)

    def test_sync_rules(self):
        store = self.temp_store()
        ss = {"trip_history": [{"confirmation": "TS-1", "route": "AUS → CUN", "place": "Cancún", "dates": "x",
                                "total": 100.0, "saved": 0.0}]}
        with patch("accounts.store", return_value=store):
            with patch("accounts.current_user", return_value=None), patch.object(store, "save") as save:
                accounts.sync(ss)  # signed out: nothing is saved
                save.assert_not_called()
            with patch("accounts.current_user", return_value=ALEX):
                accounts.sync(ss)  # sign in: guest trip is merged and saved
                self.assertEqual(store.load("google-123")["trip_history"][0]["confirmation"], "TS-1")
                with patch.object(store, "save") as save:
                    accounts.sync(ss)  # nothing changed: no save
                    save.assert_not_called()
            with patch("accounts.current_user", return_value=None):
                accounts.sync(ss)  # signing out clears the user's data from the page
                self.assertNotIn("trip_history", ss)
            with patch("accounts.current_user", return_value=ALEX):
                accounts.sync(ss)  # signing back in restores it
                self.assertEqual(ss["trip_history"][0]["confirmation"], "TS-1")

    def test_a_failed_load_never_overwrites_saved_data(self):
        store = self.temp_store()
        store.save("google-123", "alex@example.com", {"trip_history": [{"confirmation": "TS-KEEP"}]})
        ss = {}
        with patch("accounts.store", return_value=store), patch("accounts.current_user", return_value=ALEX):
            with patch.object(store, "load", side_effect=accounts.StorageError("down")), \
                 patch.object(store, "save") as save:
                accounts.sync(ss)
                save.assert_not_called()
            self.assertEqual(ss["account_error"], "down")  # shown in the account menu
            self.assertNotIn("account_user", ss)  # not signed in to storage yet, so nothing can be saved
            accounts.sync(ss)  # back up: the saved trip loads
        self.assertEqual(ss["trip_history"][0]["confirmation"], "TS-KEEP")
        self.assertEqual(store.load("google-123")["trip_history"][0]["confirmation"], "TS-KEEP")

    def test_a_failed_save_is_retried_and_never_fatal(self):
        store = self.temp_store()
        ss = {"trip_history": [{"confirmation": "TS-1"}]}
        with patch("accounts.store", return_value=store), patch("accounts.current_user", return_value=ALEX):
            with patch.object(store, "save", side_effect=accounts.StorageError("Your latest changes couldn't be saved")):
                accounts.sync(ss)
            self.assertIn("couldn't be saved", ss["account_error"])
            accounts.sync(ss)  # next run saves it
        self.assertNotIn("account_error", ss)
        self.assertEqual(store.load("google-123")["trip_history"][0]["confirmation"], "TS-1")

    def test_another_person_signing_in_on_the_same_browser_sees_only_their_data(self):
        store = self.temp_store()
        store.save("other-9", "sam@example.com", {"trip_history": [{"confirmation": "TS-SAM"}]})
        ss = {"trip_history": [{"confirmation": "TS-ALEX"}]}
        with patch("accounts.store", return_value=store):
            with patch("accounts.current_user", return_value=ALEX):
                accounts.sync(ss)
            with patch("accounts.current_user", return_value={"id": "other-9", "email": "sam@example.com", "name": "Sam"}):
                accounts.sync(ss)
        self.assertEqual([t["confirmation"] for t in ss["trip_history"]], ["TS-SAM"])


class AccountAppTests(TempStoreMixin, DemoAppCase):
    """The real app with a stand-in for Google sign-in (Streamlit's test runner can't sign in)."""

    def setUp(self):
        self.store = self.temp_store()
        for context in (patch("accounts.store", return_value=self.store),
                        patch("accounts.current_user", return_value=ALEX)):
            context.start()
            self.addCleanup(context.stop)
        super().setUp()

    def new_device(self, page):
        app = AppTest.from_file(str(APP), default_timeout=15).run()
        app.switch_page(page).run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_locked_trip_is_on_the_homepage_from_another_device(self):
        self.add("flight-0")
        self.click("🔒 Lock in my trip")
        self.app.run()  # the next run saves it
        home = self.new_device("views/home.py")
        html = "\n".join(e.proto.body for e in home.get("html"))
        self.assertIn("1 trip", html)
        self.assertIn("AUS → CUN", html)

    def test_trip_fund_comes_back_after_a_restart_on_another_device(self):
        self.app.switch_page("views/fund.py").run()
        self.click("Create Trip Fund")
        self.click("Run this week's transfer")
        funded = self.metrics()["Funded"]
        bank._DEMO.clear()  # the server restarted
        fund_page = self.new_device("views/fund.py")
        self.assertEqual({m.label: m.value for m in fund_page.metric}["Funded"], funded)
        self.assertIn("saved to your account", "\n".join(c.value for c in fund_page.caption))
        next(b for b in fund_page.button if b.label == "Run this week's transfer").click().run()
        self.assertEqual(len(fund_page.exception), 0)

    def test_user_icon_shows_the_name_and_the_account_page_shows_sign_out(self):
        links = {p.proto.label: p.proto.page for p in self.app.get("page_link")}
        self.assertIn("Alex", links)  # the top-right user icon
        self.app.switch_page("views/account.py").run()
        self.assertIn("Sign out", [b.label for b in self.app.button])
        self.assertIn("Signed in as alex@example.com", "\n".join(c.value for c in self.app.caption))

    def test_storage_outage_keeps_the_app_working(self):
        with patch.object(self.store, "load", side_effect=accounts.StorageError("Your saved trips couldn't be reached right now.")):
            app = self.new_device("views/plan.py")
            next(b for b in app.button if b.label == "Start planning").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn("couldn't be reached", "\n".join(w.value for w in app.warning))


class PasswordTests(unittest.TestCase):
    def test_passwords_are_stored_only_as_salted_hashes(self):
        first, second = accounts.hash_password("correct horse"), accounts.hash_password("correct horse")
        self.assertNotIn("correct horse", first)
        self.assertNotEqual(first, second)  # a new salt every time
        self.assertTrue(first.startswith("scrypt$16384$8$1$"))
        self.assertTrue(accounts.check_password("correct horse", first))
        self.assertFalse(accounts.check_password("correct hors", first))
        for broken in (None, "", "plain-text", "scrypt$x$y$z$a$b", "md5$1$1$1$a$b"):
            self.assertFalse(accounts.check_password("anything", broken))


class RegisterAndSignInTests(TempStoreMixin, unittest.TestCase):
    def setUp(self):
        self.store = self.temp_store()
        accounts._failures.clear()
        self.addCleanup(accounts._failures.clear)

    def test_register_then_sign_in_with_any_email_capitalisation(self):
        user = accounts.register(" Alex@Example.com ", "longenough1", "longenough1", self.store)
        self.assertEqual(user, {"id": "email:alex@example.com", "email": "alex@example.com", "name": "alex"})
        self.assertEqual(accounts.sign_in("ALEX@example.com", "longenough1", self.store)["id"], "email:alex@example.com")
        self.assertNotIn("longenough1", self.store.password_hash("email:alex@example.com"))

    def test_register_rules(self):
        for email, password, confirm, message in (
                ("not-an-email", "longenough1", "longenough1", "valid email"),
                ("a@b.co", "short", "short", "8 to 128"),
                ("a@b.co", "x" * 129, "x" * 129, "8 to 128"),
                ("a@b.co", "longenough1", "different1", "don't match")):
            with self.subTest(message=message), self.assertRaisesRegex(accounts.AccountError, message):
                accounts.register(email, password, confirm, self.store)
        accounts.register("a@b.co", "longenough1", "longenough1", self.store)
        with self.assertRaisesRegex(accounts.AccountError, "already exists"):
            accounts.register("A@B.CO", "otherpass12", "otherpass12", self.store)
        self.assertTrue(accounts.check_password("longenough1", self.store.password_hash("email:a@b.co")))  # unchanged

    def test_wrong_details_get_one_message_and_repeated_failures_pause(self):
        accounts.register("a@b.co", "longenough1", "longenough1", self.store)
        messages = set()
        for email, password in (("a@b.co", "wrongpass1"), ("nobody@b.co", "longenough1"), ("bad", "x")):
            with self.assertRaises(accounts.AccountError) as caught:
                accounts.sign_in(email, password, self.store)
            messages.add(str(caught.exception))
        self.assertEqual(messages, {"That email and password don't match an account."})
        for _ in range(4):
            with self.assertRaises(accounts.AccountError):
                accounts.sign_in("a@b.co", "wrongpass1", self.store)
        with self.assertRaisesRegex(accounts.AccountError, "Too many tries"):
            accounts.sign_in("a@b.co", "longenough1", self.store)  # even the right password waits
        with patch("time.time", return_value=time.time() + accounts.LOCKOUT_SECONDS + 1):
            self.assertEqual(accounts.sign_in("a@b.co", "longenough1", self.store)["email"], "a@b.co")

    def test_email_and_google_accounts_never_collide(self):
        google_row = {"trip_history": [{"confirmation": "TS-G"}]}
        self.store.save("123456789", "a@b.co", google_row)  # a Google account (id = Google's number)
        accounts.register("a@b.co", "longenough1", "longenough1", self.store)
        self.assertEqual(self.store.load("123456789"), google_row)
        self.assertIsNone(self.store.password_hash("123456789"))

    def test_supabase_create_user_reports_taken_emails(self):
        store = accounts.SupabaseStore("https://abc.supabase.co", "sb_secret_xyz")
        for status, created in ((201, True), (409, False)):
            with self.subTest(status=status), patch("requests.request", return_value=MagicMock(status_code=status)) as call:
                self.assertEqual(store.create_user("email:a@b.co", "a@b.co", "scrypt$..."), created)
                self.assertEqual(call.call_args.kwargs["json"]["password_hash"], "scrypt$...")
        with patch("requests.request", return_value=MagicMock(status_code=500)), self.assertRaises(accounts.StorageError):
            store.create_user("email:a@b.co", "a@b.co", "x")
        reply = MagicMock(status_code=200)
        reply.json.return_value = [{"password_hash": "scrypt$stored"}]
        with patch("requests.request", return_value=reply) as call:
            self.assertEqual(store.password_hash("email:a@b.co"), "scrypt$stored")
            self.assertEqual(call.call_args.kwargs["params"]["select"], "password_hash")


class AccountPageTests(TempStoreMixin, DemoAppCase):
    """Create an account on the Account page, use the app, sign out, sign back in."""

    def setUp(self):
        self.store = self.temp_store()
        accounts._failures.clear()
        context = patch("accounts.store", return_value=self.store)
        context.start()
        self.addCleanup(context.stop)
        super().setUp()

    def open_account(self):
        self.app.switch_page("views/account.py").run()
        self.assertEqual(len(self.app.exception), 0)

    def submit(self, label):
        next(b for b in self.app.button if b.label == label).click().run()
        self.assertEqual(len(self.app.exception), 0)

    def register(self, email="sam@example.com", password="vacation123"):
        self.open_account()
        self.app.text_input(key="register_email").input(email)
        self.app.text_input(key="register_password").input(password)
        self.app.text_input(key="register_confirm").input(password)
        self.submit("Create account")

    def test_signed_out_icon_says_account_and_the_page_offers_both_forms(self):
        self.assertIn("Account", [p.proto.label for p in self.app.get("page_link")])
        self.open_account()
        labels = [b.label for b in self.app.button]
        self.assertIn("Sign in", labels)
        self.assertIn("Create account", labels)
        self.assertNotIn("Continue with Google", labels)  # only when Google sign-in is set up

    def test_create_account_lock_a_trip_sign_out_and_back_in(self):
        self.register()
        self.assertIn("Hi, sam 👋", [h.value for h in self.app.header])
        self.assertIn("sam", [p.proto.label for p in self.app.get("page_link")])  # the icon shows the name
        self.app.switch_page("views/plan.py").run()
        self.click("Start planning")
        self.add("flight-0")
        self.click("🔒 Lock in my trip")
        self.open_account()
        self.assertEqual({m.label: m.value for m in self.app.metric}["Locked-in trips"], "1")
        self.submit("Sign out")
        self.assertIn("Your FareWell account", [h.value for h in self.app.header])
        self.assertEqual(self.app.session_state["trip_history"] if "trip_history" in self.app.session_state else [], [])
        self.app.text_input(key="signin_email").input("SAM@example.com")
        self.app.text_input(key="signin_password").input("vacation123")
        self.submit("Sign in")
        self.assertEqual({m.label: m.value for m in self.app.metric}["Locked-in trips"], "1")

    def test_wrong_password_and_duplicate_account_messages(self):
        self.register()
        self.submit("Sign out")
        self.app.text_input(key="signin_email").input("sam@example.com")
        self.app.text_input(key="signin_password").input("not-the-password")
        self.submit("Sign in")
        self.assertIn("don't match an account", "\n".join(e.value for e in self.app.error))
        self.app.text_input(key="register_email").input("sam@example.com")
        self.app.text_input(key="register_password").input("another12345")
        self.app.text_input(key="register_confirm").input("another12345")
        self.submit("Create account")
        self.assertIn("already exists", "\n".join(e.value for e in self.app.error))

    def test_google_button_appears_only_when_configured(self):
        with patch("accounts.auth_configured", return_value=True):
            self.open_account()
        self.assertIn("Continue with Google", [b.label for b in self.app.button])


if __name__ == "__main__":
    unittest.main()
