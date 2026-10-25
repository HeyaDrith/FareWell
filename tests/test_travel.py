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
                                        "flight_numbers", "departs", "route", "logo"})
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
                                 "property_token": "", "website": "", "lat": None, "lon": None, "image": ""}])

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


class MapDataTests(unittest.TestCase):
    def search(self, reply, kind="flights"):
        with patch.dict(os.environ, {"SERPAPI_KEY": "test-only-not-a-key"}), \
             patch("travel._client", return_value=reply):
            if kind == "flights":
                return travel.search_flights("AUS", "CUN", "2027-01-22", "2027-01-29")
            return travel.search_hotels("hotels in Cancun", "2027-01-22", "2027-01-29")

    def test_flight_route_includes_layovers(self):
        legs = [{"airline": "A", "departure_airport": {"id": "AUS"}, "arrival_airport": {"id": "MEX"}},
                {"airline": "A", "departure_airport": {"id": "MEX"}, "arrival_airport": {"id": "CUN"}}]
        rows = self.search({"best_flights": [{"price": 300, "total_duration": 300, "flights": legs}]})
        self.assertEqual(rows[0]["route"], ["AUS", "MEX", "CUN"])

    def test_flight_route_with_a_missing_airport_is_dropped(self):
        legs = [{"airline": "A", "departure_airport": {"id": "AUS"}, "arrival_airport": {}}]
        rows = self.search({"best_flights": [{"price": 300, "total_duration": 300, "flights": legs}]})
        self.assertEqual(rows[0]["route"], [])

    def test_hotel_coordinates_are_parsed_and_invalid_ones_dropped(self):
        def hotel(name, gps):
            return {"name": name, "rate_per_night": {"extracted_lowest": 90},
                    "total_rate": {"extracted_lowest": 630}, "gps_coordinates": gps}
        rows = self.search({"properties": [
            hotel("Good", {"latitude": 21.12, "longitude": -86.75}),
            hotel("Out of range", {"latitude": 123, "longitude": -86.75}),
            hotel("Not a number", {"latitude": "x", "longitude": None}),
            hotel("Missing", None)]}, kind="hotels")
        self.assertEqual({r["name"]: (r["lat"], r["lon"]) for r in rows},
                         {"Good": (21.12, -86.75), "Out of range": (None, None),
                          "Not a number": (None, None), "Missing": (None, None)})

    def test_airline_logo_and_hotel_photo_keep_only_https_links(self):
        flights = self.search({"best_flights": [
            {"price": 300, "total_duration": 200, "airline_logo": "https://img.example/wn.png", "flights": [{}]},
            {"price": 310, "total_duration": 200, "flights": [{"airline_logo": "https://img.example/aa.png"}]},
            {"price": 320, "total_duration": 200, "airline_logo": "javascript:alert(1)", "flights": [{}]}]})
        self.assertEqual([f["logo"] for f in flights], ["https://img.example/wn.png", "https://img.example/aa.png", ""])

        def hotel(name, images):
            return {"name": name, "rate_per_night": {"extracted_lowest": 90},
                    "total_rate": {"extracted_lowest": 630}, "images": images}
        rows = self.search({"properties": [
            hotel("Photo", [{"thumbnail": "http://insecure.example/a.jpg"}, {"thumbnail": "https://img.example/b.jpg"}]),
            hotel("Original only", [{"original_image": "https://img.example/c.jpg"}]),
            hotel("None", None), hotel("Junk", ["not a dict"])]}, kind="hotels")
        self.assertEqual({r["name"]: r["image"] for r in rows},
                         {"Photo": "https://img.example/b.jpg", "Original only": "https://img.example/c.jpg",
                          "None": "", "Junk": ""})

    def test_hotel_search_is_the_destination_city_plus_an_optional_area(self):
        self.assertEqual(travel.hotel_query("CUN"), "hotels in Cancún")
        self.assertEqual(travel.hotel_query("cun", "  near   the beach "), "hotels in Cancún near the beach")
        for repeat in ("Cancun", "cancún", "hotels in Cancun", "Hotels", ""):  # adds nothing
            with self.subTest(area=repeat):
                self.assertEqual(travel.hotel_query("CUN", repeat), "hotels in Cancún")
        self.assertEqual(len(travel.hotel_query("CUN", "x" * 500)), len("hotels in Cancún ") + travel.MAX_AREA_CHARS)
        self.assertEqual(travel.hotel_query("CDG"), "hotels in Paris")  # not "Paris (Roissy-en-France, ...)"
        self.assertEqual(travel.hotel_query("CDG", "Paris"), "hotels in Paris")

    def test_airport_lookup(self):
        aus = travel.airport_location("aus")
        self.assertEqual((aus["code"], aus["city"]), ("AUS", "Austin"))
        self.assertAlmostEqual(aus["lat"], 30.19, places=1)
        self.assertAlmostEqual(aus["lon"], -97.66, places=1)
        self.assertIsNone(travel.airport_location("ZZZ"))
        self.assertIsNone(travel.airport_location(""))

    def test_sample_data_has_routes_and_hotel_locations(self):
        flights = travel.search_flights("AUS", "CUN", "2027-01-22", "2027-01-29", True)
        self.assertEqual([f["route"] for f in flights], [["AUS", "CUN"], ["AUS", "CUN"], ["AUS", "DFW", "CUN"]])
        hotels = travel.search_hotels("hotels in Cancun", "2027-01-22", "2027-01-29", True)
        self.assertTrue(all(h["lat"] and h["lon"] for h in hotels))


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


class EncodingTests(unittest.TestCase):
    def test_demo_data_loads_without_a_utf8_system_default(self):
        """Windows reads files as cp1252 by default; demo data must still load (e.g. "Sŏndŏng-ni")."""
        import subprocess
        import sys
        from pathlib import Path

        root = Path(travel.__file__).resolve().parent
        env = {**os.environ, "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C", "LANG": "C"}
        script = ("import travel\n"
                  "for name in ('airports.json', 'flights.json', 'hotels.json'):\n"
                  "    travel._load_demo(name)\n"
                  "print(travel.airport_location('CUN') is not None)\n")
        result = subprocess.run([sys.executable, "-c", script], cwd=root, env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True")
