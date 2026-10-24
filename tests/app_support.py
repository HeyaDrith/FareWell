"""Offline harness for Streamlit integration tests."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import bank
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


class DemoAppCase(unittest.TestCase):
    def setUp(self):
        for context in (
            patch.dict(os.environ, {"SERPAPI_KEY": "", "NESSIE_API_KEY": "",
                                    "PYTHON_DOTENV_DISABLED": "1"}),
            patch.dict(bank._DEMO, {}, clear=True),
        ):
            context.start()
            self.addCleanup(context.stop)
        network = patch("requests.sessions.Session.request",
                        side_effect=AssertionError("Tests must not make external requests"))
        self.requests = network.start()
        self.addCleanup(network.stop)
        self.addCleanup(self.requests.assert_not_called)
        self.app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.click("Search prices")

    def click(self, label):
        button = next(button for button in self.app.button if button.label == label)
        button.click().run()
        self.assertEqual(len(self.app.exception), 0)

    def set_deadline(self, deadline):
        self.app.date_input(key="deadline").set_value(deadline).run()
        self.assertEqual(len(self.app.exception), 0)

    def assert_funding_blocked(self, message):
        self.assertTrue(any(message in warning.value for warning in self.app.warning))
        self.assertFalse(any("transfer" in button.label.lower() or button.label == "Create my Trip Fund"
                             for button in self.app.button))
        for balances in bank._DEMO.values():
            self.assertEqual(balances, {"checking": 3000.0, "fund": 0.0})

    def visible_text(self):
        return "\n".join(str(element.value) for kind in
                         ("warning", "error", "markdown", "info", "success")
                         for element in getattr(self.app, kind))
