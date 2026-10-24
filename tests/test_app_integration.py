"""Exercise the real Streamlit flow: budget -> picks -> savings -> final cost.

Sample travel data: flights $412 / $438 / $521 (typical $438); hotels $89 / $132 / $215
per night x 7 nights = $623 / $924 / $1,505 (typical $924). Default budget $1,500.
"""
import os
import unittest
from datetime import date, timedelta
from unittest.mock import Mock, patch

import bank
from app_support import DemoAppCase


class AppTripTests(DemoAppCase):
    def test_full_demo_trip_tracks_spending_savings_and_final_cost(self):
        self.assertEqual(self.metrics(), {"Budget": "$1,500", "Spent": "$0",
                                          "Remaining": "$1,500", "Saved": "$0"})
        self.add("flight-0")   # $412, saves $26
        self.add("hotel-0")    # $623, saves $301
        self.add_extra("Dinner at Taqueria", 60.5)  # rounds up to $61 (whole dollars)
        self.assertEqual(self.metrics(), {"Budget": "$1,500", "Spent": "$1,096",
                                          "Remaining": "$404", "Saved": "$327"})
        self.assertIn("Final trip cost: $1,096", self.plain_text())
        self.assertIn("Food: Dinner at Taqueria", self.plain_text())

        hotel_remove = [b for b in self.app.button if b.label == "✕"][1]
        hotel_remove.click().run()
        self.assertEqual(self.metrics()["Spent"], "$473")
        self.assertEqual(self.metrics()["Saved"], "$26")

    def test_options_show_fit_and_savings_labels(self):
        text = self.plain_text()
        self.assertIn("Typical round-trip price: $438", text)
        self.assertIn("$412 · ✅ fits · 💰 saves $26", text)
        self.assertIn("$1,505 total · ⚠️ $5 over", text)

    def test_over_budget_warning(self):
        self.add("flight-2")  # $521
        self.add("hotel-2")   # $1,505
        self.assertIn("You're $526 over budget", self.plain_text())

    def test_trip_edits_require_a_new_plan(self):
        self.add("flight-0")
        self.app.number_input[0].set_value(2000).run()
        self.assertIn("Trip details changed", self.visible_text())
        self.assertEqual(self.add_buttons(), [])
        self.click("Start planning")
        self.assertEqual(self.metrics()["Budget"], "$2,000")
        self.assertEqual(self.metrics()["Spent"], "$0")  # fresh trip

    def test_invalid_dates_block_planning(self):
        departure = next(w.value for w in self.app.date_input if w.label == "Depart")
        for label, value, message in (("Depart", None, "Choose a departure"),
                                      ("Depart", date.today() - timedelta(days=1), "today or later"),
                                      ("Return", departure, "Return must be after"),
                                      ("Return", None, "Choose a return")):
            with self.subTest(label=label, value=value):
                next(w for w in self.app.date_input if w.label == "Depart").set_value(departure)
                next(w for w in self.app.date_input if w.label == "Return").set_value(departure + timedelta(days=7))
                next(w for w in self.app.date_input if w.label == label).set_value(value).run()
                self.assertEqual(len(self.app.exception), 0)
                self.assertIn(message, self.visible_text())
                self.assertEqual(self.add_buttons(), [])
                start = next(b for b in self.app.button if b.label == "Start planning")
                self.assertTrue(start.disabled)

    def test_empty_search_shows_message(self):
        with patch("travel.search_flights", return_value=[]), patch("travel.search_hotels", return_value=[]):
            self.click("Start planning")
        self.assertIn("No matching flights or hotels", self.visible_text())
        self.assertEqual(self.add_buttons(), [])

    def test_search_fallback_redacts_error_and_stays_labeled(self):
        with patch.dict(os.environ, {"SERPAPI_KEY": "test-only-not-a-key"}), \
             patch("travel._client", side_effect=RuntimeError("https://example.test/?api_key=secret-sentinel")):
            self.app.toggle[0].set_value(False).run()
            self.click("Start planning")
            self.assertIn("sample prices, not live quotes", self.visible_text())
            self.add("flight-0")
            self.assertIn("sample prices, not live quotes", self.visible_text())
            self.assertNotIn("secret-sentinel", self.visible_text())

    def test_bank_failures_are_safe_and_do_not_crash(self):
        with patch("bank.create_trip", side_effect=RuntimeError("secret-sentinel")):
            self.app.number_input[0].set_value(1600).run()
            self.click("Start planning")
        self.assertIn("didn't respond", self.visible_text())
        self.assertNotIn("secret-sentinel", self.visible_text())
        self.click("Start planning")
        with patch("bank.record_pick", side_effect=bank.BankError("Nessie could not confirm the request.")):
            self.add("flight-0")
        self.assertIn("could not confirm", self.visible_text())
        self.assertEqual(self.metrics()["Spent"], "$0")

    def test_dollar_amounts_are_escaped_for_markdown(self):
        self.add("flight-0")
        self.add_extra("Snacks $5 and $6", 11)
        for element in list(self.app.markdown) + list(self.app.success) + list(self.app.caption):
            text = str(element.value)
            self.assertNotRegex(text, r"(?<!\\)\$", f"unescaped $ in: {text}")

    def test_mocked_live_nessie_flow_and_mode_switch(self):
        calls = []
        records = {"purchases": [], "deposits": []}

        def service(method, url, **kwargs):
            body = kwargs.get("json")
            calls.append((method, url.split("nessieisreal.com", 1)[1], body))
            path = calls[-1][1]
            response = Mock(status_code=201 if method == "POST" else 200)
            if method == "POST" and path == "/customers":
                result = {"objectCreated": {"_id": "cust"}}
            elif method == "POST" and path.endswith("/accounts"):
                result = {"objectCreated": {"_id": "budget" if body["type"] == "Checking" else "savings"}}
            elif method == "POST" and path == "/merchants":
                result = {"objectCreated": {"_id": f"m-{body['category']}"}}
            elif method == "POST" and path.endswith("/purchases"):
                record = {**body, "_id": f"p{len(records['purchases']) + 1}"}
                records["purchases"].insert(0, record)  # Nessie lists newest first
                result = {"objectCreated": record}
            elif method == "POST" and path.endswith("/deposits"):
                records["deposits"].insert(0, {**body, "_id": f"d{len(records['deposits']) + 1}"})
                result = {"objectCreated": records["deposits"][0]}
            elif method == "GET" and path.endswith("/purchases"):
                result = list(records["purchases"])
            elif method == "GET" and path.endswith("/deposits"):
                result = list(records["deposits"])
            else:
                raise AssertionError(f"unexpected call {method} {path}")
            response.json.return_value = result
            return response

        with patch.dict(os.environ, {"NESSIE_API_KEY": "test-only-not-a-key"}), \
             patch("requests.request", side_effect=service):
            self.app.toggle[1].set_value(False).run()
            self.assertIn("Trip details changed", self.visible_text())
            self.click("Start planning")
            self.assertIn("Nessie sandbox", self.visible_text())
            self.add("flight-0")
            self.add("hotel-0")
            self.add_extra("Dinner", 40.5)
            self.assertEqual(self.metrics(), {"Budget": "$1,500", "Spent": "$1,076",
                                              "Remaining": "$424", "Saved": "$327"})
            posts = [(p, b) for m, p, b in calls if m == "POST" and p.endswith(("/purchases", "/deposits"))]
            self.assertEqual([(p.rsplit("/", 1)[1], b["amount"]) for p, b in posts],
                             [("purchases", 412), ("deposits", 26), ("purchases", 623),
                              ("deposits", 301), ("purchases", 41)])
            self.assertTrue(all(b["status"] == "completed" for _, b in posts))
            self.assertEqual(sum(1 for m, p, _ in calls if p == "/merchants"), 3)  # Flight, Hotel, Food

            hotel_remove = [b for b in self.app.button if b.label == "✕"][1]
            hotel_remove.click().run()
            self.assertEqual(self.metrics()["Spent"], "$453")
            self.assertEqual(self.metrics()["Saved"], "$26")
            self.assertFalse(any(m == "DELETE" for m, _, _ in calls))  # Nessie can't delete

            live_calls = len(calls)
            self.app.toggle[1].set_value(True).run()
            self.click("Start planning")
            self.add("flight-0")
            self.assertEqual(len(calls), live_calls)  # demo trip never reaches Nessie
            self.assertIn("simulated demo money", self.visible_text())


if __name__ == "__main__":
    unittest.main()
