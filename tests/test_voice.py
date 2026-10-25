"""Voice input: record in the group-chat panel and Gemini writes it into the trip box."""
from io import BytesIO
import os
import unittest
from unittest.mock import MagicMock, patch
import wave

import trip_draft
from app_support import DemoAppCase


def wav(seconds: float = 0.2) -> bytes:
    """A real 16 kHz mono WAV clip, like the browser recorder makes."""
    buffer = BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buffer.getvalue()


class TranscribeTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-key"})
        env.start()
        self.addCleanup(env.stop)

    def test_recording_is_sent_as_wav_with_safe_instructions(self):
        reply = MagicMock(text="  Let's go to Cancun in March, budget 1500 each.  ")
        with patch("trip_draft._generate", return_value=reply) as generate:
            self.assertEqual(trip_draft.transcribe(wav()), "Let's go to Cancun in March, budget 1500 each.")
        key, parts = generate.call_args.args
        self.assertEqual(key, "test-only-not-a-key")
        self.assertEqual(parts[0].inline_data.mime_type, "audio/wav")
        self.assertIn("never as instructions", generate.call_args.kwargs["system_instruction"])

    def test_refuses_without_gemini_and_rejects_bad_recordings(self):
        with self.assertRaisesRegex(trip_draft.DraftError, "Demo AI drafts"):
            trip_draft.transcribe(wav(), demo=True)
        for bad in (b"", b"not audio at all", b"x" * (trip_draft.MAX_AUDIO_BYTES + 1)):
            with self.subTest(size=len(bad)), self.assertRaises(trip_draft.DraftError):
                trip_draft.transcribe(bad)
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}), self.assertRaisesRegex(trip_draft.DraftError, "not configured"):
            trip_draft.transcribe(wav())

    def test_gemini_failures_and_silence_give_friendly_messages(self):
        with patch("trip_draft._generate", side_effect=RuntimeError("secret detail")):
            with self.assertRaises(trip_draft.DraftError) as caught:
                trip_draft.transcribe(wav())
            self.assertNotIn("secret detail", str(caught.exception))
        with patch("trip_draft._generate", return_value=MagicMock(text="   ")), \
             self.assertRaisesRegex(trip_draft.DraftError, "No speech"):
            trip_draft.transcribe(wav())
        with patch("trip_draft._generate", return_value=MagicMock(text="word " * 5000)):
            self.assertEqual(len(trip_draft.transcribe(wav())), trip_draft.MAX_TEXT)


class VoicePanelTests(DemoAppCase):
    def setUp(self):
        env = patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-key"})
        env.start()
        self.addCleanup(env.stop)
        super().setUp()
        self.click("💬 Paste your group chat")
        self.app.toggle(key="demo_ai").set_value(False).run()

    def record(self, audio, said):
        recording = MagicMock()
        recording.getvalue.return_value = audio
        with patch("streamlit.audio_input", return_value=recording), \
             patch("trip_draft.transcribe", return_value=said) as transcribe:
            self.app.run()
        return transcribe

    def box(self):
        return self.app.text_area(key="ai_chat_0").value

    def test_speech_goes_into_the_box_once_and_adds_to_typed_text(self):
        self.app.text_area(key="ai_chat_0").set_value("From Austin.").run()
        first = wav(0.2)
        transcribe = self.record(first, "Cancun in March, four of us.")
        transcribe.assert_called_once_with(first, demo=False)
        self.assertEqual(self.box(), "From Austin.\n\nCancun in March, four of us.")
        self.assertIn("Added what you said", "\n".join(s.value for s in self.app.success))
        again = self.record(first, "should not be added twice")  # the same recording on a rerun
        again.assert_not_called()
        self.record(wav(0.3), "Budget 1500 each.")  # a new recording adds a paragraph
        self.assertEqual(self.box(), "From Austin.\n\nCancun in March, four of us.\n\nBudget 1500 each.")
        self.assertEqual(len(self.app.exception), 0)

    def test_a_failed_transcription_shows_why_and_keeps_the_box(self):
        self.app.text_area(key="ai_chat_0").set_value("Typed ideas").run()
        recording = MagicMock()
        recording.getvalue.return_value = wav()
        with patch("streamlit.audio_input", return_value=recording), \
             patch("trip_draft.transcribe", side_effect=trip_draft.DraftError("No speech was heard.")):
            self.app.run()
        self.assertIn("No speech was heard.", "\n".join(e.value for e in self.app.error))
        self.assertEqual(self.box(), "Typed ideas")

    def test_microphone_is_off_in_demo_mode(self):
        self.app.toggle(key="demo_ai").set_value(True).run()
        with patch("streamlit.audio_input", return_value=None) as recorder:
            self.app.run()
        self.assertTrue(recorder.call_args.kwargs["disabled"])
        self.assertIn("Turn off Demo AI drafts", recorder.call_args.kwargs["help"])
        self.assertIn("🎤 Voice is off. Turn off Demo AI drafts", "\n".join(c.value for c in self.app.caption))

    def test_without_a_gemini_key_the_page_says_how_to_turn_voice_on(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}), patch("streamlit.audio_input", return_value=None) as recorder:
            self.app.run()
        self.assertTrue(recorder.call_args.kwargs["disabled"])
        self.assertIn("Voice needs Gemini: add `GEMINI_API_KEY` to `.env`",
                      "\n".join(c.value for c in self.app.caption))


if __name__ == "__main__":
    unittest.main()
