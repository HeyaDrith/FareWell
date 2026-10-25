from datetime import date, timedelta
import unittest
from unittest.mock import patch
import bank
import funding
from app_support import DemoAppCase

TODAY = date(2026, 10, 24)


class FundingTests(unittest.TestCase):
    def test_complete_schedule_and_final_payment(self):
        fund = funding.create(100, TODAY + timedelta(days=21), True, TODAY)
        self.assertEqual([r['Contribution ($)'] for r in funding.plan(fund, 0, TODAY)], [34, 34, 32])
        for _ in range(3):
            funding.contribute(fund, TODAY)
        self.assertEqual(funding.balances(fund), (2900, 100))
        self.assertEqual(len(fund['history']), 3)
        with self.assertRaises(ValueError):
            funding.contribute(fund, TODAY)

    def test_today_deadline_and_insufficient_funds(self):
        fund = funding.create(4000, TODAY, True, TODAY)
        with self.assertRaises(ValueError):
            funding.contribute(fund, TODAY)
        self.assertEqual(funding.balances(fund), (3000, 0))
        self.assertIsNone(fund['pending'])

    def test_deadline_validation_and_expiry(self):
        with self.assertRaises(ValueError):
            funding.create(100, TODAY + timedelta(days=2), True, TODAY, TODAY)
        fund = funding.create(100, TODAY, True, TODAY)
        self.assertEqual(funding.plan(fund, 0, TODAY + timedelta(days=1)), [])

    def test_live_uncertainty_blocks_retry_and_reconciles_once(self):
        fund = {'checking_id': 'c', 'fund_id': 'f', 'demo': False, 'target': 100,
                'deadline': TODAY, 'next_due': TODAY, 'history': [], 'pending': None}
        with patch('funding.balances', return_value=(3000, 0)), patch('bank.transfer', side_effect=bank.BankError('failed')) as transfer:
            with self.assertRaises(bank.BankError): funding.contribute(fund, TODAY)
            with self.assertRaises(bank.BankError): funding.contribute(fund, TODAY)
            self.assertEqual(transfer.call_count, 1)
        with patch('funding.balances', return_value=(2900, 0)):
            funding.reconcile(fund)
            self.assertIsNotNone(fund['pending'])
        with patch('funding.balances', return_value=(2900, 100)):
            funding.reconcile(fund)
            funding.reconcile(fund)
        self.assertEqual(len(fund['history']), 1)
        self.assertIsNone(fund['pending'])

    def test_live_week_cannot_be_run_twice(self):
        fund = funding.create(100, TODAY + timedelta(days=14), True, TODAY)
        fund['demo'] = False
        with patch('funding.balances', return_value=(3000, 0)), patch('bank.transfer') as transfer:
            funding.contribute(fund, TODAY)
            with self.assertRaises(ValueError): funding.contribute(fund, TODAY)
            self.assertEqual(transfer.call_count, 1)


class FundingPageTests(DemoAppCase):
    def open_fund(self):
        self.app.switch_page('views/fund.py').run()
        self.assertEqual(len(self.app.exception), 0)

    def test_create_transfer_update_and_navigation_preserve_balance(self):
        self.add('flight-0')
        self.open_fund()
        self.assertEqual(self.app.number_input(key='fund_target_demo').value, 412)
        self.click('Create Trip Fund')
        self.click("Run this week's transfer")
        funded = self.metrics()['Funded']
        self.assertNotEqual(funded, '$0.00')
        self.app.number_input(key='fund_target_demo').set_value(500).run()
        self.assertTrue(next(b for b in self.app.button if b.label == "Run this week's transfer").disabled)
        self.click('Update savings plan')
        self.assertEqual(self.metrics()['Funded'], funded)
        self.app.switch_page('views/home.py').run()
        self.open_fund()
        self.assertEqual(self.metrics()['Funded'], funded)

    def test_today_goal_completes_and_rerun_does_not_transfer(self):
        self.open_fund()
        self.app.date_input(key='fund_deadline_demo').set_value(date.today()).run()
        self.click('Create Trip Fund')
        self.click("Run this week's transfer")
        self.assertEqual(self.metrics()['Funded'], '$1,500.00')
        self.app.run()
        self.assertEqual(self.metrics()['Funded'], '$1,500.00')
        self.assertTrue(next(b for b in self.app.button if b.label == "Run this week's transfer").disabled)

    def test_bank_mode_switch_keeps_demo_fund_isolated(self):
        self.open_fund()
        self.click('Create Trip Fund')
        self.click("Run this week's transfer")
        original = self.app.session_state.weekly_funds['demo']['fund_id']
        with patch.dict('os.environ', {'NESSIE_API_KEY': 'test-only'}):
            self.app.toggle(key='demo_bank').set_value(False).run()
            self.assertEqual(len(self.app.exception), 0)
            self.assertIn('Create Trip Fund', [b.label for b in self.app.button])
            self.app.toggle(key='demo_bank').set_value(True).run()
        self.assertEqual(self.app.session_state.weekly_funds['demo']['fund_id'], original)
        self.assertNotEqual(self.metrics()['Funded'], '$0.00')
