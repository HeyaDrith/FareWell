"""Exercise the actual Streamlit flow with cached travel and simulated money."""
import os
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import bank
from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"


class AppDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "SERPAPI_KEY": "", "NESSIE_API_KEY": "",
            "PYTHON_DOTENV_DISABLED": "1",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.balances = patch.dict(bank._DEMO, {"checking": 3000.0, "fund": 0.0}, clear=True)
        self.balances.start()
        self.addCleanup(self.balances.stop)
        self.network = patch("requests.sessions.Session.request",
                             side_effect=AssertionError("Tests must not make external requests"))
        self.requests = self.network.start()
        self.addCleanup(self.network.stop)
        self.app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.click("Search prices")

    def tearDown(self):
        self.requests.assert_not_called()

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
        self.assertEqual(bank._DEMO, {"checking": 3000.0, "fund": 0.0})

    def test_expired_deadline_blocks_account_creation(self):
        self.set_deadline(date.today() - timedelta(days=1))
        self.assert_funding_blocked("deadline has passed")

    def test_expired_deadline_blocks_transfer_and_can_be_corrected(self):
        self.click("Create my Trip Fund")
        self.set_deadline(date.today() - timedelta(days=1))
        self.assert_funding_blocked("deadline has passed")
        self.set_deadline(date.today() + timedelta(days=28))
        transfer = next(button for button in self.app.button if "transfer" in button.label.lower())
        transfer.click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(bank._DEMO, {"checking": 2735.75, "fund": 264.25})

    def test_deadline_after_departure_blocks_funding(self):
        departure = next(widget.value for widget in self.app.date_input if widget.label == "Depart")
        self.set_deadline(departure + timedelta(days=1))
        self.assert_funding_blocked("on or before your departure")

    def test_cleared_deadline_shows_message_without_crashing(self):
        self.set_deadline(None)
        self.assert_funding_blocked("Choose a booking deadline")

    def test_today_labels_and_transfers_the_full_remaining_amount(self):
        self.click("Create my Trip Fund")
        self.set_deadline(date.today())
        self.assertTrue(any("$1,057.00 today" in text.value for text in self.app.markdown))
        self.click("Transfer today ($1,057.00)")
        self.assertEqual(bank._DEMO, {"checking": 1943.0, "fund": 1057.0})
        self.assertTrue(any("fully funded" in success.value for success in self.app.success))


if __name__ == "__main__":
    unittest.main()
