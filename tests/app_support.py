"""Offline harness for Streamlit integration tests."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import bank
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


class DemoAppCase(unittest.TestCase):
    """Starts the real app with sample prices and demo money, then clicks Start planning."""

    def setUp(self):
        for context in (
            patch.dict(os.environ, {"SERPAPI_KEY": "", "NESSIE_API_KEY": "", "GEMINI_API_KEY": "",
                                    "PYTHON_DOTENV_DISABLED": "1"}),
            patch.dict(bank._DEMO, {}, clear=True),
            patch.dict(bank._TRIPS, {}, clear=True),
            patch.dict(bank._MERCHANTS, {}, clear=True),
        ):
            context.start()
            self.addCleanup(context.stop)
        network = patch("requests.sessions.Session.request",
                        side_effect=AssertionError("Tests must not make external requests"))
        self.requests = network.start()
        self.addCleanup(network.stop)
        self.addCleanup(self.requests.assert_not_called)
        self.app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.click("Start planning")

    def click(self, label):
        button = next(button for button in self.app.button if button.label == label)
        button.click().run()
        self.assertEqual(len(self.app.exception), 0)

    def add(self, key):
        self.app.button(key=key).click().run()
        self.assertEqual(len(self.app.exception), 0)

    def add_extra(self, description, cost, category="Food"):
        self.app.selectbox[0].set_value(category)
        next(w for w in self.app.text_input if w.label == "What").input(description)
        next(w for w in self.app.number_input if w.label == "Cost ($)").set_value(cost)
        self.click("Add to trip")

    def metrics(self):
        return {m.label: m.value for m in self.app.metric}

    def add_buttons(self):
        return [b for b in self.app.button if b.label == "Add"]

    def visible_text(self):
        return "\n".join(str(element.value) for kind in
                         ("warning", "error", "markdown", "info", "success", "caption")
                         for element in getattr(self.app, kind))

    def plain_text(self):
        """Visible text with markdown "$" escapes removed, as a reader sees it."""
        return self.visible_text().replace("\\$", "$")
