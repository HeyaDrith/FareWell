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

    def test_custom_amount_this_week_and_the_rest_of_the_plan_adjusts(self):
        fund = funding.create(100, TODAY + timedelta(days=21), True, TODAY)  # planned 34, 34, 32
        # Less this week: the $90 left is spread over the remaining weeks.
        self.assertEqual([r['Contribution ($)'] for r in funding.plan_after(fund, 0, 10, TODAY)], [45, 45])
        funding.contribute(fund, TODAY, amount=10)
        self.assertEqual(funding.balances(fund), (2990, 10))
        self.assertEqual(fund['history'][-1]['Amount ($)'], 10)
        self.assertEqual([r['Contribution ($)'] for r in funding.plan(fund, 10, TODAY)], [45, 45])
        funding.contribute(fund, TODAY, amount=50)  # more than planned: the last week only needs $40
        self.assertEqual([r['Contribution ($)'] for r in funding.plan(fund, 60, TODAY)], [40])
        for bad in (0, 2.5, float('nan')):
            with self.subTest(amount=bad), self.assertRaises(ValueError):
                funding.contribute(fund, TODAY, amount=bad)
        self.assertEqual(funding.balances(fund), (2940, 60))  # nothing moved for the rejected amounts
        self.assertIsNone(fund['pending'])

    def test_live_fund_keeps_its_limits(self):
        fund = funding.create(100, TODAY + timedelta(days=21), True, TODAY)
        fund['demo'] = False
        with patch('funding.balances', return_value=(3000, 60)), patch('bank.transfer') as transfer:
            with self.assertRaises(ValueError):
                funding.contribute(fund, TODAY, amount=41)  # more than the $40 still to save
        with patch('funding.balances', return_value=(3000, 100)), patch('bank.transfer') as transfer:
            with self.assertRaises(ValueError):
                funding.contribute(fund, TODAY, amount=50)  # funded: no extra weeks outside a demo
        transfer.assert_not_called()
        with self.assertRaises(ValueError):
            funding.add_demo_money(fund)

    def test_demo_has_no_limits_so_weeks_can_be_simulated(self):
        fund = funding.create(100, TODAY + timedelta(days=7), True, TODAY)
        funding.contribute(fund, TODAY, amount=500)  # more than the target
        self.assertEqual(funding.balances(fund), (2500, 500))
        for week in range(1, 6):  # past the goal and the deadline: one simulated week each
            funding.contribute(fund, TODAY, amount=500)
            self.assertEqual(fund['history'][-1]['Date'], TODAY + timedelta(days=7 * week))
        self.assertEqual(funding.balances(fund), (0, 3000))
        with self.assertRaises(ValueError):
            funding.contribute(fund, TODAY, amount=1)  # checking is empty...
        funding.add_demo_money(fund)  # ...until a simulated paycheck arrives
        funding.contribute(fund, TODAY, amount=1000)
        self.assertEqual(funding.balances(fund), (0, 4000))
        self.assertEqual(len(fund['history']), 7)
        with self.assertRaises(ValueError):
            funding.contribute(fund, TODAY)  # an extra week needs an amount; there's no plan to follow

    def test_custom_amount_needs_the_money_in_checking(self):
        fund = funding.create(5000, TODAY + timedelta(days=70), True, TODAY)
        with self.assertRaises(ValueError):
            funding.contribute(fund, TODAY, amount=3001)  # checking starts with $3,000
        self.assertEqual(funding.balances(fund), (3000, 0))

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

    def test_page_contributes_a_custom_amount_and_shows_the_adjusted_plan(self):
        self.open_fund()
        self.click('Create Trip Fund')
        box = next(n for n in self.app.number_input if n.label == 'Amount this week ($)')
        planned = box.value
        box.set_value(25).run()
        self.assertIn('to reach your target by the deadline', '\n'.join(c.value for c in self.app.caption))
        self.click("Run this week's transfer")
        self.assertEqual(self.metrics()['Funded'], '$25.00')
        self.assertIn('The rest of your plan has adjusted', self.visible_text())
        box = next(n for n in self.app.number_input if n.label == 'Amount this week ($)')
        self.assertGreater(box.value, planned)  # resets to next week's (now larger) planned amount

    def test_today_goal_completes_and_rerun_does_not_transfer(self):
        self.open_fund()
        self.app.date_input(key='fund_deadline_demo').set_value(date.today()).run()
        self.click('Create Trip Fund')
        self.click("Run this week's transfer")
        self.assertEqual(self.metrics()['Funded'], '$1,500.00')
        self.app.run()
        self.assertEqual(self.metrics()['Funded'], '$1,500.00')  # a rerun never transfers again
        # Demo: the plan is done, but deposits can keep simulating weeks.
        self.assertIn('keep depositing to simulate more weeks', '\n'.join(c.value for c in self.app.caption))
        self.click("Run this week's transfer")
        self.assertEqual(self.metrics()['Funded'], '$1,550.00')  # the extra-week amount starts at $50

    def test_page_adds_demo_money_when_checking_runs_low(self):
        self.open_fund()
        self.app.number_input(key='fund_target_demo').set_value(5000).run()
        self.click('Create Trip Fund')
        self.assertIn('Add demo money below', self.visible_text())
        self.click('💵 Add \\$1,000 demo money to checking')
        self.assertIn('checking \\$4,000.00', self.visible_text())

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
