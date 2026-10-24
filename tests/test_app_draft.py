import os
from datetime import date, timedelta
from unittest.mock import Mock, patch

import bank
import trip_draft
from app_support import DemoAppCase


class AppDraftTests(DemoAppCase):
    def button(self, label):
        return next(button for button in self.app.button if button.label == label)

    def acknowledge(self):
        self.app.checkbox(key="draft_review_acknowledged").check()

    def gemini_on(self):
        self.app.toggle(key="demo_ai").set_value(False).run()

    def test_demo_and_missing_key_do_not_call_gemini(self):
        with patch("trip_draft.extract_trip") as extract:
            self.app.text_area(key="ai_chat_0").set_value("A beach trip").run()
            self.assertTrue(self.button("Create trip draft").disabled)
            self.gemini_on()
            self.assertTrue(self.button("Create trip draft").disabled)  # no GEMINI_API_KEY
            self.click("Load example draft (no API)")
            self.assertIn("Offline example draft", self.visible_text())
            extract.assert_not_called()

    def test_apply_requires_confirmation_and_never_searches_or_spends(self):
        self.add("flight-0")
        self.click("Load example draft (no API)")
        self.app.text_input(key="draft_review_origin").set_value("LAX")
        self.click("Apply reviewed draft")
        self.assertIn("check the confirmation box", self.visible_text())
        self.assertEqual(self.app.text_input(key="trip_origin").value, "AUS")
        trips_before = {k: list(v["picks"]) for k, v in bank._TRIPS.items()}
        with patch("travel.search_flights") as flights, patch("travel.search_hotels") as hotels, \
             patch("bank.create_trip") as create, patch("bank.record_pick") as pick:
            self.acknowledge()
            self.click("Apply reviewed draft")
            self.assertEqual(self.app.text_input(key="trip_origin").value, "LAX")
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
        self.assertEqual(self.app.text_input(key="trip_origin").value, "AUS")

    def test_review_rejects_invalid_airport_budget_and_dates(self):
        self.click("Load example draft (no API)")
        self.acknowledge()
        self.app.text_input(key="draft_review_origin").set_value("123")
        self.click("Apply reviewed draft")
        self.assertIn("three-letter airport codes", self.visible_text())
        self.app.text_input(key="draft_review_origin").set_value("LAX")
        self.app.selectbox(key="draft_review_scope").select("unknown")
        self.click("Apply reviewed draft")
        self.assertIn("choose per person or group", self.visible_text())
        self.app.selectbox(key="draft_review_scope").select("per_person")
        self.app.date_input(key="draft_review_return").set_value(date.today())
        self.click("Apply reviewed draft")
        self.assertIn("return after departure", self.visible_text())
        self.assertEqual(self.app.text_input(key="trip_origin").value, "AUS")

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

    def test_gemini_draft_displays_conflicts_and_does_not_autofill(self):
        _, result = trip_draft.example_draft()
        result = result.model_copy(update={"origin": None, "depart": None,
                                           "conflicts": ["The group proposed two different departure dates."]})
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-key"}), \
             patch("trip_draft.extract_trip", return_value=result) as extract:
            self.gemini_on()
            self.app.text_area(key="ai_chat_0").set_value("We cannot agree on a weekend.").run()
            self.click("Create trip draft")
            extract.assert_called_once_with("We cannot agree on a weekend.", None, demo=False)
            self.assertIn("contains disagreements", self.visible_text())
            self.assertEqual(self.app.text_input(key="trip_origin").value, "AUS")
            self.assertEqual(self.app.text_input(key="draft_review_origin").value, "")
            self.assertIsNone(self.app.date_input(key="draft_review_depart").value)
            self.acknowledge()
            self.click("Apply reviewed draft")
            self.assertIn("Fill in both airports", self.visible_text())

    def test_provider_failure_keeps_manual_trip_form_usable(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-key"}), \
             patch("trip_draft.extract_trip", side_effect=trip_draft.DraftError("Gemini could not create a usable draft.")):
            self.gemini_on()
            self.app.text_area(key="ai_chat_0").set_value("Trip plans").run()
            self.click("Create trip draft")
            self.assertIn("could not create a usable draft", self.visible_text())
            self.assertEqual(self.app.text_input(key="trip_origin").value, "AUS")
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
        self.assertEqual(self.app.text_input(key="trip_origin").value, "AUS")

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
