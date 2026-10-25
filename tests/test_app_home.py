"""Homepage dashboard: honest empty states, then real numbers from the planned and locked trip."""
import os
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app_support import APP, DemoAppCase


class HomePageTests(DemoAppCase):
    def html(self) -> str:
        return "\n".join(element.proto.body for element in self.app.get("html"))

    def go_home(self):
        self.app.switch_page("views/home.py").run()
        self.assertEqual(len(self.app.exception), 0)

    def test_dashboard_after_planning_and_locking(self):
        self.add("flight-0")  # Southwest $412
        self.add("hotel-0")   # Seaside Budget Inn $623
        self.go_home()
        html = self.html()
        self.assertIn("<h3>Finances</h3>", html)
        self.assertIn("2 accounts · Demo money", html)
        for row in ("$1,500", "$1,035", "$465", "$327"):  # budget, spent, remaining, saved
            self.assertIn(row, html)
        self.assertIn("No trips yet", html)  # nothing locked in yet
        self.assertIn("Stay on budget", html)
        self.assertIn("2/4", html)  # flight + hotel of the four parts
        self.assertEqual([p.proto.label for p in self.app.get("page_link")], ["Continue planning"])

        self.app.switch_page("views/plan.py").run()
        self.click("🔒 Lock in my trip")
        self.go_home()
        html = self.html()
        self.assertIn("1 trip · $1,035.00", html)
        self.assertIn("AUS → CUN", html)
        self.assertIn("Cancun", html)
        self.assertIn("Confirmed", html)

    def test_locking_twice_keeps_one_history_entry(self):
        self.add("flight-0")
        self.click("🔒 Lock in my trip")
        self.click("Unlock to make changes")
        self.click("🔒 Lock in my trip")  # same trip, same confirmation number
        self.assertEqual(len(self.app.session_state.trip_history), 1)

    def test_user_text_is_escaped_in_the_dashboard(self):
        self.app.text_input(key="trip_city").input("hotels in <b>Tulum</b>").run()
        self.click("Start planning")
        self.add("flight-0")
        self.click("🔒 Lock in my trip")
        self.go_home()
        self.assertIn("&lt;b&gt;Tulum&lt;/b&gt;", self.html())
        self.assertNotIn("<b>Tulum</b>", self.html())


class FreshHomePageTests(unittest.TestCase):
    def test_empty_states_and_no_sample_numbers(self):
        with patch.dict(os.environ, {"SERPAPI_KEY": "", "NESSIE_API_KEY": "", "ANTHROPIC_API_KEY": "",
                                     "PYTHON_DOTENV_DISABLED": "1"}):
            app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.assertEqual(len(app.exception), 0)
        html = "\n".join(element.proto.body for element in app.get("html"))
        for empty in ("No trip budget yet", "No trips yet", "No goals yet", "Coming soon"):
            self.assertIn(empty, html)
        self.assertNotIn("$", html.split("ts-powered")[0].split("<style>")[0])  # no made-up amounts
        self.assertEqual([p.proto.label for p in app.get("page_link")], ["Start a trip"])
        self.assertEqual([t.label for t in app.toggle][:2],
                         ["Sample travel prices (no SerpApi calls)", "Demo bank (no Nessie calls)"])

    def test_the_app_is_called_farewell(self):
        with patch.dict(os.environ, {"SERPAPI_KEY": "", "NESSIE_API_KEY": "", "ANTHROPIC_API_KEY": "",
                                     "PYTHON_DOTENV_DISABLED": "1"}):
            app = AppTest.from_file(str(APP), default_timeout=15).run()
            self.assertIn("Welcome to FareWell", "\n".join(m.value for m in app.markdown))
            app.switch_page("views/plan.py").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "FareWell")
        everything = "\n".join(str(e.value) for kind in ("title", "markdown", "caption", "header")
                               for e in getattr(app, kind))
        self.assertNotIn("Trip Saver", everything)


if __name__ == "__main__":
    unittest.main()
