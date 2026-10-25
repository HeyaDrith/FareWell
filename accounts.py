"""Optional accounts and per-user saving: locked trips (Travel History) and Trip Funds.

People create an account with an email and password on the Account page. Passwords are stored
only as salted scrypt hashes; repeated wrong passwords are slowed down. Signing in lasts while
the browser tab is open. Google sign-in (Streamlit's built-in login) is offered too when an
[auth] block is in secrets. Without an account the app works as before, keeping everything in
the browser session.

Saved data lives in Supabase when SUPABASE_URL and SUPABASE_SERVICE_KEY are set (one row per
user in the farewell_users table, see supabase_setup.sql), otherwise in a local SQLite file for
development. The service key stays on the server; the table has row-level security on and no
policies, so nothing else can read it.

sync() runs at the start of every page. It loads a user's saved data once per session, merges in
anything they did before signing in, and saves again whenever their data changes. If loading
fails it never saves, so a hiccup can't overwrite someone's saved trips with an empty session.
"""
import base64
from contextlib import closing
from datetime import date, datetime, timezone
import hashlib
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from threading import RLock
import time

import requests
import streamlit as st

import bank

LOCAL_DB = Path(__file__).parent / ".farewell_accounts.db"
TABLE = "farewell_users"
VERSION = 1
_LOCAL_LOCK = RLock()


class StorageError(RuntimeError):
    """Saved data couldn't be loaded or saved (the message is safe to show)."""


# ---------- Who is signed in ----------

def auth_configured() -> bool:
    """True when secrets have an [auth] block, so the Sign in button can work."""
    try:
        return "auth" in st.secrets
    except Exception:  # no secrets file at all
        return False


SESSION_KEY = "account_signed_in"  # {"id", "email", "name"} after an email + password sign-in


def current_user() -> dict | None:
    """{"id", "email", "name", "via"} for a signed-in visitor, else None."""
    signed = st.session_state.get(SESSION_KEY)
    if isinstance(signed, dict) and signed.get("id"):
        return {**signed, "via": "email"}
    try:
        user = st.user
        if not user.get("is_logged_in"):
            return None
        ident, email = user.get("sub") or user.get("email"), user.get("email")
        name = user.get("given_name") or user.get("name") or email
    except Exception:
        return None
    if not ident:
        return None
    return {"id": str(ident), "email": str(email or ""), "name": str(name or "Traveler"), "via": "google"}


# ---------- Email + password accounts ----------

MIN_PASSWORD, MAX_PASSWORD = 8, 128
MAX_FAILURES, LOCKOUT_SECONDS = 5, 300
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}  # about 0.2 s per check: slow for guessing, fine for people
_failures: dict[str, list[float]] = {}  # email -> recent failed sign-in times (this server)
_FAIL_LOCK = RLock()


class AccountError(ValueError):
    """A sign-in or registration problem the person can fix (safe to show)."""


def _clean_email(email: str) -> str:
    email = str(email or "").strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise AccountError("Enter a valid email address.")
    return email


def hash_password(password: str) -> str:
    """A salted scrypt hash, stored instead of the password ("scrypt$n$r$p$salt$hash")."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return "$".join(["scrypt", str(_SCRYPT["n"]), str(_SCRYPT["r"]), str(_SCRYPT["p"]),
                     base64.b64encode(salt).decode(), base64.b64encode(digest).decode()])


def check_password(password: str, stored: str | None) -> bool:
    try:
        kind, n, r, p, salt, digest = str(stored).split("$")
        if kind != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                                dklen=32)
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def _user_id(email: str) -> str:
    return f"email:{email}"


def _signed_in(email: str) -> dict:
    return {"id": _user_id(email), "email": email, "name": email.split("@")[0]}


def register(email: str, password: str, confirm: str, backend=None) -> dict:
    """Create an account, then return the signed-in user (put it in st.session_state[SESSION_KEY])."""
    email = _clean_email(email)
    if not MIN_PASSWORD <= len(password or "") <= MAX_PASSWORD:
        raise AccountError(f"Use a password with {MIN_PASSWORD} to {MAX_PASSWORD} characters.")
    if password != confirm:
        raise AccountError("The two passwords don't match.")
    if not (backend or store()).create_user(_user_id(email), email, hash_password(password)):
        raise AccountError("An account with this email already exists. Sign in instead.")
    return _signed_in(email)


def sign_in(email: str, password: str, backend=None) -> dict:
    """Check an email and password, then return the signed-in user. Wrong details get one message
    whichever part was wrong, and 5 failures in 5 minutes pause that email for 5 minutes."""
    wrong = AccountError("That email and password don't match an account.")
    try:
        email = _clean_email(email)
    except AccountError:
        raise wrong from None
    now = time.time()
    with _FAIL_LOCK:
        recent = [t for t in _failures.get(email, []) if now - t < LOCKOUT_SECONDS]
        _failures[email] = recent
        if len(recent) >= MAX_FAILURES:
            raise AccountError("Too many tries. Wait a few minutes, then try again.")
    if not check_password(password or "", (backend or store()).password_hash(_user_id(email))):
        with _FAIL_LOCK:
            _failures.setdefault(email, []).append(now)
        raise wrong
    with _FAIL_LOCK:
        _failures.pop(email, None)
    return _signed_in(email)


# ---------- Where it's saved ----------

class LocalStore:
    """A SQLite file next to the app: for development, and as a fallback without Supabase."""
    label = "this server"

    def __init__(self, path: Path = LOCAL_DB):
        self.path = path

    def _run(self, sql: str, args: tuple):
        """One statement in its own connection, committed and closed (an open file stays locked)."""
        with _LOCAL_LOCK, closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute(f"create table if not exists {TABLE} (user_id text primary key, email text, "
                       "data text not null, updated_at text not null, password_hash text)")
            columns = {row[1] for row in db.execute(f"pragma table_info({TABLE})")}
            if "password_hash" not in columns:  # a file made before email accounts existed
                db.execute(f"alter table {TABLE} add column password_hash text")
            return db.execute(sql, args).fetchone()

    def create_user(self, user_id: str, email: str, password_hash: str) -> bool:
        """False when that account already exists."""
        try:
            self._run(f"insert into {TABLE} (user_id, email, data, updated_at, password_hash) "
                      "values (?, ?, '{}', ?, ?)", (user_id, email, _now(), password_hash))
            return True
        except sqlite3.IntegrityError:
            return False
        except sqlite3.Error:
            raise StorageError("Accounts are unavailable right now. Try again in a moment.") from None

    def password_hash(self, user_id: str) -> str | None:
        try:
            row = self._run(f"select password_hash from {TABLE} where user_id = ?", (user_id,))
        except sqlite3.Error:
            raise StorageError("Accounts are unavailable right now. Try again in a moment.") from None
        return row[0] if row else None

    def load(self, user_id: str) -> dict | None:
        try:
            row = self._run(f"select data from {TABLE} where user_id = ?", (user_id,))
            return json.loads(row[0]) if row else None
        except (sqlite3.Error, ValueError):
            raise StorageError("Your saved trips couldn't be loaded right now.") from None

    def save(self, user_id: str, email: str, data: dict) -> None:
        try:
            self._run(f"insert into {TABLE} (user_id, email, data, updated_at) values (?, ?, ?, ?) "
                      "on conflict(user_id) do update set email = excluded.email, data = excluded.data, "
                      "updated_at = excluded.updated_at", (user_id, email, json.dumps(data), _now()))
        except sqlite3.Error:
            raise StorageError("Your latest changes couldn't be saved right now.") from None


class SupabaseStore:
    """Supabase's REST API (PostgREST), called with the server-side service key."""
    label = "your account"

    def __init__(self, url: str, key: str):
        self.endpoint = url.rstrip("/") + f"/rest/v1/{TABLE}"
        self.headers = {"apikey": key, "Content-Type": "application/json"}
        if key.startswith("eyJ"):  # legacy JWT keys also go in Authorization; new sb_secret_ keys must not
            self.headers["Authorization"] = f"Bearer {key}"

    def _call(self, method: str, allow: tuple = (), **kwargs):
        try:
            reply = requests.request(method, self.endpoint, headers={**self.headers, **kwargs.pop("headers", {})},
                                     timeout=8, allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise StorageError("Your saved trips couldn't be reached right now.") from None
        if not 200 <= reply.status_code < 300 and reply.status_code not in allow:
            raise StorageError("Your saved trips couldn't be reached right now.")
        return reply

    def _rows(self, reply) -> list:
        try:
            rows = reply.json()
        except ValueError:
            raise StorageError("Your saved trips couldn't be read.") from None
        if not isinstance(rows, list):
            raise StorageError("Your saved trips couldn't be read.")
        return rows

    def create_user(self, user_id: str, email: str, password_hash: str) -> bool:
        """False when that account already exists (409: the primary key is taken)."""
        reply = self._call("POST", allow=(409,), headers={"Prefer": "return=minimal"},
                           json={"user_id": user_id, "email": email, "data": {}, "updated_at": _now(),
                                 "password_hash": password_hash})
        return reply.status_code != 409

    def password_hash(self, user_id: str) -> str | None:
        rows = self._rows(self._call("GET", params={"user_id": f"eq.{user_id}", "select": "password_hash"}))
        return rows[0].get("password_hash") if rows and isinstance(rows[0], dict) else None

    def load(self, user_id: str) -> dict | None:
        rows = self._rows(self._call("GET", params={"user_id": f"eq.{user_id}", "select": "data"}))
        return rows[0].get("data") if rows and isinstance(rows[0], dict) else None

    def save(self, user_id: str, email: str, data: dict) -> None:
        self._call("POST", params={"on_conflict": "user_id"},
                   headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                   json={"user_id": user_id, "email": email, "data": data, "updated_at": _now()})


def store():
    url, key = os.getenv("SUPABASE_URL", "").strip(), os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    return SupabaseStore(url, key) if url.startswith("https://") and key else LocalStore()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- What's saved ----------

_FUND_DATES = ("deadline", "next_due")


def _fund_out(fund: dict) -> dict:
    """A Trip Fund as JSON: dates as text, plus the demo money balances so they survive restarts."""
    out = {k: v for k, v in fund.items() if k not in ("history", "pending")}
    for key in _FUND_DATES:
        out[key] = fund[key].isoformat()
    out["history"] = [{**row, "Date": row["Date"].isoformat()} for row in fund.get("history", [])]
    pending = fund.get("pending")
    out["pending"] = ({**pending, "row": {**pending["row"], "Date": pending["row"]["Date"].isoformat()}}
                      if pending else None)
    if fund.get("demo"):
        out["demo_balances"] = bank.demo_balances(fund["checking_id"])
    return out


def _fund_in(saved: dict) -> dict:
    """The reverse of _fund_out; demo accounts that a server restart forgot are put back."""
    fund = {k: v for k, v in saved.items() if k != "demo_balances"}
    for key in _FUND_DATES:
        fund[key] = date.fromisoformat(saved[key])
    fund["target"] = int(saved["target"])
    fund["history"] = [{**row, "Date": date.fromisoformat(row["Date"])} for row in saved.get("history", [])]
    pending = saved.get("pending")
    fund["pending"] = ({**pending, "row": {**pending["row"], "Date": date.fromisoformat(pending["row"]["Date"])}}
                       if pending else None)
    balances = saved.get("demo_balances")
    if fund.get("demo") and balances:
        bank.restore_demo_accounts(fund["checking_id"], fund["fund_id"], balances["checking"], balances["fund"])
    return fund


def _history_in(rows) -> list[dict]:
    """Locked trips from storage, keeping only well-formed entries."""
    keep = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and isinstance(row.get("confirmation"), str):
            keep.append({"confirmation": row["confirmation"], "route": str(row.get("route", "")),
                         "place": str(row.get("place", "")), "dates": str(row.get("dates", "")),
                         "total": float(row.get("total") or 0), "saved": float(row.get("saved") or 0)})
    return keep


def snapshot(ss) -> dict:
    """What gets saved for a signed-in user."""
    return {"version": VERSION, "trip_history": list(ss.get("trip_history", [])),
            "funds": {mode: _fund_out(fund) for mode, fund in ss.get("weekly_funds", {}).items()}}


def _digest(data: dict) -> str:
    return sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def restore(ss, saved: dict | None) -> None:
    """Merge a user's saved data into this session. Trips locked before signing in are kept too;
    for each Trip Fund mode the saved fund wins over one started before signing in."""
    saved = saved if isinstance(saved, dict) else {}
    session_trips = list(ss.get("trip_history", []))
    seen = {t.get("confirmation") for t in session_trips}
    ss["trip_history"] = session_trips + [t for t in _history_in(saved.get("trip_history"))
                                          if t["confirmation"] not in seen]
    funds = ss.setdefault("weekly_funds", {})
    for mode, raw in (saved.get("funds") or {}).items():
        if mode not in ("demo", "nessie") or not isinstance(raw, dict):
            continue
        try:
            funds[mode] = _fund_in(raw)
        except (KeyError, TypeError, ValueError):
            continue  # a damaged fund is skipped, never fatal
        # Goal fields from before signing in would read as an unsaved change; show the saved goal.
        ss.pop(f"fund_target_{mode}", None)
        ss.pop(f"fund_deadline_{mode}", None)


def sign_out(ss) -> None:
    """End an email sign-in; the next sync() then clears that user's trips and funds from the page."""
    ss.pop(SESSION_KEY, None)


def _forget(ss) -> None:
    """After signing out, don't leave the previous user's saved trips and funds on screen."""
    for key in ("trip_history", "weekly_funds", "account_user", "account_digest", "account_error"):
        ss.pop(key, None)
    for mode in ("demo", "nessie"):
        ss.pop(f"fund_target_{mode}", None)
        ss.pop(f"fund_deadline_{mode}", None)


def sync(ss) -> None:
    """Load once per session after sign-in, then save whenever the user's data changes."""
    user = current_user()
    if not user:
        if ss.get("account_user"):
            _forget(ss)
        return
    backend = store()
    if ss.get("account_user") != user["id"]:
        try:
            saved = backend.load(user["id"])
        except StorageError as error:
            ss["account_error"] = str(error)  # try again next run; never save over unloaded data
            return
        if ss.get("account_user"):  # a different person signed in on this browser
            _forget(ss)
        restore(ss, saved)
        ss["account_user"], ss["account_digest"] = user["id"], _digest(saved) if saved else None
        ss.pop("account_error", None)
    data = snapshot(ss)
    digest = _digest(data)
    if digest == ss.get("account_digest"):
        return
    try:
        backend.save(user["id"], user["email"], data)
    except StorageError as error:
        ss["account_error"] = str(error)
        return
    ss["account_digest"] = digest
    ss.pop("account_error", None)
