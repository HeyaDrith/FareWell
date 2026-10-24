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
        self.assertEqual(set(rows[0]), {"airline", "price", "duration_min", "stops",
                                        "flight_numbers", "departs"})
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
        self.assertEqual(rows, [{"name": "Complete", "per_night": 100.0, "total": 750.0, "rating": 4.5,
                                 "property_token": "", "website": ""}])

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


class BookingLinkTests(unittest.TestCase):
    def test_links_go_to_google_travel_with_trip_details(self):
        flight = travel.flight_booking_url("American", "DFW", "CUN", "2027-01-22", "2027-01-29", ["AA 1190"])
        self.assertTrue(flight.startswith("https://www.google.com/travel/flights/search?tfs="))
        self.assertTrue(flight.endswith("&hl=en&curr=USD"))
        self.assertEqual(decode_tfs(flight), {
            "legs": [("2027-01-22", "DFW", "CUN", ["AA"]), ("2027-01-29", "CUN", "DFW", ["AA"])],
            "passengers": 1, "seat": 1, "trip": 1})
        # Without a flight number (sample data) the link still opens the route and dates.
        sample = travel.flight_booking_url("Southwest", "AUS", "CUN", "2027-01-22", "2027-01-29")
        self.assertEqual(decode_tfs(sample)["legs"][0], ("2027-01-22", "AUS", "CUN", []))
        # Same layout as a published Google Flights example (date, then from/to airports).
        self.assertTrue(sample.split("tfs=")[1].startswith("CBwQAhoeEgoyMDI3LTAxLTIyagcIARID"))
        hotel = travel.hotel_booking_url("Seaside Budget Inn", "Cancun", "2027-01-22", "2027-01-29")
        self.assertTrue(hotel.startswith("https://www.google.com/travel/hotels?q=Seaside+Budget+Inn+Cancun"))
        self.assertIn("checkin=2027-01-22", hotel)
        self.assertEqual(travel.place_url(" Tacos & more Cancun "),
                         "https://www.google.com/maps/search/?api=1&query=Tacos+%26+more+Cancun")

    def test_live_flights_count_stops(self):
        reply = {"best_flights": [{"price": 300, "total_duration": 300,
                                   "flights": [{"airline": "A"}, {"airline": "A"}]}]}
        with patch.dict(os.environ, {"SERPAPI_KEY": "test-only-not-a-key"}), \
             patch("travel._client", return_value=reply):
            rows = travel.search_flights("AUS", "CUN", "2027-01-22", "2027-01-29")
        self.assertEqual(rows[0]["stops"], 1)


def decode_tfs(url: str) -> dict:
    """Minimal protobuf reader for the Google Flights tfs links built by travel.py."""
    import base64
    from urllib.parse import parse_qs, urlparse

    def fields(data: bytes):
        i = 0
        while i < len(data):
            key, i = varint(data, i)
            if key & 7 == 0:
                value, i = varint(data, i)
            else:
                size, i = varint(data, i)
                value, i = data[i:i + size], i + size
            yield key >> 3, value

    def varint(data: bytes, i: int):
        shift = result = 0
        while True:
            byte = data[i]
            i += 1
            result |= (byte & 0x7F) << shift
            shift += 7
            if not byte & 0x80:
                return result, i

    token = parse_qs(urlparse(url).query)["tfs"][0]
    out = {"legs": []}
    for field, value in fields(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))):
        if field == 3:
            leg = dict(airlines=[])
            for f, v in fields(value):
                if f == 2:
                    leg["date"] = v.decode()
                elif f == 6:
                    leg["airlines"].append(v.decode())
                elif f in (13, 14):
                    leg["from" if f == 13 else "to"] = dict(fields(v))[2].decode()
            out["legs"].append((leg["date"], leg["from"], leg["to"], leg["airlines"]))
        elif field in (8, 9, 19):
            out[{8: "passengers", 9: "seat", 19: "trip"}[field]] = value
    return out
