import os
from datetime import date
from unittest.mock import patch

import bank
from app_support import DemoAppCase


class AppFundingTests(DemoAppCase):
    def test_insufficient_funds_and_fully_funded_hide_transfer(self):
        self.click("Create my Trip Fund")
        self.set_deadline(date.today())
        balances = next(iter(bank._DEMO.values()))
        balances["checking"] = 1.0
        self.app.run()
        self.assertIn("Not enough money", self.visible_text())
        self.assertFalse(any("transfer" in button.label.lower() for button in self.app.button))
        balances.update(checking=1765.0, fund=1235.0)
        self.app.run()
        self.assertIn("fully funded", self.visible_text())
        self.assertFalse(any("transfer" in button.label.lower() for button in self.app.button))

    def test_service_failures_are_safe_and_do_not_crash(self):
        with patch("bank.setup_accounts", side_effect=RuntimeError("secret-sentinel")):
            self.click("Create my Trip Fund")
        self.assertIn("Could not create", self.visible_text())
        self.assertNotIn("secret-sentinel", self.visible_text())
        self.click("Create my Trip Fund")
        with patch("bank.get_balance", side_effect=RuntimeError("secret-sentinel")):
            self.app.run()
            self.assertEqual(len(self.app.exception), 0)
        self.assertIn("Funding is paused", self.visible_text())
        self.assertNotIn("secret-sentinel", self.visible_text())

    def test_failed_demo_transfer_leaves_balances_unchanged(self):
        self.click("Create my Trip Fund")
        self.set_deadline(date.today())
        with patch("bank.transfer", side_effect=RuntimeError("secret-sentinel")):
            self.click("Transfer today ($1,235.00)")
        self.assertIn("Could not confirm", self.visible_text())
        self.assertNotIn("secret-sentinel", self.visible_text())
        self.assertEqual(list(bank._DEMO.values()), [{"checking": 3000.0, "fund": 0.0}])

    def test_uncertain_live_transfer_blocks_repeat_submission(self):
        with patch.dict(os.environ, {"NESSIE_API_KEY": "test-only-not-a-key"}), \
             patch("bank.setup_accounts", return_value={"checking_id": "checking", "fund_id": "fund"}), \
             patch("bank.get_balance", side_effect=lambda account, demo: 3000.0 if account == "checking" else 0.0), \
             patch("bank.transfer", side_effect=bank.BankError("secret-sentinel")) as transfer:
            self.app.toggle[0].set_value(False).run()
            self.click("Search prices")
            self.click("Create my Trip Fund")
            self.set_deadline(date.today())
            self.click("Transfer today ($1,235.00)")
            self.app.run()
            self.assertIn("Further transfers are paused", self.visible_text())
            self.assertNotIn("secret-sentinel", self.visible_text())
            self.assertFalse(any("transfer" in button.label.lower() for button in self.app.button))
            self.assertEqual(transfer.call_count, 1)
