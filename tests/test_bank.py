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

    @staticmethod
    def fake_get(balance, deposits=(), withdrawals=()):
        def get(path):
            if path.endswith("/deposits"):
                return [{"amount": a, "status": "completed"} for a in deposits]
            if path.endswith("/withdrawals"):
                return [{"amount": a, "status": "completed"} for a in withdrawals]
            return {"balance": balance}
        return get

    def test_live_insufficient_funds_prevents_post(self):
        with patch.object(bank, "_get", side_effect=self.fake_get(5)), patch.object(bank, "_post") as post:
            with self.assertRaisesRegex(ValueError, "Not enough"):
                bank.transfer("checking", "fund", 6)
            post.assert_not_called()

    def test_live_transfer_records_withdrawal_and_deposit(self):
        with patch.object(bank, "_get", side_effect=self.fake_get(3000)), patch.object(bank, "_post") as post:
            self.assertIsNone(bank.transfer("checking", "fund", 20))
            (w_path, w_body), (d_path, d_body) = (c.args for c in post.call_args_list)
            self.assertEqual((w_path, d_path), ("/accounts/checking/withdrawals", "/accounts/fund/deposits"))
            for body in (w_body, d_body):
                self.assertEqual((body["amount"], body["status"], body["medium"]), (20, "completed", "balance"))
            self.assertNotIn("payee_id", w_body)

    def test_live_transfer_rejects_fractional_dollars_before_posting(self):
        with patch.object(bank, "_get", side_effect=self.fake_get(3000)), patch.object(bank, "_post") as post:
            with self.assertRaisesRegex(ValueError, "whole dollars"):
                bank.transfer("checking", "fund", 19.99)
            post.assert_not_called()

    def test_live_balance_includes_completed_deposits_and_withdrawals(self):
        with patch.object(bank, "_get", side_effect=self.fake_get(3000, deposits=[100], withdrawals=[40])):
            self.assertEqual(bank.get_balance("checking"), 3060)

    def test_demo_ids_cannot_reach_live_service(self):
        with self.assertRaises(ValueError):
            bank.get_balance(self.accounts["fund_id"])
        with self.assertRaises(ValueError):
            bank.transfer("checking", self.accounts["fund_id"], 1)

    def test_https_and_no_redirects(self):
        response = Mock(status_code=200)
        response.json.side_effect = [{"balance": 100}, [], []]  # balance, deposits, withdrawals
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


class TripBudgetTests(unittest.TestCase):
    """Trip budget tracker: typed budget -> picks as purchases -> savings as deposits."""

    def setUp(self):
        for context in (patch.dict(bank._TRIPS, {}, clear=True),
                        patch.dict(bank._MERCHANTS, {}, clear=True),
                        patch.dict(os.environ, {"NESSIE_API_KEY": "test-only-not-a-key"})):
            context.start()
            self.addCleanup(context.stop)
        self.network = patch("requests.sessions.Session.request", side_effect=AssertionError("External HTTP forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def live_trip(self):
        return {"budget": 1500.0, "budget_id": "bud", "savings_id": "sav", "demo": False, "removed": []}

    def test_demo_trip_totals_and_removal(self):
        trip = bank.create_trip(1500, True)
        bank.record_pick(trip, "Flight", "Southwest", 412, saved=26)
        hotel = bank.record_pick(trip, "Hotel", "Seaside Inn", 623, saved=301)
        bank.record_pick(trip, "Food", "Tacos", 30)
        s = bank.get_summary(trip)
        self.assertEqual((s["spent"], s["saved"], s["remaining"], s["final_total"]), (1065, 327, 435, 1065))
        self.assertFalse(s["over_budget"])
        self.assertEqual([p["description"] for p in s["picks"]], ["Southwest", "Seaside Inn", "Tacos"])
        bank.remove_pick(trip, hotel["id"])
        self.assertEqual(bank.get_summary(trip)["spent"], 442)

    def test_whole_dollars_cost_rounds_up_savings_round_down(self):
        trip = bank.create_trip(100, True)
        pick = bank.record_pick(trip, "Food", "Lunch", 12.01, saved=3.99)
        self.assertEqual((pick["amount"], pick["saved"]), (13, 3))
        self.assertEqual(bank.record_pick(trip, "Food", "Gum", 0.004 + 1, saved=-5)["saved"], 0)

    def test_over_budget(self):
        trip = bank.create_trip(300, True)
        bank.record_pick(trip, "Flight", "Pricey", 450)
        s = bank.get_summary(trip)
        self.assertTrue(s["over_budget"])
        self.assertEqual(s["remaining"], -150)

    def test_invalid_budgets_and_costs_raise_value_error(self):
        for bad in (0, -5, 0.001, "abc", None, float("nan"), float("inf")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                bank.create_trip(bad, True)
        trip = bank.create_trip(100, True)
        with self.assertRaises(ValueError):
            bank.record_pick(trip, "Food", "Free", 0)

    def test_unknown_category_and_blank_description(self):
        trip = bank.create_trip(100, True)
        pick = bank.record_pick(trip, "Spaceship", "  ", 10)
        self.assertEqual((pick["category"], pick["description"]), ("Other", "Other"))

    def test_demo_trips_cannot_reach_live_service(self):
        trip = bank.create_trip(100, True)
        live_view = {**trip, "demo": False}
        with self.assertRaises(ValueError):
            bank.record_pick(live_view, "Food", "Tacos", 10)
        with self.assertRaises(ValueError):
            bank.list_picks(live_view)

    def test_live_create_trip_opens_budget_and_savings_accounts(self):
        ids = iter([{"objectCreated": {"_id": "cust"}}, {"objectCreated": {"_id": "bud"}},
                    {"objectCreated": {"_id": "sav"}}])
        with patch.object(bank, "_post", side_effect=lambda path, body: next(ids)) as post:
            trip = bank.create_trip(1500.4)
        self.assertEqual(trip, {"budget": 1501.0, "budget_id": "bud", "savings_id": "sav",
                                "demo": False, "removed": []})
        bodies = [c.args[1] for c in post.call_args_list]
        self.assertEqual(bodies[1], {"type": "Checking", "nickname": "Trip Budget", "rewards": 0, "balance": 1501})
        self.assertEqual(bodies[2], {"type": "Savings", "nickname": "Trip Savings", "rewards": 0, "balance": 0})

    def test_live_pick_posts_purchase_and_tagged_savings_deposit(self):
        def post(path, body):
            if path == "/merchants":
                return {"objectCreated": {"_id": "m1"}}
            if path.endswith("/purchases"):
                return {"objectCreated": {**body, "_id": "p1"}}
            return {"objectCreated": {"_id": "d1"}}

        with patch.object(bank, "_post", side_effect=post) as posted:
            pick = bank.record_pick(self.live_trip(), "Flight", "Southwest", 412.5, saved=26.9)
            bank.record_pick(self.live_trip(), "Flight", "Again", 100)
        self.assertEqual((pick["id"], pick["amount"], pick["saved"]), ("p1", 413, 26))
        calls = [(c.args[0], c.args[1]) for c in posted.call_args_list]
        self.assertEqual([p for p, _ in calls],
                         ["/merchants", "/accounts/bud/purchases", "/accounts/sav/deposits", "/accounts/bud/purchases"])
        purchase, deposit = calls[1][1], calls[2][1]
        self.assertEqual((purchase["amount"], purchase["status"], purchase["merchant_id"]), (413, "completed", "m1"))
        self.assertEqual(purchase["description"], "[Flight] Southwest")
        self.assertEqual((deposit["amount"], deposit["status"]), (26, "completed"))
        self.assertTrue(deposit["description"].startswith("[for:p1]"))

    def test_live_summary_orders_picks_maps_savings_and_skips_removed(self):
        def get(path):
            if path.endswith("/purchases"):  # Nessie returns newest first
                return [{"_id": "p3", "amount": 30, "description": "[Food] Tacos", "status": "completed"},
                        {"_id": "p2", "amount": 99, "description": "[Hotel] Old", "status": "cancelled"},
                        {"_id": "p1", "amount": 412, "description": "[Flight] Southwest", "status": "completed"}]
            return [{"_id": "d1", "amount": 26, "description": "[for:p1] Saved on Southwest", "status": "completed"},
                    {"_id": "d9", "amount": 500, "description": "untagged", "status": "completed"}]

        trip = self.live_trip()
        with patch.object(bank, "_get", side_effect=get):
            s = bank.get_summary(trip)
            self.assertEqual([(p["category"], p["saved"]) for p in s["picks"]], [("Flight", 26), ("Food", 0)])
            self.assertEqual((s["spent"], s["saved"], s["remaining"]), (442, 26, 1058))
            bank.remove_pick(trip, "p1")
            bank.remove_pick(trip, "p1")
            self.assertEqual(trip["removed"], ["p1"])
            self.assertEqual(bank.get_summary(trip)["spent"], 30)

    def test_live_failed_deposit_hides_purchase_with_safe_message(self):
        def post(path, body):
            if path.endswith("/deposits"):
                raise bank.BankError("Nessie could not confirm the request.")
            if path == "/merchants":
                return {"objectCreated": {"_id": "m1"}}
            return {"objectCreated": {**body, "_id": "p1"}}

        trip = self.live_trip()
        with patch.object(bank, "_post", side_effect=post):
            with self.assertRaisesRegex(bank.BankError, "savings"):
                bank.record_pick(trip, "Flight", "Southwest", 412, saved=26)
        self.assertEqual(trip["removed"], ["p1"])

    def test_live_trip_errors_do_not_expose_credentials(self):
        with patch("requests.request", side_effect=requests.Timeout("https://x.test/?key=secret-sentinel")):
            with self.assertRaises(bank.BankError) as result:
                bank.create_trip(100)
        self.assertNotIn("secret-sentinel", str(result.exception))
