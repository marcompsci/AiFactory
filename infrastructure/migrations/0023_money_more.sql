-- V6.128–V6.157: money, round 2. All typed in by you; nothing is connected to a bank and nothing moves money.
create table expenses (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  amount_cents integer not null check (amount_cents between 1 and 100000000),
  category text not null check (char_length(category) between 1 and 40),
  day date not null,
  note text not null default '' check (char_length(note) <= 300),
  created_by uuid not null,
  created_at timestamptz not null default now()
);
create index expenses_org on expenses (organization_id, day);

create table category_budgets (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  category text not null check (char_length(category) between 1 and 40),
  limit_cents integer not null check (limit_cents between 1 and 100000000),
  constraint category_budgets_once unique (organization_id, category)
);

create table cash_accounts (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 60),
  kind text not null default 'checking' check (kind in ('checking','savings','cash')),
  created_at timestamptz not null default now()
);
create index cash_accounts_org on cash_accounts (organization_id);

create table cash_balances (
  id uuid primary key,
  account_id uuid not null references cash_accounts(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  balance_cents integer not null check (balance_cents between -100000000 and 100000000),
  day date not null,
  created_at timestamptz not null default now()
);
create index cash_balances_account on cash_balances (account_id, day);

create table debts (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 60),
  kind text not null default 'card' check (kind in ('card','loan','other')),
  balance_cents integer not null check (balance_cents between 0 and 100000000),
  apr double precision not null default 0 check (apr >= 0 and apr <= 100),
  min_payment_cents integer not null check (min_payment_cents between 0 and 100000000),
  card_id uuid references credit_cards(id) on delete set null,
  updated_at timestamptz not null default now()
);
create index debts_org on debts (organization_id);

create table bill_extras (
  bill_id uuid primary key references my_bills(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  autopay_account_id uuid references cash_accounts(id) on delete set null,
  late_fee_cents integer check (late_fee_cents is null or late_fee_cents between 0 and 100000000),
  grace_days integer check (grace_days is null or grace_days between 0 and 60)
);

create table money_settings (
  organization_id uuid primary key references organizations(id) on delete cascade,
  mileage_rate_cents integer check (mileage_rate_cents is null or mileage_rate_cents between 0 and 1000),
  tax_pct double precision check (tax_pct is null or (tax_pct >= 0 and tax_pct <= 60)),
  emergency_goal_id uuid references savings_goals(id) on delete set null,
  gig_sources text not null default '' check (char_length(gig_sources) <= 1300)
);

create table gig_costs (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  source text not null check (char_length(source) between 1 and 60),
  day date not null,
  amount_cents integer not null default 0 check (amount_cents between 0 and 100000000),
  miles double precision not null default 0 check (miles >= 0 and miles <= 2000),
  note text not null default '' check (char_length(note) <= 300),
  created_at timestamptz not null default now()
);
create index gig_costs_org on gig_costs (organization_id, day);

create table money_checks (
  organization_id uuid not null references organizations(id) on delete cascade,
  key text not null check (char_length(key) between 1 and 40),
  done_at timestamptz not null,
  primary key (organization_id, key)
);

create table cashback_entries (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  card text not null check (char_length(card) between 1 and 60),
  amount_cents integer not null check (amount_cents between 1 and 100000000),
  day date not null,
  created_at timestamptz not null default now()
);
create index cashback_entries_org on cashback_entries (organization_id, day);

create table assets (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 60),
  value_cents integer not null check (value_cents between 0 and 100000000),
  updated_at timestamptz not null default now()
);

create table net_worth_snapshots (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  day date not null,
  assets_cents bigint not null,
  debts_cents bigint not null,
  constraint net_worth_once_a_day unique (organization_id, day)
);

create table bill_splits (
  id uuid primary key,
  bill_id uuid not null references my_bills(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  person text not null check (char_length(person) between 1 and 40),
  share_cents integer not null check (share_cents between 1 and 100000000)
);
create index bill_splits_bill on bill_splits (bill_id);

create table split_receipts (
  split_id uuid not null references bill_splits(id) on delete cascade,
  period text not null check (char_length(period) between 4 and 7),
  organization_id uuid not null references organizations(id) on delete cascade,
  received_at timestamptz not null,
  primary key (split_id, period)
);
