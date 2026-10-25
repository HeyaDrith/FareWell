-- FareWell accounts: run once in Supabase > SQL Editor (safe to run again).
-- One row per account: email + password accounts ("email:you@example.com") and, if Google
-- sign-in is set up, Google accounts. data holds their locked trips and Trip Funds as JSON.
create table if not exists public.farewell_users (
  user_id       text primary key,
  email         text not null default '',
  data          jsonb not null default '{}'::jsonb,
  updated_at    timestamptz not null default now(),
  password_hash text            -- salted scrypt hash for email accounts; never the password
);
alter table public.farewell_users add column if not exists password_hash text;

-- Row-level security on with no policies: browsers and the public anon key can't read or
-- write this table. Only the app's server, using the secret (service role) key, can.
alter table public.farewell_users enable row level security;
