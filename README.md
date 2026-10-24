# ✈️ Trip Saver

Type a budget and destination, pick the flights, hotels, food and activities that fit, and
see how much you save. Prices come from SerpApi; every pick is tracked in Capital One's
Nessie sandbox. Built at HackTX 26.

## How it works
1. Enter a **budget**, airports, dates and a hotel search, then click **Start planning**.
2. Flights and hotels show the **typical price** (median of the results), whether each option
   **fits** what's left of the budget, and how much it **saves** vs. typical.
3. Each pick becomes a Nessie **purchase** on a "Trip Budget" account. Money saved vs. typical
   is a Nessie **deposit** into a "Trip Savings" account. Food and activities are added by hand.
4. The page shows Budget / Spent / Remaining / Saved and the **final trip cost**. ✕ removes a pick.

## Run it
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add your SERPAPI_KEY and NESSIE_API_KEY
streamlit run app.py
```
With no keys set, the app runs in **demo mode** using cached data in `demo_data/`.
On Windows PowerShell, use:
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```
Keys are optional for the demo. For live integrations, store them only in a local
`.env` or Streamlit's secret settings. `.env.example` contains empty placeholders.
Never commit filled environment files or `secrets.toml`.

## Gemini: turn the group chat into a trip
This optional feature sits above the existing trip form. It extracts an editable draft
from pasted text, a PNG/JPEG screenshot, or both. Airports, dates, hotel city, traveler
count, budget scope/currency, and preferences are reviewed before use. Missing details
and disagreements are shown instead of silently treating them as group agreement.

To try it without credentials:
1. Install the updated requirements (works on Python 3.10 through 3.12).
2. Open **Turn our group chat into a trip**.
3. Select **Load example draft (no API)**. This is a fixed example, not AI analysis.
4. Edit the draft, check the review confirmation, and select **Apply reviewed draft**.
5. Select **Start planning** in the normal trip form, then pick your options.

For Gemini itself, configure `GEMINI_API_KEY` privately in `.env` or Streamlit secrets,
restart the app, turn off **Demo AI drafts** in the sidebar, and select **Create trip draft** after pasting
text or uploading a screenshot. `GEMINI_MODEL` is an optional override; the default is
`gemini-3.5-flash-lite`, a model with image and structured-output support documented by
[Google](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite).
The Gemini key is independent of the SerpApi/Nessie keys. If those are absent, their
existing demo fallbacks still apply and remain labeled.

- A draft never automatically searches, books, creates an account, or transfers money.
  Applying it fills the reviewed search fields. A per-person USD budget also fills the
  **Total trip budget** field; a group budget stays a planning note.
- Changed source text or a replaced screenshot invalidates the old editable draft.
- Per-person USD budget limits are compared with the one-traveler trip cost so far.
  Group size, group budgets, and interests remain planning notes: the current search
  quotes one traveler and one room. It does not yet price shared accommodation, generate
  a verified itinerary, search activities/restaurants, or coordinate votes.
- Submitted text and image pixels go to Google only after **Create trip draft** is clicked.
  Remove private content first; model instructions cannot guarantee redaction. Images are
  checked for actual PNG/JPEG format, limited to 4 MB / 12 million pixels, resized to at
  most 2000 pixels per side, and stripped of metadata in memory. This app never saves
  uploads to disk or logs prompts/replies. Google's handling of submissions is separate.
- Input is capped at 12,000 characters. Requests have a 25-second timeout and one attempt,
  with no tools, fixed HTTPS transport, and no redirects. Failures leave the manual flow usable.
- **Clear chat and draft** removes the input widgets and editable draft from the session.
  Already-confirmed trip fields and planning notes remain until replaced or the session ends.
- Tests use mocked Gemini responses and an offline SDK transport. A real authenticated
  Gemini request and model extraction accuracy still need a smoke test with a configured key.

`trip_draft.py` owns extraction, validation, and the offline example. `draft_ui.py` owns
review and confirmation. Existing `travel.py`, `planner.py`, and `bank.py` APIs are unchanged.

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

## Trip budget tracker (Nessie)
- `create_trip(budget, demo=False)` returns a trip dict (keep it in `st.session_state`);
  `record_pick(trip, category, description, amount, saved=0)`, `remove_pick(trip, pick_id)`,
  `list_picks(trip)` and `get_summary(trip)` use it. Categories: Flight, Hotel, Food, Activity, Other.
- Live sandbox behavior, verified with a real key on 2026-10-24: purchases and deposits need
  `"status"`, amounts are whole dollars only, balances never update, purchases can't be deleted.
  So costs round **up** to the dollar, savings round **down**, totals are computed from the
  records, and removed picks are remembered in the trip dict instead of deleted.
- Demo trips never reach Nessie; invalid amounts raise `ValueError`; service failures raise
  `BankError` with safe text (no URL or key).
- The weekly Trip Fund functions (`setup_accounts`, `get_balance`, `transfer`) and the deadline
  helpers in `planner.py` are unchanged and still tested, ready for a later "save for it" step.

## Who owns what
| File | Job |
|---|---|
| `app.py` | Streamlit UI |
| `travel.py` | SerpApi flights + hotels |
| `bank.py` | Nessie trip budget tracker (+ Trip Fund transfers, not used by the UI) |
| `planner.py` | Typical price / savings math (+ weekly savings math) |

## Trip Fund transfer contract (kept in `bank.py`, not shown in the UI yet)
- Existing `setup_accounts(demo=False)`, `get_balance(account_id, demo=False)`,
  and `transfer(from_id, to_id, amount, demo=False)` signatures remain unchanged.
- Demo account IDs are opaque and unique per account pair. Always use the IDs returned
  by `setup_accounts`; do not hard-code IDs or read the private `_DEMO` store.
- Transfers require a positive, finite dollar amount with at most two decimal places
  and enough checking funds. Validation raises `ValueError` before submission.
- Nessie requests use `https://prod-api.nessieisreal.com` with TLS verification and
  redirects disabled. No fallback sends a credential over HTTP. Service failures raise
  `BankError` with safe text instead of a URL containing the API key.
- The live transfer adapter uses whole-dollar amounts and records a completed withdrawal plus
  a deposit (two requests), deriving balances from those records. Verify both records before
  retrying after an uncertain failure.
- Demo balances live only in server memory and are isolated by account pair. A restart
  loses them; abandoned pairs remain until restart. This is not persistent group banking.
- Live service availability and authenticated account/transfer behavior still need a
  smoke test by the banking owner. Automated tests never use actual API credentials.

## Notes
- Nessie is a sandbox: money is fake and nothing is booked. Picks are a spending plan.
- Sample prices stay visibly labeled after every rerun. The budget caption separately
  identifies demo money versus the Nessie sandbox. The sidebar has separate switches for
  sample prices and the demo bank, so either key works on its own.
- Changing the budget, trip details or a sidebar switch blocks the old results until
  **Start planning** runs again (which starts a fresh trip).

## Integration handoff
- Person 4's branch includes rounding, deadline checks, transfer safeguards, and the
  end-to-end checks. Integrate this branch once; the earlier Person 4 branches are its ancestors.
- `travel.py` still returns the same normalized dictionaries. Flight prices are round-trip
  USD values; hotel `total` must cover the complete stay. Live hotels missing that total
  are skipped instead of using one night's rate. Demo totals equal nightly rate times nights.
- Search dates must be valid and return after departure.
- Offline tests cover price normalization, the budget -> picks -> savings -> final cost flow,
  whole-dollar rounding, over-budget warnings, safe error handling, `$` escaping, mocked live
  Nessie payloads, demo/live isolation, and the Trip Fund transfer contract. No automated test
  calls either external API.
- Default demo ($1,500 budget): Southwest $412 (typical $438, saves $26) + Seaside Budget Inn
  $89 x 7 = $623 (typical $924, saves $301) = **$1,035 spent, $327 saved, $465 left**.
- Live Nessie: the trip budget tracker passed a 9/9 smoke test with a real key on 2026-10-24
  (create trip, picks, savings deposits, totals, removal). SerpApi live prices still need a
  check with a real key. See [Nessie](https://nessieisreal.com/docs) and
  [SerpApi hotel totals](https://serpapi.com/google-hotels-api).
- Teammates' unpublished work cannot be checked here. Re-run the suite after their branches
  are integrated. Persistent group plans, voting, authentication, a scheduler, and full
  group pricing are outside this prototype's current implementation.

## Devpost checklist
- [ ] What it does / how we built it / challenges / what's next
- [ ] Demo link + 1-minute video
- [ ] Tracks: SerpApi, Capital One (+ Best Overall / Novice)
