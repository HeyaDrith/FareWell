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

## Check the savings calculations
```bash
python -m unittest discover -s tests -v
```
These checks use only Python's standard library; no API keys or network access are needed.

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
