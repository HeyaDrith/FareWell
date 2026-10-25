import os
from datetime import date, timedelta
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

import bank
import draft_ui
import trip_draft
from app_support import APP, DemoAppCase


class AppDraftTests(DemoAppCase):
    def button(self, label):
        return next(button for button in self.app.button if button.label == label)

    def acknowledge(self):
        self.app.checkbox(key="draft_review_acknowledged").check()

    def gemini_on(self):
        self.app.toggle(key="demo_ai").set_value(False).run()

    def test_start_choices_open_and_close_the_chat_panel(self):
        self.assertFalse(self.app.session_state[draft_ui.PANEL_KEY])  # closed until asked for
        self.click("💬 Paste your group chat")
        self.assertTrue(self.app.session_state[draft_ui.PANEL_KEY])
        self.app.text_area(key="ai_chat_0").set_value("Beach week in March?").run()
        self.click("✍️ Fill in the details")
        self.assertFalse(self.app.session_state[draft_ui.PANEL_KEY])
        self.assertEqual(self.app.text_area(key="ai_chat_0").value, "Beach week in March?")  # kept while closed

    def test_homepage_link_opens_the_planner_with_the_chat_panel_open(self):
        home = AppTest.from_file(str(APP), default_timeout=15).run()
        link = next(p for p in home.get("page_link") if "group chat" in p.proto.label)
        self.assertTrue(link.proto.page.endswith("plan"))
        self.assertIn("start=chat", link.proto.query_string)
        home.query_params["start"] = "chat"
        home.switch_page("views/plan.py").run()
        self.assertEqual(len(home.exception), 0)
        self.assertTrue(home.session_state[draft_ui.PANEL_KEY])
        self.assertNotIn("start", home.query_params)  # once only

    def test_demo_and_missing_key_do_not_call_gemini(self):
        with patch("trip_draft.extract_trip") as extract:
            self.app.text_area(key="ai_chat_0").set_value("A beach trip").run()
            self.assertTrue(self.button("Create trip draft").disabled)
            self.gemini_on()
            self.assertTrue(self.button("Create trip draft").disabled)  # no GEMINI_API_KEY
            self.assertIn("add `GEMINI_API_KEY=<your key>` to the `.env` file",
                          "\n".join(c.value for c in self.app.caption))
            self.click("Load example draft (no API)")
            self.assertIn("Offline example draft", self.visible_text())
            extract.assert_not_called()

    def test_apply_requires_confirmation_and_never_searches_or_spends(self):
        self.add("flight-0")
        self.click("Load example draft (no API)")
        self.app.text_input(key="draft_review_origin").set_value("LAX")
        self.click("Apply reviewed draft")
        self.assertIn("check the confirmation box", self.visible_text())
        self.assertEqual(self.app.selectbox(key="trip_origin").value, "AUS")
        trips_before = {k: list(v["picks"]) for k, v in bank._TRIPS.items()}
        with patch("travel.search_flights") as flights, patch("travel.search_hotels") as hotels, \
             patch("bank.create_trip") as create, patch("bank.record_pick") as pick:
            self.acknowledge()
            self.click("Apply reviewed draft")
            self.assertEqual(self.app.selectbox(key="trip_origin").value, "LAX")
            self.assertIn("Trip details changed", self.visible_text())
            for mock in (flights, hotels, create, pick):
                mock.assert_not_called()
        self.assertEqual({k: list(v["picks"]) for k, v in bank._TRIPS.items()}, trips_before)
        self.click("Start planning")
        self.assertEqual(self.metrics()["Spent"], "$0")  # fresh trip for the new details

    def test_per_person_budget_fills_trip_budget_and_compares_cost(self):
        self.click("Load example draft (no API)")
        self.app.text_input(key="draft_review_budget").set_value("1200")
        self.acknowledge()
        self.click("Apply reviewed draft")
        self.assertEqual(self.app.number_input(key="trip_budget").value, 1200)
        self.click("Start planning")
        self.assertEqual(self.metrics()["Budget"], "$1,200")
        self.add("flight-0")
        self.assertIn("under your USD 1,200.00 per-person limit", self.visible_text())

    def test_changed_chat_cannot_apply_previous_draft(self):
        self.click("Load example draft (no API)")
        self.app.text_area(key="ai_chat_1").set_value("Actually, we want a different trip.").run()
        self.assertIn("Create a new draft before applying", self.visible_text())
        self.assertFalse(any(button.label == "Apply reviewed draft" for button in self.app.button))
        self.assertEqual(self.app.selectbox(key="trip_origin").value, "AUS")

    def test_review_rejects_invalid_airport_budget_and_dates(self):
        self.click("Load example draft (no API)")
        self.acknowledge()
        self.app.text_input(key="draft_review_origin").set_value("123")
        self.click("Apply reviewed draft")
        self.assertIn("three-letter airport codes", self.visible_text())
        self.app.text_input(key="draft_review_origin").set_value("ZZZ")  # three letters, but no such airport
        self.click("Apply reviewed draft")
        self.assertIn("ZZZ isn't in the airport list", self.visible_text())
        self.assertEqual(self.app.selectbox(key="trip_origin").value, "AUS")
        self.app.text_input(key="draft_review_origin").set_value("LAX")
        self.app.selectbox(key="draft_review_scope").select("unknown")
        self.click("Apply reviewed draft")
        self.assertIn("choose per person or group", self.visible_text())
        self.app.selectbox(key="draft_review_scope").select("per_person")
        self.app.date_input(key="draft_review_return").set_value(date.today())
        self.click("Apply reviewed draft")
        self.assertIn("return after departure", self.visible_text())
        self.assertEqual(self.app.selectbox(key="trip_origin").value, "AUS")

    def test_group_budget_stays_a_note_and_is_not_used_as_trip_budget(self):
        self.click("Load example draft (no API)")
        self.app.selectbox(key="draft_review_scope").select("group")
        self.app.text_input(key="draft_review_budget").set_value("8000")
        self.acknowledge()
        self.click("Apply reviewed draft")
        captions = "\n".join(element.value for element in self.app.caption)
        self.assertIn("full group quote is still needed", captions)
        self.assertNotIn("per-person limit", self.visible_text())
        self.assertEqual(self.app.number_input(key="trip_budget").value, 1500)

    def test_gaps_are_filled_so_the_draft_can_still_be_applied(self):
        _, result = trip_draft.example_draft()
        result = result.model_copy(update={"origin": None, "depart": None, "return_date": None,
                                           "conflicts": ["The group proposed two different departure dates."]})
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-key"}), \
             patch("trip_draft.extract_trip", return_value=result) as extract:
            self.gemini_on()
            self.app.text_area(key="ai_chat_0").set_value("We cannot agree on a weekend.").run()
            self.click("Create trip draft")
            extract.assert_called_once_with("We cannot agree on a weekend.", None, demo=False)
            self.assertIn("contains disagreements", self.visible_text())
            # Nothing was written to the trip form yet.
            self.assertEqual(self.app.selectbox(key="trip_origin").value, "AUS")
            # The draft borrows the trip form's airport and suggests a week about a month out.
            self.assertEqual(self.app.text_input(key="draft_review_origin").value, "AUS")
            depart = date.today() + timedelta(days=30)
            self.assertEqual(self.app.date_input(key="draft_review_depart").value, depart)
            self.assertEqual(self.app.date_input(key="draft_review_return").value, depart + timedelta(days=7))
            text = self.visible_text()
            self.assertIn("Filled in so you can search right away", text)
            self.assertIn("departure airport AUS (from your trip form)", text)
            self.assertIn("the chat had no usable dates", text)
            self.acknowledge()
            self.click("Apply reviewed draft")
            self.assertIn("Draft applied", self.visible_text())
            self.assertEqual(self.app.date_input(key="trip_depart").value, depart)

    def test_picking_a_plan_from_a_disagreement_autofills_the_draft(self):
        soon = date.today() + timedelta(days=60)
        result = trip_draft.TripDraft(
            conflicts=["Dallas to France vs Chicago to Italy."],
            plans=[trip_draft.PlanOption(label="Dallas to France", origin="DFW", destination="CDG", city="Paris",
                                         depart=soon, return_date=soon + timedelta(days=6)),
                   trip_draft.PlanOption(label="Chicago to **Italy**", origin="ORD", destination="FCO", city="Rome",
                                         depart=soon + timedelta(days=30), return_date=soon + timedelta(days=47))])
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-key"}), \
             patch("trip_draft.extract_trip", return_value=result):
            self.gemini_on()
            self.app.text_area(key="ai_chat_0").set_value("Two ideas in the chat").run()
            self.click("Create trip draft")
            self.assertIn("Pick one of the plans below", self.visible_text())
            plans = self.app.radio(key="draft_review_plan")
            self.assertIsNone(plans.value)  # nothing chosen for the user
            self.assertEqual(len(plans.options), 2)  # options are the formatted labels
            self.assertTrue(plans.options[1].startswith("Chicago to Italy · ORD → FCO · "))  # markdown stripped
            plans.set_value(1).run()
            self.assertEqual(self.app.text_input(key="draft_review_origin").value, "ORD")
            self.assertEqual(self.app.text_input(key="draft_review_destination").value, "FCO")
            self.assertEqual(self.app.text_input(key="draft_review_city").value, "Rome")
            self.assertEqual(self.app.date_input(key="draft_review_depart").value, soon + timedelta(days=30))
            self.app.radio(key="draft_review_plan").set_value(0).run()  # switch plans
            self.assertEqual(self.app.text_input(key="draft_review_city").value, "Paris")
            self.acknowledge()
            self.click("Apply reviewed draft")
            self.assertEqual(self.app.selectbox(key="trip_origin").value, "DFW")
            self.assertEqual(self.app.selectbox(key="trip_destination").value, "CDG")
            self.assertEqual(self.app.text_input(key="trip_area").value, "")  # Paris is where CDG is
            self.assertIn("We'll search hotels in Paris", self.visible_text())

    def test_a_plan_without_dates_gets_suggested_dates(self):
        result = trip_draft.TripDraft(plans=[trip_draft.PlanOption(label="Somewhere sunny", destination="MIA")])
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-key"}), \
             patch("trip_draft.extract_trip", return_value=result):
            self.gemini_on()
            self.app.text_area(key="ai_chat_0").set_value("Let's go somewhere sunny").run()
            self.click("Create trip draft")
            self.app.radio(key="draft_review_plan").set_value(0).run()
            self.assertEqual(self.app.text_input(key="draft_review_destination").value, "MIA")
            self.assertEqual(self.app.text_input(key="draft_review_city").value, "Miami")  # from the airport
            self.assertEqual(self.app.date_input(key="draft_review_depart").value, date.today() + timedelta(days=30))

    def test_provider_failure_keeps_manual_trip_form_usable(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-key"}), \
             patch("trip_draft.extract_trip", side_effect=trip_draft.DraftError("Gemini could not create a usable draft.")):
            self.gemini_on()
            self.app.text_area(key="ai_chat_0").set_value("Trip plans").run()
            self.click("Create trip draft")
            self.assertIn("could not create a usable draft", self.visible_text())
            self.assertEqual(self.app.selectbox(key="trip_origin").value, "AUS")
            self.add("flight-0")
            self.assertEqual(self.metrics()["Spent"], "$412")

    def test_screenshot_only_is_passed_to_extractor_and_replacement_invalidates_it(self):
        _, result = trip_draft.example_draft()
        upload = Mock(size=4)
        upload.getvalue.return_value = b"test"
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-key"}), \
             patch("streamlit.file_uploader", return_value=upload), \
             patch("trip_draft.extract_trip", return_value=result) as extract:
            self.gemini_on()
            self.click("Create trip draft")
            extract.assert_called_once_with("", b"test", demo=False)
            upload.getvalue.return_value = b"new!"
            self.app.run()
            self.assertIn("Create a new draft before applying", self.visible_text())

    def test_clear_discards_source_and_draft_but_preserves_manual_trip(self):
        self.click("Load example draft (no API)")
        self.click("Clear chat and draft")
        self.assertEqual(self.app.text_area(key="ai_chat_2").value, "")
        self.assertNotIn("ai_draft", self.app.session_state)
        self.assertFalse(any(button.label == "Apply reviewed draft" for button in self.app.button))
        self.assertEqual(self.app.selectbox(key="trip_origin").value, "AUS")

    def test_short_notice_draft_plans_without_errors(self):
        self.click("Load example draft (no API)")
        departure = date.today() + timedelta(days=10)
        self.app.date_input(key="draft_review_depart").set_value(departure)
        self.app.date_input(key="draft_review_return").set_value(departure + timedelta(days=3))
        self.acknowledge()
        self.click("Apply reviewed draft")
        self.click("Start planning")
        self.assertEqual(self.app.date_input(key="trip_depart").value, departure)
        self.add("hotel-0")  # 3 nights x $89
        self.assertEqual(self.metrics()["Spent"], "$267")
