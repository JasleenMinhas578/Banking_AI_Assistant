-- Step-up verification (POL-004): transfers over $1,000 need a one-time code
-- on top of the PIN. Like the PIN, only a bcrypt hash of the code is stored.
alter table sessions
  add column otp_hash       text,
  add column otp_expires_at timestamptz,
  add column otp_attempts   int not null default 0;

-- The daily-limit check sums today's transfers out of a customer's accounts.
create index transfers_from_account_created_idx on transfers (from_account_id, created_at);
