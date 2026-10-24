"""Savings calculations can be checked without Streamlit, network access, or keys."""
import unittest
from datetime import date, timedelta
from decimal import Decimal

import planner


class DeadlineTests(unittest.TestCase):
    TODAY = date(2026, 10, 24)

    def test_expired_deadlines_are_rejected_by_both_arithmetic_helpers(self):
        yesterday = self.TODAY - timedelta(days=1)
        with self.assertRaisesRegex(ValueError, "deadline has passed"):
            planner.weeks_until(yesterday, self.TODAY)
        with self.assertRaisesRegex(ValueError, "deadline has passed"):
            planner.weekly_amount(100.0, 20.0, yesterday, self.TODAY)

    def test_missing_deadline_has_a_useful_error(self):
        with self.assertRaisesRegex(ValueError, "Choose a booking deadline"):
            planner.weekly_amount(100.0, 20.0, None, self.TODAY)

    def test_today_requires_the_full_remaining_amount(self):
        self.assertEqual(planner.weeks_until(self.TODAY, self.TODAY), 1)
        self.assertEqual(planner.weekly_amount(100.0, 20.0, self.TODAY, self.TODAY), 80.0)

    def test_booking_after_departure_is_rejected(self):
        departure = self.TODAY + timedelta(days=10)
        with self.assertRaisesRegex(ValueError, "on or before your departure"):
            planner.validate_deadline(departure + timedelta(days=1), self.TODAY, departure)

    def test_booking_on_departure_is_valid(self):
        departure = self.TODAY + timedelta(days=10)
        self.assertIsNone(planner.validate_deadline(departure, self.TODAY, departure))

    def test_future_week_boundaries_preserve_existing_behavior(self):
        for days, periods in [(1, 1), (7, 1), (8, 2), (14, 2), (15, 3)]:
            with self.subTest(days=days):
                self.assertEqual(planner.weeks_until(self.TODAY + timedelta(days=days), self.TODAY), periods)


class WeeklyAmountTests(unittest.TestCase):
    TODAY = date(2026, 10, 24)

    def test_three_contributions_cover_the_remaining_cost(self):
        amount = planner.weekly_amount(100.0, 0.0, self.TODAY + timedelta(days=21), self.TODAY)
        self.assertEqual(amount, 33.34)
        self.assertGreaterEqual(Decimal(str(amount)) * 3, Decimal("100.00"))

    def test_one_cent_goal_is_not_rounded_to_zero(self):
        amount = planner.weekly_amount(100.0, 99.99, self.TODAY + timedelta(days=21), self.TODAY)
        self.assertEqual(amount, 0.01)

    def test_existing_savings_reduce_the_required_contribution(self):
        amount = planner.weekly_amount(600.0, 200.0, self.TODAY + timedelta(weeks=8), self.TODAY)
        self.assertEqual(amount, 50.0)

    def test_cent_balances_are_subtracted_without_float_artifacts(self):
        amount = planner.weekly_amount(0.3, 0.2, self.TODAY + timedelta(weeks=1), self.TODAY)
        self.assertEqual(amount, 0.10)

    def test_fractional_cent_noise_does_not_increase_contribution(self):
        amount = planner.weekly_amount(0.1 + 0.2, 0.2, self.TODAY + timedelta(weeks=1), self.TODAY)
        self.assertEqual(amount, 0.10)

    def test_funded_and_overfunded_goals_need_no_contribution(self):
        for saved in (100.0, 120.0):
            with self.subTest(saved=saved):
                self.assertEqual(planner.weekly_amount(100.0, saved, self.TODAY, self.TODAY), 0.0)

    def test_last_contribution_is_only_the_remaining_balance(self):
        amount = planner.weekly_amount(100.0, 66.68, self.TODAY + timedelta(weeks=1), self.TODAY)
        self.assertEqual(amount, 33.32)

    def test_recalculation_each_week_finishes_at_the_target(self):
        deadline = self.TODAY + timedelta(weeks=3)
        saved = Decimal("0.00")
        for week in range(3):
            amount = planner.weekly_amount(100.0, float(saved), deadline,
                                           self.TODAY + timedelta(weeks=week))
            saved += Decimal(str(amount))
        self.assertEqual(saved, Decimal("100.00"))

    def test_existing_app_call_and_format_remain_supported(self):
        budget = planner.trip_budget(412.0, 445.0, 200.0)
        amount = planner.weekly_amount(budget, 0.0, date.today() + timedelta(weeks=4))
        self.assertIsInstance(amount, float)
        self.assertEqual(f"${amount:,.2f}", "$264.25")
        self.assertIsInstance(planner.price_trend(None, budget), str)


if __name__ == "__main__":
    unittest.main()


class RecommendationTests(unittest.TestCase):
    def test_budget_split_and_rollover(self):
        self.assertEqual([planner.category_allowance(c, 1500) for c in ("Flight", "Hotel", "Food", "Activity")],
                         [525.0, 600.0, 225.0, 150.0])
        # $438 flight picked: the $1,062 left is split among hotel, food and activities.
        self.assertEqual(planner.category_allowance("Hotel", 1062, {"Flight"}), 653.54)
        self.assertEqual(planner.category_allowance("Hotel", 0), 0.0)
        self.assertEqual(planner.category_allowance("Other", 1000), 0.0)

    def test_quality_scores(self):
        self.assertEqual(planner.flight_quality({"duration_min": 180, "stops": 0}, 180), 5.0)
        self.assertEqual(planner.flight_quality({"duration_min": 285, "stops": 1}, 180), 2.41)
        self.assertEqual(planner.hotel_quality({"rating": 4.3}), 4.3)
        self.assertEqual(planner.hotel_quality({"rating": None}), 0.0)

    def test_pick_options(self):
        prices, quality = [623, 924, 1505], [3.9, 4.3, 4.7]
        self.assertEqual(planner.pick_options(prices, quality, 1000),
                         {"recommended": 1, "cheapest": 0, "best_quality": 2})
        # Nothing fits: recommend the cheapest.
        self.assertEqual(planner.pick_options(prices, quality, 600)["recommended"], 0)
        # Ties go to the cheaper option.
        self.assertEqual(planner.pick_options([300, 200], [4.0, 4.0], 500),
                         {"recommended": 1, "cheapest": 1, "best_quality": 1})
        self.assertEqual(planner.pick_options([], [], 500),
                         {"recommended": None, "cheapest": None, "best_quality": None})



class TripInputTests(unittest.TestCase):
    def test_airports_and_dates_are_checked_in_order(self):
        today = date(2026, 10, 24)
        go, back = date(2027, 1, 22), date(2027, 1, 29)
        cases = [(("", "CUN", go, back), "flying from and to"),
                 (("DALLAS AREA", "CUN", go, back), "3-letter code"),
                 (("CUN", "CUN", go, back), "two different airports"),
                 (("AUS", "CUN", None, back), "departure date"),
                 (("AUS", "CUN", go, None), "return date"),
                 (("AUS", "CUN", date(2026, 10, 1), back), "today or later"),
                 (("AUS", "CUN", go, go), "Return must be after")]
        for args, message in cases:
            with self.subTest(args=args):
                self.assertIn(message, planner.trip_input_error(*args, today=today))
        self.assertIsNone(planner.trip_input_error("AUS", "CUN", go, back, today=today))
