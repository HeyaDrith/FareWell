"""Bank contract tests use fake credentials and mocked HTTP only."""
import os
import unittest
from unittest.mock import Mock, patch

import requests
import bank


class BankTests(unittest.TestCase):
    def setUp(self):
        for context in (patch.dict(bank._DEMO, {}, clear=True),
                        patch.dict(os.environ, {"NESSIE_API_KEY": "test-only-not-a-key"})):
            context.start()
            self.addCleanup(context.stop)
        self.network = patch("requests.sessions.Session.request", side_effect=AssertionError("External HTTP forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.accounts = bank.setup_accounts(True)

    def transfer(self, amount):
        bank.transfer(self.accounts["checking_id"], self.accounts["fund_id"], amount, True)

    def test_demo_accounts_are_isolated_and_money_is_conserved(self):
        self.transfer(19.99)
        other = bank.setup_accounts(True)
        self.assertEqual(bank.get_balance(self.accounts["checking_id"], True), 2980.01)
        self.assertEqual(bank.get_balance(self.accounts["fund_id"], True), 19.99)
        self.assertEqual(bank.get_balance(other["fund_id"], True), 0)
        with self.assertRaises(ValueError):
            bank.transfer(self.accounts["checking_id"], other["fund_id"], 1, True)

    def test_invalid_or_unaffordable_amounts_do_not_change_balances(self):
        for amount in (0, -1, 0.001, float("nan"), float("inf"), 3000.01):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.transfer(amount)
        self.assertEqual(bank.get_balance(self.accounts["checking_id"], True), 3000)
        self.assertEqual(bank.get_balance(self.accounts["fund_id"], True), 0)

    def test_live_insufficient_funds_prevents_post(self):
        with patch.object(bank, "_get", return_value={"balance": 5}), patch.object(bank, "_post") as post:
            with self.assertRaisesRegex(ValueError, "Not enough"):
                bank.transfer("checking", "fund", 6)
            post.assert_not_called()

    def test_live_transfer_preserves_payload_contract(self):
        with patch.object(bank, "_get", return_value={"balance": 3000}), patch.object(bank, "_post") as post:
            self.assertIsNone(bank.transfer("checking", "fund", 19.99))
            path, body = post.call_args.args
            self.assertEqual(path, "/accounts/checking/transfers")
            self.assertEqual((body["payee_id"], body["amount"], body["medium"]), ("fund", 19.99, "balance"))

    def test_demo_ids_cannot_reach_live_service(self):
        with self.assertRaises(ValueError):
            bank.get_balance(self.accounts["fund_id"])
        with self.assertRaises(ValueError):
            bank.transfer("checking", self.accounts["fund_id"], 1)

    def test_https_and_no_redirects(self):
        response = Mock(status_code=200)
        response.json.return_value = {"balance": 100}
        with patch("requests.request", return_value=response) as request:
            self.assertEqual(bank.get_balance("checking"), 100)
        self.assertTrue(request.call_args.args[1].startswith("https://"))
        self.assertFalse(request.call_args.kwargs["allow_redirects"])

    def test_service_errors_and_redirects_do_not_expose_credentials(self):
        with patch("requests.request", side_effect=requests.Timeout("https://example.test/?key=secret-sentinel")):
            with self.assertRaises(bank.BankError) as result:
                bank.get_balance("checking")
        self.assertNotIn("secret-sentinel", str(result.exception))
        for status in (302, 401, 500):
            with patch("requests.request", return_value=Mock(status_code=status)) as request:
                with self.assertRaises(bank.BankError):
                    bank.get_balance("checking")
                self.assertEqual(request.call_count, 1)
