# ✈️ Trip Saver

Plan a trip with live flight and hotel prices (SerpApi), calculate weekly savings, and
submit contributions to a Trip Fund (Capital One Nessie). Built at HackTX 26.
Transfers are triggered by a button; a background scheduler is not implemented.

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

## Funding contract and limits
- Existing `setup_accounts(demo=False)`, `get_balance(account_id, demo=False)`,
  and `transfer(from_id, to_id, amount, demo=False)` signatures remain unchanged.
- Demo account IDs are opaque and unique per account pair. Always use the IDs returned
  by `setup_accounts`; do not hard-code IDs or read the private `_DEMO` store.
- Transfers require a positive, finite dollar amount with at most two decimal places
  and enough checking funds. Validation raises `ValueError` before submission.
- The website hides transfers when a goal is funded or checking funds are insufficient.
  Each browser session keeps separate demo and Nessie account selections.
- Nessie requests use `https://prod-api.nessieisreal.com` with TLS verification and
  redirects disabled. No fallback sends a credential over HTTP. Service failures raise
  `BankError` with safe text instead of a URL containing the API key.
- A successful live request means submitted, not settled. After a live submission or
  uncertain failure, this prototype pauses further transfers for that wallet/session.
  Verify the transfer in Nessie; status reconciliation is not implemented yet.
- Demo balances live only in server memory and are isolated by account pair. A restart
  loses them; abandoned pairs remain until restart. This is not persistent group banking.
- Live service availability and authenticated account/transfer behavior still need a
  smoke test by the banking owner. Automated tests never use actual API credentials.

## Notes
- Nessie is a sandbox: money is fake, so "automated saving" is simulated.
- "Run this week's transfer" submits one contribution; it does not advance the date.
- Sample prices stay visibly labeled after every rerun. The funding caption separately
  identifies demo balances versus the Nessie sandbox, including when only one key is set.

## Integration handoff
- Person 4's branch includes rounding, deadline checks, transfer safeguards, and the
  end-to-end checks. Integrate this branch once; the earlier Person 4 branches are its ancestors.
- `travel.py` still returns the same normalized dictionaries. Flight prices are round-trip
  USD values; hotel `total` must cover the complete stay. Live hotels missing that total
  are skipped instead of using one night's rate. Demo totals equal nightly rate times nights.
- Search dates must be valid and return after departure. Changing the search inputs or
  demo mode blocks old prices and funding until a new search completes.
- Offline tests cover price normalization, travel-to-budget-to-bank flow, same-day and
  future savings, insufficient funds, fully funded goals, safe error handling, pending live
  submissions, and mode switching. No automated test calls either external API.
- Default demo: $412 flight + $89 x 7 nights + $200 extras = **$1,235**. With a deadline
  four weeks away, the first contribution is **$308.75**. With a deadline today, it is
  **$1,235** and the fund becomes fully funded after one contribution.
- Live verification is still outstanding: configure keys privately, confirm current Nessie
  account/transfer responses, and verify authenticated SerpApi prices. A credential-free
  Nessie HTTPS probe on 2026-10-24 returned a service error; this branch does not claim live
  service availability. See [Nessie](https://nessieisreal.com/docs) and
  [SerpApi hotel totals](https://serpapi.com/google-hotels-api).
- Teammates' unpublished work cannot be checked here. Re-run the suite after their branches
  are integrated. Persistent group plans, voting, authentication, a scheduler, and Gemini
  are outside this prototype's current implementation.

## Devpost checklist
- [ ] What it does / how we built it / challenges / what's next
- [ ] Demo link + 1-minute video
- [ ] Tracks: SerpApi, Capital One (+ Best Overall / Novice)
