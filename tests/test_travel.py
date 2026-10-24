import os
import unittest
from unittest.mock import patch

import travel


class TravelTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"SERPAPI_KEY": "test-only-not-a-key"})
        env.start()
        self.addCleanup(env.stop)
        network = patch("requests.sessions.Session.request", side_effect=AssertionError("External HTTP forbidden"))
        self.request = network.start()
        self.addCleanup(network.stop)
        self.addCleanup(self.request.assert_not_called)

    def test_flight_prices_are_sorted_and_invalid_quotes_are_skipped(self):
        data = {"best_flights": [{"price": price, "flights": [{"airline": "Example Air"}], "total_duration": 180}
                                 for price in (450, -1, None, "NaN", 0, 310.25)]}
        with patch("travel._client", return_value=data) as client:
            rows = travel.search_flights("AUS", "CUN", "2027-01-01", "2027-01-08")
        self.assertEqual([row["price"] for row in rows], [310.25, 450.0])
        self.assertEqual(set(rows[0]), {"airline", "price", "duration_min"})
        self.assertEqual(client.call_args.args[0]["currency"], "USD")

    def test_hotels_use_total_stay_price_and_omit_incomplete_quotes(self):
        data = {"properties": [
            {"name": "Complete", "rate_per_night": {"extracted_lowest": 100},
             "total_rate": {"extracted_lowest": 750}, "overall_rating": 4.5},
            {"name": "Nightly only", "rate_per_night": {"extracted_lowest": 10}},
            {"name": "Invalid", "rate_per_night": {"extracted_lowest": 100},
             "total_rate": {"extracted_lowest": "NaN"}},
            {"name": "Missing", "rate_per_night": None, "total_rate": None},
        ]}
        with patch("travel._client", return_value=data):
            rows = travel.search_hotels("Cancun", "2027-01-01", "2027-01-08")
        self.assertEqual(rows, [{"name": "Complete", "per_night": 100.0, "total": 750.0, "rating": 4.5}])

    def test_demo_hotel_total_uses_requested_nights(self):
        for nights in (1, 5, 7):
            rows = travel.search_hotels("Cancun", "2027-01-01", f"2027-01-{nights + 1:02}", True)
            self.assertEqual(rows[0]["total"], 89 * nights)

    def test_invalid_dates_fail_before_service_call(self):
        with patch("travel._client") as client:
            for end in ("2027-01-01", "2026-12-31", "invalid"):
                with self.subTest(end=end), self.assertRaises(ValueError):
                    travel.search_hotels("Cancun", "2027-01-01", end)
            client.assert_not_called()

    def test_service_error_payload_is_sanitized(self):
        with patch("serpapi.GoogleSearch") as search:
            search.return_value.get_dict.return_value = {"error": "secret-sentinel"}
            with self.assertRaises(RuntimeError) as caught:
                travel.search_hotels("Cancun", "2027-01-01", "2027-01-08")
            self.assertNotIn("secret-sentinel", str(caught.exception))
