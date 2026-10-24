import os
from datetime import date, timedelta
from unittest.mock import Mock, patch

import bank
from app_support import DemoAppCase


class AppIntegrationTests(DemoAppCase):
    def test_trip_edits_block_old_prices_until_researched(self):
        self.click("Create my Trip Fund")
        departure = next(widget.value for widget in self.app.date_input if widget.label == "Depart")
        return_widget = next(widget for widget in self.app.date_input if widget.label == "Return")
        return_widget.set_value(departure + timedelta(days=2)).run()
        self.assertIn("Search prices again", self.visible_text())
        self.assertFalse(any("transfer" in button.label.lower() for button in self.app.button))
        self.click("Search prices")
        self.assertEqual(self.app.metric[0].value, "$790")  # 412 flight + 2*89 hotel + 200 extras
        self.assertEqual(len(bank._DEMO), 1)  # Same wallet, recalculated trip.

    def test_cleared_and_invalid_travel_dates_block_funding(self):
        departure = next(widget.value for widget in self.app.date_input if widget.label == "Depart")
        for label, value, message in (("Depart", None, "Choose a departure"),
                                      ("Depart", date.today() - timedelta(days=1), "today or later"),
                                      ("Return", departure, "Return must be after"),
                                      ("Return", None, "Choose a return")):
            with self.subTest(label=label, value=value):
                next(widget for widget in self.app.date_input if widget.label == "Depart").set_value(departure)
                next(widget for widget in self.app.date_input if widget.label == "Return").set_value(departure + timedelta(days=7))
                next(widget for widget in self.app.date_input if widget.label == label).set_value(value).run()
                self.assertEqual(len(self.app.exception), 0)
                self.assert_funding_blocked(message)

    def test_empty_search_replaces_previous_results(self):
        with patch("travel.search_flights", return_value=[]), patch("travel.search_hotels", return_value=[]):
            self.click("Search prices")
        self.assertIn("No matching flights or hotels", self.visible_text())
        self.assertEqual(len(self.app.metric), 0)
        self.assertFalse(any(button.label == "Create my Trip Fund" for button in self.app.button))

    def test_fallback_redacts_error_and_stays_labeled_on_rerun(self):
        with patch.dict(os.environ, {"SERPAPI_KEY": "test-only-not-a-key"}), \
             patch("travel._client", side_effect=RuntimeError("https://example.test/?api_key=secret-sentinel")):
            self.app.toggle[0].set_value(False).run()
            self.click("Search prices")
            self.click("Create my Trip Fund")
            self.assertIn("sample prices, not live quotes", self.visible_text())
            self.assertNotIn("secret-sentinel", self.visible_text())
            self.assertEqual(self.app.metric[0].value, "$1,235")

    def test_mocked_live_search_to_bank_submission_and_mode_switch(self):
        # Real adapters and UI with provider-shaped replies; never uses actual keys.
        bank_calls = []

        def service(method, url, **kwargs):
            body = kwargs.get("json")
            bank_calls.append((method, url, body))
            if method == "GET":
                result = {"balance": 3000 if url.endswith("/checking") else 0}
            elif url.endswith("/customers"):
                result = {"objectCreated": {"_id": "customer"}}
            elif url.endswith("/accounts"):
                result = {"objectCreated": {"_id": "checking" if body["type"] == "Checking" else "fund"}}
            else:
                result = {"objectCreated": {"_id": "transfer", "status": "pending"}}
            response = Mock(status_code=201 if method == "POST" else 200)
            response.json.return_value = result
            return response

        def prices(params):
            if params["engine"] == "google_flights":
                return {"best_flights": [{"price": 500, "flights": [{"airline": "Example Air"}], "total_duration": 180}]}
            return {"properties": [{"name": "Example Hotel", "rate_per_night": {"extracted_lowest": 90},
                                     "total_rate": {"extracted_lowest": 630}, "overall_rating": 4.0}]}

        self.click("Create my Trip Fund")
        demo_wallet = dict(self.app.session_state.wallets["demo"]["accounts"])
        with patch.dict(os.environ, {"SERPAPI_KEY": "test-only-not-a-key", "NESSIE_API_KEY": "test-only-not-a-key"}), \
             patch("travel._client", side_effect=prices), patch("requests.request", side_effect=service):
            self.app.toggle[0].set_value(False).run()
            self.click("Search prices")
            self.assertEqual(self.app.metric[0].value, "$1,330")
            self.click("Create my Trip Fund")
            self.set_deadline(date.today() + timedelta(days=28))
            self.click("Run this week's transfer ($332.50)")
            self.assertIn("Further transfers are paused", self.visible_text())
            self.app.run()
            transfers = [call for call in bank_calls if call[1].endswith("/transfers")]
            self.assertEqual(len(transfers), 1)
            self.assertEqual(transfers[0][2]["amount"], 332.50)
            self.assertEqual(transfers[0][2]["payee_id"], "fund")
            self.app.toggle[0].set_value(True).run()
            self.click("Search prices")
            self.assertEqual(self.app.session_state.wallets["demo"]["accounts"], demo_wallet)
            self.assertNotIn("Further transfers are paused", self.visible_text())
            self.assertEqual(bank.get_balance(demo_wallet["fund_id"], True), 0)
            self.app.toggle[0].set_value(False).run()
            self.click("Search prices")
            self.assertIn("Further transfers are paused", self.visible_text())
            self.assertEqual(len([call for call in bank_calls if call[1].endswith("/transfers")]), 1)
