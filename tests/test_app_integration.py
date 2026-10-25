"""Exercise the real Streamlit flow: budget -> picks -> savings -> final cost.

Sample travel data: flights $412 / $438 / $521 (typical $438); hotels $89 / $132 / $215
per night x 7 nights = $623 / $924 / $1,505 (typical $924). Default budget $1,500.
"""
import json
import os
import unittest
from datetime import date, timedelta
from unittest.mock import Mock, patch

import bank
import travel
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
                      "🧾 Other expenses $375 (food ≈ $28/day)", text)  # food $225 + activities $150
        self.assertIn("Other expenses", [s.value for s in self.app.subheader])
        self.assertIn("Food, activities and anything else you'll pay for on the trip. "
                      "Food budget ≈ $28/day for 8 days.", text)
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
        self.assertTrue(buttons[1][1].startswith("https://www.google.com/travel/hotels?q=Seaside+Budget+Inn+Canc%C3%BAn"))
        self.assertEqual(buttons[2][1], "https://www.google.com/maps/search/?api=1&query=Taqueria+El+Fogon+Canc%C3%BAn")

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

    def test_options_can_be_viewed_before_adding(self):
        self.assertIn("[View on Google Flights ↗](https://www.google.com/travel/flights/search?tfs=", self.plain_text())
        hotel_links = [m.value for m in self.app.markdown if "[Find hotel ↗](" in m.value]
        self.assertEqual(len(hotel_links), 3)  # one per sample hotel, before anything is added
        self.assertIn("https://www.google.com/travel/hotels?q=Seaside+Budget+Inn+Canc%C3%BAn", hotel_links[0])
        flight_links = [m.value for m in self.app.markdown if "[View on Google Flights ↗](" in m.value]
        self.assertEqual(len(flight_links), 3)
        self.assertEqual(self.link_buttons(), [])  # the big booking buttons still come with picks

    def test_view_links_keep_provider_urls_inside_the_markdown_link(self):
        hotels = [{"name": "Paren Hotel", "per_night": 90.0, "total": 630.0, "rating": 4.4, "property_token": "",
                   "website": "https://hotel.example/rooms (deluxe)", "lat": None, "lon": None}]
        with patch("travel.search_hotels", return_value=hotels):
            self.click("Start planning")
        line = next(m.value for m in self.app.markdown if "Website ↗" in m.value)
        self.assertIn("[Website ↗](https://hotel.example/rooms%20%28deluxe%29)", line)

    def decks(self):
        return [json.loads(d.proto.json) for d in self.app.get("deck_gl_json_chart")]

    def show_map(self, label):
        next(r for r in self.app.radio if r.key == "map_view").set_value(label).run()

    def test_map_shows_flight_path_and_hotels(self):
        toggle = next(r for r in self.app.radio if r.key == "map_view")
        self.assertEqual(toggle.options, ["✈️ Flight path", "🏨 Hotels on the map"])
        (route,) = self.decks()  # only the chosen map is drawn, so its hover cards work
        self.show_map("🏨 Hotels on the map")
        (hotels,) = self.decks()
        decks = [route, hotels]
        # Start/end halos, white arc casing, colored arcs, airport dots on top.
        self.assertEqual([layer["@@type"] for layer in route["layers"]],
                         ["ScatterplotLayer", "ArcLayer", "ArcLayer", "ScatterplotLayer"])
        self.assertEqual([p["label"] for p in route["layers"][3]["data"]], ["Start: AUS · Austin", "End: CUN · Cancún"])
        legs = route["layers"][2]["data"]
        self.assertEqual(len(legs), 1)  # recommended Volaris: nonstop AUS -> CUN
        self.assertEqual((legs[0]["from_color"], legs[0]["to_color"]), ([22, 163, 74], [220, 38, 38]))  # green -> red
        self.assertEqual(route["layers"][2]["getHeight"], 0.35)  # low arcs, not towers
        self.assertLess(route["initialViewState"]["zoom"], 6)
        self.assertEqual(route["initialViewState"]["pitch"], 30)  # a gentle, fixed 3D tilt
        self.assertEqual(hotels["initialViewState"].get("pitch", 0), 0)  # hotels stay top-down
        for deck in decks:  # neither map can be tilted or spun by dragging
            self.assertEqual(deck["views"][0]["controller"], {"dragRotate": False, "touchRotate": False})
        self.assertEqual(len(hotels["layers"][0]["data"]), 3)  # every sample hotel has a location
        self.assertIn("<b>{title}</b>", json.loads(self.app.get("deck_gl_json_chart")[0].proto.tooltip)["html"])
        card = hotels["layers"][0]["data"][0]
        self.assertIn("/night", card["detail"])
        self.assertIn("★ rating", card["rating"])
        for row in route["layers"][2]["data"] + route["layers"][3]["data"]:  # arcs and airports get cards too
            self.assertLessEqual({"title", "detail", "rating", "note", "tone"}, set(row))
        self.assertIn("Hotels near", self.plain_text())
        self.show_map("✈️ Flight path")
        text = self.plain_text()
        self.assertIn("Volaris: AUS → CUN (nonstop)", text)
        self.assertIn("🟢 **Start** AUS · Austin  →  🔴 **End** CUN · Cancún", text)

    def test_map_follows_the_selected_and_added_flight(self):
        selector = next(s for s in self.app.selectbox if s.label == "Show the flight path for")
        selector.set_value(2).run()  # American, 1 stop via DFW
        route = json.loads(self.app.get("deck_gl_json_chart")[0].proto.json)
        self.assertEqual([p["label"] for p in route["layers"][2]["data"]], ["AUS → DFW", "DFW → CUN"])
        self.assertEqual([p["label"] for p in route["layers"][3]["data"]],
                         ["Start: AUS · Austin", "Layover: DFW · Dallas-Fort Worth", "End: CUN · Cancún"])
        self.assertIn("American: AUS → DFW → CUN (layover in DFW)", self.plain_text())
        self.assertIn("🟢 **Start** AUS · Austin  →  🟡 DFW  →  🔴 **End** CUN", self.plain_text())
        self.add("flight-0")  # adding Southwest switches the map to it
        self.assertIn("Southwest: AUS → CUN (nonstop)", self.plain_text())
        self.add("hotel-0")
        self.show_map("🏨 Hotels on the map")
        hotels = self.decks()[0]["layers"][0]["data"]
        self.assertEqual(hotels[0]["status"], "picked")  # Seaside Budget Inn
        self.assertNotIn("picked", [h["status"] for h in hotels[1:]])

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
        self.add("flight-0")  # the added flight's button is Remove, so this takes it out again
        self.assertEqual(self.metrics()["Spent"], "$623")

    def test_added_options_are_marked_and_can_be_removed(self):
        self.add("flight-0")  # Southwest
        self.add("hotel-0")   # Seaside Budget Inn
        self.assertEqual(self.app.button(key="flight-0").label, "Remove")
        self.assertEqual(self.app.button(key="hotel-0").label, "Remove")
        self.assertEqual(self.app.button(key="flight-1").label, "Add")  # other options stay addable
        text = self.plain_text()
        self.assertIn("**Southwest** · 3h 15m · Nonstop  \n💰 Cheapest  \n✅ **Added to your trip**", text)
        self.assertIn("✅ Added Seaside Budget Inn to your trip", [t.value for t in self.app.toast])
        self.assertEqual(text.count("✅ **Added to your trip**"), 2)
        # An added option is judged against the budget before its own cost, so it still "fits".
        self.assertIn("$623 total · ✅ fits", text)
        self.app.button(key="flight-0").click().run()  # unselect the flight
        self.assertEqual(self.metrics()["Spent"], "$623")
        self.assertEqual(self.app.button(key="flight-0").label, "Add")
        self.assertIn("Removed Southwest flight AUS→CUN from your trip", [t.value for t in self.app.toast])
        self.assertNotIn("Southwest flight", "\n".join(m.value for m in self.app.markdown
                                                     if m.value.startswith("Flight:")))  # gone from the trip list

    def test_added_rows_get_the_green_style_hook(self):
        self.add("hotel-1")
        keys = []  # container keys become the CSS classes the green style targets

        def walk(node):
            block_id = str(getattr(getattr(node, "proto", None), "id", ""))
            if "-opt-" in block_id:
                keys.append("opt-" + block_id.split("-opt-", 1)[1])
            for child in getattr(node, "children", {}).values():
                walk(child)
        walk(self.app._tree)
        self.assertIn("opt-hotel-1-picked", keys)
        self.assertIn("opt-hotel-0", keys)
        self.assertNotIn("opt-hotel-0-picked", keys)

    def test_remove_is_frozen_while_locked(self):
        self.add("flight-0")
        self.click("🔒 Lock in my trip")
        self.assertEqual(self.app.button(key="flight-0").label, "Remove")
        self.assertTrue(self.app.button(key="flight-0").disabled)

    def test_cannot_lock_while_over_budget(self):
        self.add("flight-2")
        self.add("hotel-2")
        lock = next(b for b in self.app.button if b.label == "🔒 Lock in my trip")
        self.assertTrue(lock.disabled)
        self.assertIn("Get under budget first", self.visible_text())

    def test_airport_dropdowns_search_by_code_or_city(self):
        origin = self.app.selectbox(key="trip_origin")
        self.assertEqual(origin.value, "AUS")
        self.assertIn("CUN · Cancún (Cancun)", origin.options)  # accents-free name matches "cancun"
        self.assertIn("DFW · Dallas-Fort Worth", origin.options)
        self.assertGreater(len(origin.options), 4000)

    def test_hotels_are_searched_where_the_flight_lands_with_an_optional_area(self):
        area = self.app.text_input(key="trip_area")
        self.assertEqual((area.label, area.value), ("Hotel area or type (optional)", ""))
        self.assertIn("We'll search hotels in Cancún, where your flight lands.", self.visible_text())
        self.app.selectbox(key="trip_destination").select("SJU").run()
        self.assertIn("We'll search hotels in San Juan", self.visible_text())  # follows the To airport
        self.assertIn("Trip details changed", self.visible_text())
        with patch("travel.search_hotels", return_value=[]) as search:
            self.app.text_input(key="trip_area").input("Condado").run()
            self.click("Start planning")
            self.app.text_input(key="trip_area").input("").run()
            self.click("Start planning")  # blank still searches the city, never sample data
        self.assertEqual([c.args[0] for c in search.call_args_list], ["hotels in San Juan Condado", "hotels in San Juan"])

    def test_form_has_from_and_to_and_the_hero_search_stays_in_sync(self):
        labels = [s.label for s in self.app.selectbox]
        self.assertIn("From", labels)
        self.assertIn("To", labels)
        hero = self.app.selectbox(key="hero_destination")
        self.assertEqual(hero.value, "CUN")  # mirrors the form's To field
        hero.select("SJU").run()  # searching in the hero sets To, and so the hotel city
        self.assertEqual(self.app.selectbox(key="trip_destination").value, "SJU")
        self.assertIn("We'll search hotels in San Juan", self.visible_text())
        self.app.selectbox(key="trip_destination").select("MIA").run()  # and the other way round
        self.assertEqual(self.app.selectbox(key="hero_destination").value, "MIA")
        self.assertIn("We'll search hotels in Miami", self.visible_text())

    def test_only_listed_airports_can_be_chosen(self):
        listed = [travel.airport_label(code) for code in travel.airport_codes()]
        for key in ("hero_destination", "trip_origin", "trip_destination"):
            box = self.app.selectbox(key=key)
            self.assertFalse(box.proto.accept_new_options)  # typed text can't become a new option
            self.assertEqual(box.options, listed)  # nothing outside the airport list
            # Substring matching, not fuzzy: a made-up code like "XYZ" lists no airports.
            self.assertEqual(box.proto.DESCRIPTOR.fields_by_name["filter_mode"].enum_type
                             .values_by_number[box.proto.filter_mode].name, "FILTER_MODE_CONTAINS")
        self.assertEqual([label for label in listed if "xyz" in label.lower()], [])
        self.assertTrue(any("dal" in label.lower() for label in listed))  # a city prefix still matches

    def test_airport_code_is_uppercased_and_empty_stays_empty(self):
        self.app.session_state["trip_origin"] = "dfw"
        self.app.run()
        self.assertEqual(self.app.selectbox(key="trip_origin").value, "DFW")
        self.app.session_state["trip_origin"] = None
        self.app.run()
        self.assertIsNone(self.app.selectbox(key="trip_origin").value)  # not the first airport in the list
        self.assertIn("flying from and to", self.visible_text())
        self.assertTrue(next(b for b in self.app.button if b.label == "Start planning").disabled)
        self.app.session_state["trip_origin"] = "CUN"
        self.app.run()
        self.assertIn("two different airports", self.visible_text())


if __name__ == "__main__":
    unittest.main()
