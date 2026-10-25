"""Map data: flight paths from airport codes and hotel pins near the destination."""
import math
import unittest
from unittest.mock import MagicMock, patch

import requests

import trip_map
import travel
import ui


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
        # Fixed screen sizes, so markers don't balloon when zoomed in; the halo is bigger than a dot.
        self.assertEqual((dots.radius_min_pixels, dots.radius_max_pixels), (7, 7))
        self.assertEqual((halos.radius_min_pixels, halos.radius_max_pixels), (15, 15))
        lone = trip_map._airport_layers(stops[-1:])[0].data  # the hotels map shows only the destination
        self.assertEqual((lone[0]["color"], lone[0]["role"]), (trip_map.DEST_RGB, "End"))
        self.assertNotEqual(trip_map.ORIGIN_RGB, trip_map.DEST_RGB)

    def test_arcs_fade_from_start_green_through_amber_layovers_to_end_red(self):
        stops = trip_map.flight_path(["AUH", "IST", "MEX", "CUN"], "AUH", "CUN")
        legs = trip_map.route_geometry(stops)["legs"]
        self.assertEqual([leg["label"] for leg in legs], ["AUH → IST", "IST → MEX", "MEX → CUN"])
        green, amber, red = trip_map.ORIGIN_RGB, trip_map.LAYOVER_RGB, trip_map.DEST_RGB
        self.assertEqual([(leg["from_color"], leg["to_color"]) for leg in legs],
                         [(green, amber), (amber, amber), (amber, red)])
        aus_cun = trip_map.route_geometry(trip_map.flight_path([], "AUS", "CUN"))["legs"]
        self.assertEqual((aus_cun[0]["from_color"], aus_cun[0]["to_color"]), (green, red))  # nonstop
        self.assertLess(trip_map.ARC_HEIGHT, 1)  # lower than deck.gl's default arc

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
        self.assertEqual([p["note"] for p in points], ["In your trip", "⭐ Recommended", "Other option"])

    def test_hover_card_fields_are_plain_text(self):
        hotel = dict(self.hotel("<b>Bold</b> Inn", 21.1, -86.8), per_night=90.0)
        (point,) = trip_map.hotel_points([hotel], None, picked=set(), recommended=None)
        # Streamlit escapes these values, so the markup stays in the card template only.
        self.assertEqual((point["title"], point["detail"], point["rating"]),
                         ("<b>Bold</b> Inn", "$630 total · $90/night", "4.4★ rating"))
        for name in ("title", "detail", "rating", "note", "tone"):
            self.assertIn("{" + name + "}", trip_map._TOOLTIP["html"])
        self.assertIn("src='{image}'", trip_map._HOTEL_TOOLTIP["html"])

    def test_hover_card_picture_is_the_hotel_photo_or_a_drawn_stand_in(self):
        photo = dict(self.hotel("Photo", 21.1, -86.8), image="https://img.example/a.jpg")
        blocked = dict(self.hotel("Blocked", 21.1, -86.8), image="https://img.example/blocked.jpg")
        plain = self.hotel("Plain", 21.1, -86.8)
        with patch("travel.picture_data", side_effect=lambda url: "data:image/jpeg;base64,QQ==" if "a.jpg" in url else ""):
            points = trip_map.hotel_points([photo, blocked, plain], None, picked=set(), recommended=None)
        self.assertEqual([p["image"] for p in points],
                         ["data:image/jpeg;base64,QQ==", ui.PLACEHOLDERS["hotel"], ui.PLACEHOLDERS["hotel"]])
        stops = trip_map.flight_path([], "AUS", "CUN")
        self.assertEqual({row["image"] for row in trip_map._airport_layers(stops)[0].data}, {""})  # airports: none


class PictureTests(unittest.TestCase):
    def setUp(self):
        network = patch("requests.sessions.Session.request", side_effect=AssertionError("External HTTP forbidden"))
        network.start()
        self.addCleanup(network.stop)
        travel.picture_data.cache_clear()
        self.addCleanup(travel.picture_data.cache_clear)

    def test_picture_is_the_downloaded_image_or_the_stand_in(self):
        with patch("travel.picture_data", return_value="data:image/png;base64,QQ==") as fetch:
            self.assertEqual(ui.picture_url(" https://img.example/a.png ", "hotel"), "data:image/png;base64,QQ==")
            fetch.assert_called_once_with("https://img.example/a.png")
            self.assertIn("ts-pic-logo", ui.picture("https://img.example/logo.png", "flight"))  # logos are fitted
        for bad in ("", None, "http://img.example/a.jpg", "javascript:alert(1)"):
            self.assertEqual(ui.picture_url(bad, "hotel"), ui.PLACEHOLDERS["hotel"])  # never fetched
        self.assertNotIn("ts-pic-logo", ui.picture("", "flight"))  # the stand-in fills its tile
        with patch("travel.picture_data", return_value="data:image/png;base64,'><script>"):
            self.assertIn("&#x27;&gt;&lt;script&gt;", ui.picture("https://img.example/a.png", "hotel"))  # escaped

    def test_download_keeps_only_raster_images_that_load(self):
        def reply(status=200, kind="image/jpeg", body=b"pic"):
            response = MagicMock(status_code=status, headers={"Content-Type": kind})
            response.iter_content.return_value = [body]
            response.__enter__.return_value = response
            return response
        cases = {"https://a.example/ok.jpg": (reply(), "data:image/jpeg;base64,cGlj"),
                 "https://a.example/blocked.jpg": (reply(status=403), ""),
                 "https://a.example/page.html": (reply(kind="text/html"), ""),
                 "https://a.example/vector.svg": (reply(kind="image/svg+xml"), ""),
                 "https://a.example/huge.jpg": (reply(body=b"x" * (travel.MAX_PICTURE_BYTES + 1)), "")}
        for url, (response, expected) in cases.items():
            with self.subTest(url=url), patch("requests.get", return_value=response):
                self.assertEqual(travel.picture_data(url), expected)
        with patch("requests.get", side_effect=requests.Timeout):
            self.assertEqual(travel.picture_data("https://a.example/slow.jpg"), "")
        with patch("requests.get") as get:
            self.assertEqual(travel.picture_data("http://a.example/plain.jpg"), "")  # https only
            get.assert_not_called()

    def test_broken_pictures_fall_back_in_css_and_the_stylesheet_survives_sanitizing(self):
        self.assertIn("ts-pic-hotel", trip_map._HOTEL_TOOLTIP["html"])
        self.assertIn(".ts-pic::before", ui._CSS)
        self.assertIn('url("HOTEL_TILE")', ui._CSS)  # filled in with the drawn stand-in by inject_css
        # Streamlit's HTML cleaner drops a whole style block that contains an angle bracket.
        built = ui._CSS.replace("BEACH", ui.BEACH_URL).replace("HOTEL_TILE", ui.PLACEHOLDERS["hotel"])
        self.assertNotIn("<", built.replace("FLIGHT_TILE", ui.PLACEHOLDERS["flight"]))


if __name__ == "__main__":
    unittest.main()
