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
        self.assertEqual([p.proto.label for p in self.app.get("page_link")],
                         ["Account", "Paste your group chat → get a trip draft", "Continue planning",
                          "Grow your Trip Fund"])  # "Account" is the top-right user icon

        self.app.switch_page("views/plan.py").run()
        self.click("🔒 Lock in my trip")
        self.go_home()
        html = self.html()
        self.assertIn("1 trip · $1,035.00", html)
        self.assertIn("AUS → CUN", html)
        self.assertIn("Cancún", html)  # the arrival airport's city
        self.assertIn("Confirmed", html)

    def test_locking_twice_keeps_one_history_entry(self):
        self.add("flight-0")
        self.click("🔒 Lock in my trip")
        self.click("Unlock to make changes")
        self.click("🔒 Lock in my trip")  # same trip, same confirmation number
        self.assertEqual(len(self.app.session_state.trip_history), 1)

    def test_relocking_refreshes_history_totals(self):
        self.add("flight-0")
        self.click("🔒 Lock in my trip")
        self.click("Unlock to make changes")
        self.add("hotel-0")
        self.click("🔒 Lock in my trip")
        history = self.app.session_state.trip_history
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["total"], 1035)
        self.assertEqual(history[0]["saved"], 327)
        self.go_home()
        self.assertIn("1 trip · $1,035.00", self.html())

    def test_typed_hotel_area_never_reaches_the_dashboard_as_html(self):
        self.app.text_input(key="trip_area").input("<b>Tulum</b>").run()
        self.click("Start planning")
        self.add("flight-0")
        self.click("🔒 Lock in my trip")
        self.go_home()
        self.assertIn("Cancún", self.html())  # the trip is named for where the flight lands
        self.assertNotIn("<b>Tulum</b>", self.html())


class FreshHomePageTests(unittest.TestCase):
    def test_empty_states_and_no_sample_numbers(self):
        with patch.dict(os.environ, {"SERPAPI_KEY": "", "NESSIE_API_KEY": "", "GEMINI_API_KEY": "",
                                     "PYTHON_DOTENV_DISABLED": "1"}):
            app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.assertEqual(len(app.exception), 0)
        html = "\n".join(element.proto.body for element in app.get("html"))
        for empty in ("No trip budget yet", "No trips yet", "No goals yet"):
            self.assertIn(empty, html)
        self.assertNotIn("$", html.split("ts-powered")[0].split("<style>")[0])  # no made-up amounts
        self.assertEqual([p.proto.label for p in app.get("page_link")],
                         ["Account", "Paste your group chat → get a trip draft", "Start a trip",
                          "Grow your Trip Fund"])  # "Account" is the top-right user icon
        self.assertEqual([t.label for t in app.toggle][:2],
                         ["Sample travel prices (no SerpApi calls)", "Demo bank (no Nessie calls)"])

    def test_the_app_is_called_farewell(self):
        with patch.dict(os.environ, {"SERPAPI_KEY": "", "NESSIE_API_KEY": "", "GEMINI_API_KEY": "",
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
