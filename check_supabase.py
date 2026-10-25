"""Check the Supabase connection used for accounts, and say exactly what's wrong.

Run from the project folder (reads SUPABASE_URL and SUPABASE_SERVICE_KEY from .env or the
environment):
    .venv\\Scripts\\python.exe check_supabase.py

It reads the farewell_users table, then writes and deletes one test row. It never prints the key.
"""
import os
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

import accounts

load_dotenv()
url = os.getenv("SUPABASE_URL", "").strip()
key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()


def explain(reply) -> str:
    try:
        body = reply.json()
    except ValueError:
        return f"HTTP {reply.status_code}: {reply.text[:200]!r}"
    if isinstance(body, dict):
        parts = [str(body.get(k)) for k in ("code", "message", "hint", "details") if body.get(k)]
        return f"HTTP {reply.status_code}: " + " | ".join(parts)
    return f"HTTP {reply.status_code}"


print("SUPABASE_URL:", url or "(missing)")
host = urlparse(url).hostname or ""
if not url:
    raise SystemExit("Add SUPABASE_URL to .env (the Project URL, like https://abcd.supabase.co).")
if not host.endswith(".supabase.co") or urlparse(url).path.strip("/"):
    print("  ! This doesn't look like a Project URL. It should be exactly https://<project-ref>.supabase.co "
          "(not the dashboard address, and nothing after .co).")
if not key:
    raise SystemExit("Add SUPABASE_SERVICE_KEY to .env (the secret / service_role key).")
kind = ("new secret key" if key.startswith("sb_secret_") else
        "PUBLISHABLE key: wrong one, use the secret key" if key.startswith("sb_publishable_") else
        "legacy JWT key (check it's service_role, not anon)" if key.startswith("eyJ") else "unrecognised format")
print(f"SUPABASE_SERVICE_KEY: {len(key)} characters, {kind}")

store = accounts.SupabaseStore(url, key)
probe = "diagnostic:check_supabase"
try:
    read = requests.get(store.endpoint, headers=store.headers, params={"select": "user_id", "limit": "1"},
                        timeout=10, allow_redirects=False)
    print("1. Read the table:  ", "OK" if read.ok else explain(read))
    write = requests.post(store.endpoint, headers={**store.headers, "Prefer": "return=minimal,resolution=merge-duplicates"},
                          json={"user_id": probe, "email": "", "data": {}, "password_hash": None},
                          timeout=10, allow_redirects=False)
    print("2. Write a test row:", "OK" if write.ok else explain(write))
    if write.ok:
        gone = requests.delete(store.endpoint, headers=store.headers, params={"user_id": f"eq.{probe}"},
                               timeout=10, allow_redirects=False)
        print("3. Delete it again: ", "OK" if gone.ok else explain(gone))
except requests.RequestException as error:
    print("Couldn't reach that address at all:", type(error).__name__,
          "- check SUPABASE_URL (and that the Supabase project isn't paused).")
