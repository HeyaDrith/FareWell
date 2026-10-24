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

    def test_recommendations_badges_and_budget_split(self):
        text = self.plain_text()
        self.assertIn("Suggested split of what's left: ✈️ Flights $525 · 🏨 Hotel $600 · "
                      "🍽️ Food $225 · 🎟️ Activities $150 (food ≈ $28/day)", text)
        self.assertIn("Recommended: Volaris** ($438), best quality that fits your $525 flight budget.", text)
        self.assertIn("**Southwest** · 3h 15m · Nonstop  \n💰 Cheapest", text)
        self.assertIn("**American** · 4h 45m · 1 stop", text)
        # No hotel fits the $600 hotel share yet: recommend the cheapest, offer the upgrade.
        self.assertIn("nothing fits your $600 hotel budget, so this is the cheapest. "
                      "✨ Upgrade: **Azure Resort & Spa** for $882 more.", text)
        self.add("flight-1")  # Volaris $438 -> $1,062 left; hotel share rolls up to $654
        self.assertIn("Recommended: Seaside Budget Inn** ($623), best quality that fits your "
                      "$654 hotel budget.", self.plain_text())
        self.assertNotIn("✈️ Flights", self.plain_text())

    def test_booking_buttons_on_picks(self):
        self.add("flight-0")
        self.add("hotel-0")
        self.add_extra("Taqueria El Fogon", 30)
        buttons = self.link_buttons()
        self.assertEqual([label for label, _ in buttons],
                         ["Book on Google Flights ↗", "Find this hotel ↗", "Open in Google Maps ↗"])
        self.assertTrue(buttons[0][1].startswith("https://www.google.com/travel/flights/search?tfs="))
        self.assertTrue(buttons[1][1].startswith("https://www.google.com/travel/hotels?q=Seaside+Budget+Inn+Cancun"))
        self.assertEqual(buttons[2][1], "https://www.google.com/maps/search/?api=1&query=Taqueria+El+Fogon+Cancun")

    def test_live_listings_link_to_the_exact_hotel_and_flight(self):
        flights = [{"airline": "Southwest", "price": 400.0, "duration_min": 195, "stops": 0,
                    "flight_numbers": ["WN 1234"], "departs": "2027-01-22 07:05"}]
        hotels = [{"name": "Real Hotel", "per_night": 90.0, "total": 630.0, "rating": 4.4,
                   "property_token": "ChgI56qez/Nac0", "website": "https://realhotel.example/"}]
        with patch("travel.search_flights", return_value=flights), patch("travel.search_hotels", return_value=hotels):
            self.app.number_input[0].set_value(1600).run()
            self.click("Start planning")
        self.assertIn("**Southwest** · WN 1234, departs 7:05 AM · 3h 15m · Nonstop", self.plain_text())
        self.add("flight-0")
        self.add("hotel-0")
        self.assertIn("Southwest flight AUS→CUN (WN 1234, departs 7:05 AM)", self.plain_text())
        self.assertEqual(self.link_buttons()[1:], [
            ("Book this hotel ↗", "https://www.google.com/travel/hotels/entity/ChgI56qez%2FNac0"),
            ("Hotel website ↗", "https://realhotel.example/")])
        from test_travel import decode_tfs
        self.assertEqual(decode_tfs(self.link_buttons()[0][1])["legs"][0][3], ["WN"])  # airline filter

    def test_picked_category_recommends_a_swap_within_budget(self):
        self.add("flight-0")  # Southwest $412
        self.add("hotel-0")   # $623 -> $465 left
        # Swapping the flight frees $412: (465 + 412) x 0.35 / (0.35 + 0.15 + 0.10) = $512
        self.assertIn("Recommended: Volaris** ($438), best quality that fits your $512 flight budget.",
                      self.plain_text())

    def test_lock_in_shows_confirmation_and_freezes_picks(self):
        lock = next(b for b in self.app.button if b.label == "🔒 Lock in my trip")
        self.assertTrue(lock.disabled)  # nothing picked yet
        self.add("flight-0")
        self.add("hotel-0")
        self.click("🔒 Lock in my trip")
        text = self.plain_text()
        self.assertRegex(text, r"Trip locked in!\*\* Confirmation \*\*TS-[0-9A-F]{6}\*\*")
        self.assertIn("total $1,035 · saved $327", text)
        self.assertIn("nothing is reserved or charged", text)
        self.assertTrue(all(b.disabled for b in self.add_buttons()))
        self.assertFalse(any(b.label == "✕" for b in self.app.button))
        self.assertIn("**Flight: Southwest flight AUS→CUN** · $412", self.plain_text())
        self.assertEqual([label for label, _ in self.link_buttons()],
                         ["Book on Google Flights ↗", "Find this hotel ↗"])  # shown once, in the confirmation
        self.assertIn("sample listings", self.plain_text())
        self.click("Unlock to make changes")
        self.assertFalse(any(b.disabled for b in self.add_buttons()))
        self.add("flight-0")
        self.assertEqual(self.metrics()["Spent"], "$1,447")

    def test_cannot_lock_while_over_budget(self):
        self.add("flight-2")
        self.add("hotel-2")
        lock = next(b for b in self.app.button if b.label == "🔒 Lock in my trip")
        self.assertTrue(lock.disabled)
        self.assertIn("Get under budget first", self.visible_text())


if __name__ == "__main__":
    unittest.main()
