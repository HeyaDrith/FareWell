"""Exercise the actual Streamlit flow with cached travel and simulated money."""
import unittest
from datetime import date, timedelta

import bank
from app_support import DemoAppCase


class AppDeadlineTests(DemoAppCase):

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
        self.assertEqual(list(bank._DEMO.values()), [{"checking": 2691.25, "fund": 308.75}])

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
        self.assertTrue(any("$1,235.00 today" in text.value for text in self.app.markdown))
        self.click("Transfer today ($1,235.00)")
        self.assertEqual(list(bank._DEMO.values()), [{"checking": 1765.0, "fund": 1235.0}])
        self.assertTrue(any("fully funded" in success.value for success in self.app.success))


if __name__ == "__main__":
    unittest.main()
