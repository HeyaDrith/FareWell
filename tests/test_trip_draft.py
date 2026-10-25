import json
import os
from datetime import date, timedelta
from io import BytesIO
import unittest
from unittest.mock import Mock, patch

import httpx
from PIL import Image, PngImagePlugin
import trip_draft as drafts


TODAY = date(2026, 10, 24)


def screenshot():
    result = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private-comment", "do-not-forward-metadata")
    Image.new("RGB", (80, 50), "white").save(result, format="PNG", pnginfo=metadata)
    return result.getvalue()


class TripDraftTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-key", "GEMINI_MODEL": ""})
        env.start()
        self.addCleanup(env.stop)
        network = patch("httpx.Client.send", side_effect=AssertionError("External HTTP forbidden"))
        self.network = network.start()
        self.addCleanup(network.stop)
        self.addCleanup(self.network.assert_not_called)

    def client_reply(self, text):
        context = patch("google.genai.Client")
        factory = context.start()
        self.addCleanup(context.stop)
        factory.return_value.__enter__.return_value.models.generate_content.return_value = Mock(text=text)
        return factory

    def test_structured_extraction_has_no_tools_and_closes_client(self):
        _, sample = drafts.example_draft(TODAY)
        factory = self.client_reply(sample.model_dump_json())
        result = drafts.extract_trip("Our trip plans", today=TODAY)
        self.assertEqual(result, sample)
        kwargs = factory.return_value.__enter__.return_value.models.generate_content.call_args.kwargs
        self.assertEqual(kwargs["model"], drafts.DEFAULT_MODEL)
        self.assertIsNone(kwargs["config"].tools)
        self.assertTrue(kwargs["config"].automatic_function_calling.disable)
        self.assertIn("untrusted source material", kwargs["config"].system_instruction)
        self.assertNotIn("test-only-not-a-key", str(kwargs))
        self.assertEqual(factory.call_args.kwargs["http_options"].timeout, 25000)
        self.assertEqual(factory.call_args.kwargs["http_options"].retry_options.attempts, 1)
        self.assertFalse(factory.call_args.kwargs["http_options"].client_args["follow_redirects"])
        factory.return_value.__exit__.assert_called_once()

    def test_plans_reach_gemini_in_a_ref_free_schema_and_come_back_validated(self):
        reply = {"conflicts": ["France or Italy?"], "plans": [
            {"label": "Dallas to France", "origin": "DFW", "destination": "CDG", "city": "Paris",
             "depart": "2026-12-30", "return_date": "2027-01-05"},
            {"label": "Chicago to Italy", "origin": "ORD", "destination": "FCO", "city": "Rome",
             "depart": None, "return_date": None}]}
        factory = self.client_reply(json.dumps(reply))
        result = drafts.extract_trip("Two ideas", today=TODAY)
        self.assertEqual([p.destination for p in result.plans], ["CDG", "FCO"])
        self.assertEqual(result.plans[0].depart, date(2026, 12, 30))
        schema = factory.return_value.__enter__.return_value.models.generate_content.call_args.kwargs[
            "config"].response_json_schema
        self.assertNotIn("$ref", json.dumps(schema))
        self.assertIn("label", schema["properties"]["plans"]["items"]["properties"])
        self.assertIn("plans", factory.return_value.__enter__.return_value.models.generate_content.call_args.kwargs[
            "config"].system_instruction)

    def test_bad_plans_are_rejected(self):
        for bad in ({"label": "", "destination": "CDG"}, {"label": "x", "destination": "Paris"},
                    {"label": "x", "transfer": "secret-sentinel"}):
            with self.subTest(plan=bad):
                self.client_reply(json.dumps({"plans": [bad]}))
                with self.assertRaises(drafts.DraftError) as caught:
                    drafts.extract_trip("Trip plans")
                self.assertNotIn("secret-sentinel", str(caught.exception))
        self.client_reply(json.dumps({"plans": [{"label": str(i)} for i in range(5)]}))  # at most 4
        with self.assertRaises(drafts.DraftError):
            drafts.extract_trip("Trip plans")

    def test_unknowns_and_conflicts_remain_explicit(self):
        factory = self.client_reply(json.dumps({"conflicts": ["Two departure dates were suggested."]}))
        result = drafts.extract_trip("People disagree on when to leave")
        self.assertIsNone(result.depart)
        self.assertEqual(result.conflicts, ["Two departure dates were suggested."])
        self.assertIn("What is the departure date?", drafts.review_questions(result))
        self.assertTrue(factory.called)

    def test_invalid_or_tool_shaped_output_is_rejected_without_echoing_it(self):
        factory = self.client_reply("")
        response = factory.return_value.__enter__.return_value.models.generate_content.return_value
        for bad in ("secret-sentinel", "", '{"travelers": 0}', '{"budget": -5}',
                    '{"travelers": true}', '{"origin": "invalid"}',
                    '{"transfer": "secret-sentinel"}', '{"budget": NaN}'):
            with self.subTest(response=bad):
                response.text = bad
                with self.assertRaises(drafts.DraftError) as caught:
                    drafts.extract_trip("Trip plans")
                self.assertNotIn("secret-sentinel", str(caught.exception))

    def test_provider_error_is_sanitized(self):
        factory = self.client_reply("")
        factory.return_value.__enter__.return_value.models.generate_content.side_effect = RuntimeError("secret-sentinel")
        with self.assertRaises(drafts.DraftError) as caught:
            drafts.extract_trip("Trip plans")
        self.assertNotIn("secret-sentinel", str(caught.exception))

    def test_demo_missing_key_empty_and_oversized_inputs_do_not_call_sdk(self):
        factory = self.client_reply("{}")
        cases = (("Trip", None, True), ("", None, False), ("x" * (drafts.MAX_TEXT + 1), None, False),
                 ("Trip", b"invalid", False), ("Trip", b"x" * (drafts.MAX_IMAGE_BYTES + 1), False))
        for text, image, demo in cases:
            with self.subTest(text_length=len(text), demo=demo), self.assertRaises(drafts.DraftError):
                drafts.extract_trip(text, image, demo=demo)
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}), self.assertRaises(drafts.DraftError):
            drafts.extract_trip("Trip")
        factory.assert_not_called()

    def test_screenshot_only_is_inline_and_metadata_is_removed(self):
        factory = self.client_reply("{}")
        drafts.extract_trip(image=screenshot())
        contents = factory.return_value.__enter__.return_value.models.generate_content.call_args.kwargs["contents"]
        self.assertEqual(contents[1].inline_data.mime_type, "image/png")
        data = contents[1].inline_data.data
        self.assertNotIn(b"do-not-forward-metadata", data)
        with Image.open(BytesIO(data)) as image:
            self.assertEqual(image.size, (80, 50))
        factory.return_value.__enter__.return_value.files.upload.assert_not_called()

    def test_invalid_image_format_and_dimensions_are_rejected(self):
        data = BytesIO()
        Image.new("RGB", (2, 2)).save(data, format="GIF")
        with self.assertRaises(drafts.DraftError):
            drafts.prepare_image(data.getvalue())
        with patch.object(drafts, "MAX_IMAGE_PIXELS", 100), self.assertRaises(drafts.DraftError):
            drafts.prepare_image(screenshot())

    def test_confirmed_fields_are_a_whitelist_for_the_search_form(self):
        _, sample = drafts.example_draft(TODAY)
        fields = drafts.confirmed_search_fields(sample, TODAY)
        self.assertEqual(set(fields), {"trip_origin", "trip_destination", "trip_city", "trip_depart", "trip_return"})
        self.assertEqual(fields["trip_city"], "hotels in Cancun")
        self.assertNotIn("budget", fields)

    def test_review_rejects_missing_fields_bad_dates_and_unresolved_budget(self):
        _, sample = drafts.example_draft(TODAY)
        for changes in ({"origin": None}, {"depart": TODAY - timedelta(days=1)},
                        {"return_date": sample.depart}, {"destination": sample.origin},
                        {"budget_scope": "unknown"}, {"currency": "other"}):
            with self.subTest(changes=changes), self.assertRaises(drafts.DraftError):
                drafts.confirmed_search_fields(sample.model_copy(update=changes), TODAY)

    def test_missing_group_and_budget_context_adds_questions(self):
        result = drafts.TripDraft(budget=2000.0)
        questions = drafts.review_questions(result, TODAY)
        self.assertIn("How many people are traveling?", questions)
        self.assertIn("Is the budget per person or for the whole group?", questions)
        self.assertTrue(any("USD" in question for question in questions))

    def test_offline_example_is_deterministic_and_does_not_invoke_sdk(self):
        factory = self.client_reply("{}")
        text, example = drafts.example_draft(TODAY)
        self.assertIn(example.depart.isoformat(), text)
        self.assertEqual(example.travelers, 4)
        self.assertEqual(drafts.review_questions(example, TODAY), [])
        factory.assert_not_called()


class SdkContractTests(unittest.TestCase):
    def test_actual_sdk_serializes_schema_using_mock_transport(self):
        from google import genai
        real_client = genai.Client
        _, sample = drafts.example_draft(TODAY)
        captured = []

        def handler(request):
            captured.append(json.loads(request.content))
            self.assertEqual(request.url.host, "generativelanguage.googleapis.com")
            self.assertEqual(request.headers.get("x-goog-api-key"), "test-only-not-a-key")
            return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [
                {"text": sample.model_dump_json()}]}, "finishReason": "STOP"}]})

        def factory(**kwargs):
            kwargs["http_options"].httpx_client = httpx.Client(transport=httpx.MockTransport(handler))
            return real_client(**kwargs)

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-key", "GEMINI_MODEL": ""}), \
             patch("google.genai.Client", side_effect=factory), \
             patch("socket.create_connection", side_effect=AssertionError("External HTTP forbidden")):
            self.assertEqual(drafts.extract_trip("Trip plans", today=TODAY), sample)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["generationConfig"]["responseMimeType"], "application/json")
        self.assertNotIn("tools", captured[0])
