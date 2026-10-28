-- Customers: one row per bank customer. PIN stored only as a bcrypt hash.
create table customers (
  id              uuid primary key default gen_random_uuid(),
  customer_code   text unique not null,          -- e.g. 'C-1001'
  full_name       text not null,
  pin_hash        text not null,
  failed_pin_attempts int not null default 0,
  is_locked       boolean not null default false,
  created_at      timestamptz not null default now()
);

-- Sessions: one per call; tracks verification state.
create table sessions (
  id              uuid primary key default gen_random_uuid(),
  customer_id     uuid references customers(id),
  token           text unique not null,
  verified        boolean not null default false,
  step_up_verified boolean not null default false,
  last_activity_at timestamptz not null default now(),
  expires_at      timestamptz not null,
  created_at      timestamptz not null default now()
);

-- Accounts: money stored as integer cents, never below zero.
create table accounts (
  id              uuid primary key default gen_random_uuid(),
  customer_id     uuid not null references customers(id),
  account_type    text not null check (account_type in ('chequing', 'savings')),
  last4           char(4) not null,
  balance_cents   bigint not null check (balance_cents >= 0),
  created_at      timestamptz not null default now()
);

-- Cards: freeze is instant; unfreeze is human-only.
create table cards (
  id              uuid primary key default gen_random_uuid(),
  account_id      uuid not null references accounts(id),
  last4           char(4) not null,
  status          text not null default 'active'
                  check (status in ('active', 'frozen')),
  frozen_at       timestamptz
);

-- Transactions: negative amounts are debits.
create table transactions (
  id              uuid primary key default gen_random_uuid(),
  account_id      uuid not null references accounts(id),
  merchant        text not null,
  amount_cents    bigint not null,
  status          text not null default 'posted'
                  check (status in ('pending', 'posted')),
  posted_at       timestamptz not null default now()
);

-- Transfers: own accounts only; idempotency key prevents double moves.
create table transfers (
  id               uuid primary key default gen_random_uuid(),
  from_account_id  uuid not null references accounts(id),
  to_account_id    uuid not null references accounts(id),
  amount_cents     bigint not null check (amount_cents > 0 and amount_cents <= 250000),
  idempotency_key  text unique not null,
  status           text not null default 'completed'
                   check (status in ('completed', 'failed')),
  created_at       timestamptz not null default now(),
  check (from_account_id <> to_account_id)
);

-- Disputes: one per transaction.
create table disputes (
  id              uuid primary key default gen_random_uuid(),
  transaction_id  uuid unique not null references transactions(id),
  reason          text not null,
  status          text not null default 'open'
                  check (status in ('open', 'resolved', 'rejected')),
  created_at      timestamptz not null default now()
);

-- Audit log: append-only record of every action.
create table audit_log (
  id              bigint generated always as identity primary key,
  session_id      uuid references sessions(id),
  actor           text not null,                 -- 'agent', 'customer', 'system'
  action          text not null,                 -- e.g. 'transfer.create'
  outcome         text not null,                 -- 'allowed', 'denied', 'error'
  details         jsonb not null default '{}',
  created_at      timestamptz not null default now()
);