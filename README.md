# ✈️ Trip Saver

Plan a trip with live flight and hotel prices (SerpApi), then let a Trip Fund save for it
automatically with weekly transfers (Capital One Nessie). Built at HackTX 26.

## Run it
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add your SERPAPI_KEY and NESSIE_API_KEY
streamlit run app.py
```
With no keys set, the app runs in **demo mode** using cached data in `demo_data/`.

## Check the planner and website
After installing `requirements.txt`, run the calculation and Streamlit flow tests:
```bash
python -m unittest discover -s tests -v
```
No API keys are needed. Website tests use cached travel results and simulated money,
and reject external HTTP requests. To run just the standard-library calculation tests:
```bash
python -m unittest discover -s tests -p test_planner.py -v
```

## Savings deadline contract
- Existing planner function names, arguments, and dollar-valued float results are preserved.
- `weeks_until()` and `weekly_amount()` raise `ValueError` for a missing or expired deadline.
- `validate_deadline(deadline, today=None, departure=None)` also checks the departure bound
  when supplied. The website catches its messages before showing funding controls.
- Saving by today is valid: the full remaining amount is due today. A deadline on the
  departure date is also allowed; a later deadline is rejected.
- Demo weekly scheduling remains simulated with the existing transfer button.

## Who owns what
| File | Job |
|---|---|
| `app.py` | Streamlit UI |
| `travel.py` | SerpApi flights + hotels |
| `bank.py` | Nessie accounts + transfers |
| `planner.py` | Savings-plan math |

## Notes
- Nessie is a sandbox: money is fake, so "automated saving" is simulated.
- "Run this week's transfer" stands in for a weekly scheduler in the demo.

## Devpost checklist
- [ ] What it does / how we built it / challenges / what's next
- [ ] Demo link + 1-minute video
- [ ] Tracks: SerpApi, Capital One (+ Best Overall / Novice)
