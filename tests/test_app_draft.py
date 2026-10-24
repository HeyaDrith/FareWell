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

    def test_demo_and_missing_key_do_not_call_gemini(self):
        with patch("trip_draft.extract_trip") as extract:
            self.app.text_area(key="ai_chat_0").set_value("A beach trip").run()
            self.assertTrue(self.button("Create trip draft").disabled)
            self.app.toggle[0].set_value(False).run()
            self.assertTrue(self.button("Create trip draft").disabled)
            self.click("Load example draft (no API)")
            self.assertIn("Offline example draft", self.visible_text())
            extract.assert_not_called()

    def test_apply_requires_confirmation_and_never_searches_or_moves_money(self):
        self.click("Create my Trip Fund")
        self.click("Load example draft (no API)")
        self.app.text_input(key="draft_review_origin").set_value("LAX")
        self.click("Apply reviewed draft")
        self.assertIn("check the confirmation box", self.visible_text())
        self.assertEqual(self.app.text_input(key="trip_origin").value, "AUS")
        with patch("travel.search_flights") as flights, patch("travel.search_hotels") as hotels, \
             patch("bank.setup_accounts") as accounts, patch("bank.transfer") as transfer:
            self.acknowledge()
            self.click("Apply reviewed draft")
            self.assertEqual(self.app.text_input(key="trip_origin").value, "LAX")
            self.assertIn("Search prices again", self.visible_text())
            for mock in (flights, hotels, accounts, transfer):
                mock.assert_not_called()
        self.assertEqual(list(bank._DEMO.values()), [{"checking": 3000.0, "fund": 0.0}])
        self.click("Search prices")
        self.assertIn("per-person limit", self.visible_text())
        self.assertEqual(self.app.metric[0].value, "$1,235")

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

    def test_group_budget_stays_a_note_and_is_not_used_as_trip_cost(self):
        self.click("Load example draft (no API)")
        self.app.selectbox(key="draft_review_scope").select("group")
        self.app.text_input(key="draft_review_budget").set_value("8000")
        self.acknowledge()
        self.click("Apply reviewed draft")
        captions = "\n".join(element.value for element in self.app.caption)
        self.assertIn("full group quote is still needed", captions)
        self.assertNotIn("per-person limit", self.visible_text())
        self.assertEqual(self.app.metric[0].value, "$1,235")

    def test_gemini_draft_displays_conflicts_and_does_not_autofill(self):
        _, result = trip_draft.example_draft()
        result = result.model_copy(update={"origin": None, "depart": None,
                                           "conflicts": ["The group proposed two different departure dates."]})
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-key"}), \
             patch("trip_draft.extract_trip", return_value=result) as extract:
            self.app.toggle[0].set_value(False).run()
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
            self.app.toggle[0].set_value(False).run()
            self.app.text_area(key="ai_chat_0").set_value("Trip plans").run()
            self.click("Create trip draft")
            self.assertIn("could not create a usable draft", self.visible_text())
            self.assertEqual(self.app.text_input(key="trip_origin").value, "AUS")
            self.click("Search prices")
            self.assertEqual(self.app.metric[0].value, "$1,235")

    def test_screenshot_only_is_passed_to_extractor_and_replacement_invalidates_it(self):
        _, result = trip_draft.example_draft()
        upload = Mock(size=4)
        upload.getvalue.return_value = b"test"
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-key"}), \
             patch("streamlit.file_uploader", return_value=upload), \
             patch("trip_draft.extract_trip", return_value=result) as extract:
            self.app.toggle[0].set_value(False).run()
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

    def test_short_notice_trip_gets_a_valid_savings_deadline(self):
        self.click("Load example draft (no API)")
        departure = date.today() + timedelta(days=10)
        self.app.date_input(key="draft_review_depart").set_value(departure)
        self.app.date_input(key="draft_review_return").set_value(departure + timedelta(days=3))
        self.acknowledge()
        self.click("Apply reviewed draft")
        self.click("Search prices")
        self.assertLessEqual(self.app.date_input(key="deadline").value, departure)
        self.click("Create my Trip Fund")
        self.assertFalse(any("on or before" in warning.value for warning in self.app.warning))

    def test_apply_preserves_an_existing_valid_savings_deadline(self):
        chosen_deadline = date.today() + timedelta(days=14)
        self.set_deadline(chosen_deadline)
        self.click("Load example draft (no API)")
        self.acknowledge()
        self.click("Apply reviewed draft")
        self.assertEqual(self.app.date_input(key="deadline").value, chosen_deadline)
