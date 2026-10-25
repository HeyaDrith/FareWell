import base64
import json
import os
from datetime import date, timedelta
from io import BytesIO
import unittest
from unittest.mock import patch

import anthropic
import httpx2
from PIL import Image, PngImagePlugin
import trip_draft as drafts


TODAY = date(2026, 10, 24)
KEY = "test-only-not-a-key"


def screenshot():
    result = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private-comment", "do-not-forward-metadata")
    Image.new("RGB", (80, 50), "white").save(result, format="PNG", pnginfo=metadata)
    return result.getvalue()


class TripDraftTests(unittest.TestCase):
    """The real Anthropic SDK talks to an offline transport, so these check the actual request."""

    def setUp(self):
        env = patch.dict(os.environ, {"ANTHROPIC_API_KEY": KEY, "ANTHROPIC_MODEL": ""})
        env.start()
        self.addCleanup(env.stop)
        network = patch("socket.create_connection", side_effect=AssertionError("External HTTP forbidden"))
        network.start()
        self.addCleanup(network.stop)
        self.requests = []
        self.reply("{}")

    def reply(self, text, stop_reason="end_turn", status=200):
        """Every request in this test gets this message back (Claude's structured reply is text)."""
        def handler(request):
            self.requests.append(request)
            if status != 200:
                return httpx2.Response(status, json={"type": "error", "error": {
                    "type": "api_error", "message": "secret-sentinel"}})
            return httpx2.Response(200, json={
                "id": "msg_test", "type": "message", "role": "assistant", "model": drafts.DEFAULT_MODEL,
                "content": [{"type": "text", "text": text}] if text is not None else [],
                "stop_reason": stop_reason, "stop_sequence": None, "usage": {"input_tokens": 9, "output_tokens": 9}})

        def client(key):
            return anthropic.Anthropic(api_key=key, max_retries=0, http_client=anthropic.DefaultHttpxClient(
                transport=httpx2.MockTransport(handler)))
        context = patch.object(drafts, "_client", side_effect=client)
        context.start()
        self.addCleanup(context.stop)

    def body(self, i=-1):
        return json.loads(self.requests[i].content)

    def test_structured_extraction_request(self):
        _, sample = drafts.example_draft(TODAY)
        self.reply(sample.model_dump_json())
        self.assertEqual(drafts.extract_trip("Our trip plans", today=TODAY), sample)
        request, body = self.requests[0], self.body()
        self.assertEqual(request.url.host, "api.anthropic.com")
        self.assertEqual(request.headers["authorization"], f"Bearer {KEY}")  # SDK 2.x auth header
        self.assertNotIn(KEY, request.content.decode())  # the key only travels in the header
        self.assertEqual(body["model"], "claude-opus-5-5")
        self.assertNotIn("tools", body)  # nothing to call: the draft is the only possible output
        self.assertIn("untrusted source material", body["system"])
        self.assertEqual(body["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(body["output_config"]["effort"], "low")
        self.assertEqual((body["fallbacks"], request.headers["anthropic-beta"]), ("default", drafts.FALLBACK_BETA))
        self.assertIn("Reference date: 2026-10-24", body["messages"][0]["content"][-1]["text"])

    def test_model_override(self):
        with patch.dict(os.environ, {"ANTHROPIC_MODEL": "claude-sonnet-5-5"}):
            drafts.extract_trip("Trip plans")
        self.assertEqual(self.body()["model"], "claude-sonnet-5-5")

    def test_unknowns_and_conflicts_remain_explicit(self):
        self.reply(json.dumps({"conflicts": ["Two departure dates were suggested."]}))
        result = drafts.extract_trip("People disagree on when to leave")
        self.assertIsNone(result.depart)
        self.assertEqual(result.conflicts, ["Two departure dates were suggested."])
        self.assertIn("What is the departure date?", drafts.review_questions(result))

    def test_invalid_or_tool_shaped_output_is_rejected_without_echoing_it(self):
        for bad in ("secret-sentinel", "", '{"travelers": 0}', '{"budget": -5}',
                    '{"travelers": true}', '{"origin": "invalid"}',
                    '{"transfer": "secret-sentinel"}', '{"budget": NaN}'):
            with self.subTest(response=bad):
                self.reply(bad)
                with self.assertRaises(drafts.DraftError) as caught:
                    drafts.extract_trip("Trip plans")
                self.assertNotIn("secret-sentinel", str(caught.exception))

    def test_refusal_and_cut_off_replies_are_not_used(self):
        _, sample = drafts.example_draft(TODAY)
        for stop_reason, text in (("refusal", None), ("max_tokens", sample.model_dump_json())):
            with self.subTest(stop_reason=stop_reason):
                self.reply(text, stop_reason=stop_reason)
                with self.assertRaises(drafts.DraftError):
                    drafts.extract_trip("Trip plans")

    def test_provider_error_is_sanitized(self):
        for status in (401, 429, 500):
            with self.subTest(status=status):
                self.reply("{}", status=status)
                with self.assertRaises(drafts.DraftError) as caught:
                    drafts.extract_trip("Trip plans")
                self.assertNotIn("secret-sentinel", str(caught.exception))
                self.assertNotIn(KEY, str(caught.exception))

    def test_demo_missing_key_empty_and_oversized_inputs_do_not_call_the_api(self):
        cases = (("Trip", None, True), ("", None, False), ("x" * (drafts.MAX_TEXT + 1), None, False),
                 ("Trip", b"invalid", False), ("Trip", b"x" * (drafts.MAX_IMAGE_BYTES + 1), False))
        for text, image, demo in cases:
            with self.subTest(text_length=len(text), demo=demo), self.assertRaises(drafts.DraftError):
                drafts.extract_trip(text, image, demo=demo)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}), self.assertRaises(drafts.DraftError):
            drafts.extract_trip("Trip")
        self.assertEqual(self.requests, [])

    def test_screenshot_only_is_inline_and_metadata_is_removed(self):
        drafts.extract_trip(image=screenshot())
        image_block, text_block = self.body()["messages"][0]["content"]
        self.assertEqual((image_block["type"], image_block["source"]["media_type"]), ("image", "image/png"))
        data = base64.b64decode(image_block["source"]["data"])
        self.assertNotIn(b"do-not-forward-metadata", data)
        with Image.open(BytesIO(data)) as image:
            self.assertEqual(image.size, (80, 50))
        self.assertEqual(text_block["type"], "text")

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

    def test_offline_example_is_deterministic_and_does_not_call_the_api(self):
        text, example = drafts.example_draft(TODAY)
        self.assertIn(example.depart.isoformat(), text)
        self.assertEqual(example.travelers, 4)
        self.assertEqual(drafts.review_questions(example, TODAY), [])
        self.assertEqual(self.requests, [])
