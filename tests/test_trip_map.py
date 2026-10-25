"""Map data: flight paths from airport codes and hotel pins near the destination."""
import math
import unittest

import trip_map
import travel


class FlightPathTests(unittest.TestCase):
    def test_route_with_layover_is_drawn_in_order(self):
        stops = trip_map.flight_path(["AUS", "MEX", "CUN"], "AUS", "CUN")
        self.assertEqual([s["code"] for s in stops], ["AUS", "MEX", "CUN"])

    def test_missing_or_mismatched_route_falls_back_to_direct_line(self):
        for route in ([], ["DFW", "CUN"], ["AUS", "MIA"]):
            with self.subTest(route=route):
                self.assertEqual([s["code"] for s in trip_map.flight_path(route, "AUS", "CUN")], ["AUS", "CUN"])

    def test_unknown_airport_draws_nothing(self):
        self.assertEqual(trip_map.flight_path([], "AUS", "ZZZ"), [])
        self.assertEqual(trip_map.flight_path(["AUS", "ZZZ", "CUN"], "AUS", "CUN"), [])

    def test_view_fits_every_airport(self):
        stops = trip_map.flight_path(["AUS", "CUN"], "AUS", "CUN")
        view = trip_map._view([[s["lon"], s["lat"]] for s in stops], max_zoom=8)
        self.assertAlmostEqual(view.zoom, 4.19, places=1)  # the north-south span decides it
        self.assertAlmostEqual(view.latitude, 25.75, places=1)  # Mercator midpoint
        self.assertAlmostEqual(view.longitude, (stops[0]["lon"] + stops[1]["lon"]) / 2, places=3)
        # Every point lands inside the chart (inside the padding) at that zoom.
        scale = 512 * 2 ** view.zoom
        def y(lat):
            return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / (2 * math.pi) * scale
        for s in stops:
            self.assertLess(abs(y(s["lat"]) - y(view.latitude)), trip_map.MAP_HEIGHT / 2)
            self.assertLess(abs(s["lon"] - view.longitude) / 360 * scale, 560 / 2)
        single = trip_map._view([[-86.75, 21.13]], max_zoom=13)
        self.assertEqual((single.latitude, single.longitude, single.zoom), (21.13, -86.75, 11))

    def test_view_fits_routes_over_the_date_line(self):
        lax, nrt = travel.airport_location("LAX"), travel.airport_location("NRT")
        view = trip_map._view([[lax["lon"], lax["lat"]], [nrt["lon"], nrt["lat"]]], max_zoom=8)
        self.assertGreater(abs(view.longitude), 160)  # centered over the Pacific, not Africa
        self.assertGreater(view.zoom, 1)

    def test_airport_colors(self):
        stops = trip_map.flight_path(["AUS", "DFW", "CUN"], "AUS", "CUN")
        dots, halos = trip_map._airport_layers(stops)
        self.assertEqual([row["color"] for row in dots.data], [trip_map.ORIGIN_RGB, trip_map.LAYOVER_RGB, trip_map.DEST_RGB])
        self.assertEqual([row["role"] for row in dots.data], ["Start", "Layover", "End"])
        self.assertEqual([row["role"] for row in halos.data], ["Start", "End"])  # only the ends get a halo
        self.assertGreater(dots.data[0]["radius"], dots.data[1]["radius"])  # ends are bigger than layovers
        lone = trip_map._airport_layers(stops[-1:])[0].data  # the hotels map shows only the destination
        self.assertEqual((lone[0]["color"], lone[0]["role"]), (trip_map.DEST_RGB, "End"))
        self.assertNotEqual(trip_map.ORIGIN_RGB, trip_map.DEST_RGB)

    def test_route_geometry_is_flat_legs_with_arrows_pointing_forward(self):
        stops = trip_map.flight_path(["AUH", "IST", "MEX", "CUN"], "AUH", "CUN")
        shape = trip_map.route_geometry(stops)
        self.assertEqual([leg["label"] for leg in shape["legs"]], ["AUH → IST", "IST → MEX", "MEX → CUN"])
        for leg in shape["legs"]:
            self.assertEqual(len(leg["path"]), 2)  # straight, not an arch
        # MEX → CUN is a short hop on a world-sized map, so only the long legs carry arrows.
        self.assertEqual([a["label"] for a in shape["arrows"]], ["AUH → IST", "IST → MEX"])
        for arrow in shape["arrows"]:
            a, b = next((leg["path"] for leg in shape["legs"] if leg["label"] == arrow["label"]))
            tip, base1, base2 = arrow["polygon"]
            # The tip sits closer to the destination than the arrow's base does.
            base = [(base1[0] + base2[0]) / 2, (base1[1] + base2[1]) / 2]
            self.assertLess(math.dist(tip, b), math.dist(base, b))

    def test_short_hop_gets_no_arrow(self):
        stops = trip_map.flight_path(["AUS", "DFW", "LHR"], "AUS", "LHR")
        labels = [a["label"] for a in trip_map.route_geometry(stops)["arrows"]]
        self.assertEqual(labels, ["DFW → LHR"])  # AUS → DFW is too short next to the ocean crossing

    def test_route_over_the_date_line_stays_continuous(self):
        stops = trip_map.flight_path(["LAX", "NRT"], "LAX", "NRT")
        (lax, nrt) = trip_map.route_geometry(stops)["positions"]
        self.assertLess(abs(nrt[0] - lax[0]), 180)  # across the Pacific, not around the world

    def test_distance(self):
        aus, cun = travel.airport_location("AUS"), travel.airport_location("CUN")
        self.assertAlmostEqual(trip_map.distance_km(aus["lat"], aus["lon"], cun["lat"], cun["lon"]), 1485, delta=25)  # ~920 miles


class HotelPointTests(unittest.TestCase):
    def hotel(self, name, lat, lon):
        return {"name": name, "total": 630.0, "rating": 4.4, "lat": lat, "lon": lon}

    def test_only_nearby_hotels_with_coordinates_are_plotted(self):
        cun = travel.airport_location("CUN")
        hotels = [self.hotel("Near", 21.13, -86.75), self.hotel("Far", 30.2, -97.7),
                  self.hotel("No location", None, None)]
        points = trip_map.hotel_points(hotels, cun, picked=set(), recommended=None)
        self.assertEqual([p["label"].split(" · ")[0] for p in points], ["Near"])
        self.assertEqual(points[0]["position"], [-86.75, 21.13])  # pydeck wants [lon, lat]

    def test_picked_and_recommended_hotels_stand_out(self):
        hotels = [self.hotel("A", 21.1, -86.8), self.hotel("B", 21.11, -86.8), self.hotel("C", 21.12, -86.8)]
        points = trip_map.hotel_points(hotels, None, picked={"A"}, recommended="B")
        self.assertEqual([p["status"] for p in points], ["picked", "recommended", ""])
        self.assertEqual([p["color"] for p in points],
                         [trip_map.PICKED_RGB, trip_map.RECOMMENDED_RGB, trip_map.HOTEL_RGB])
        self.assertTrue(points[0]["label"].endswith("in your trip"))


if __name__ == "__main__":
    unittest.main()
