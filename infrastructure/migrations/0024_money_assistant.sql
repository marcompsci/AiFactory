-- V6.158–V6.187: money, round 3. Typed in by you; nothing is connected to a bank and nothing moves money.
create table payment_notes (
  bill_id uuid not null references my_bills(id) on delete cascade,
  period text not null check (char_length(period) between 4 and 7),
  organization_id uuid not null references organizations(id) on delete cascade,
  confirmation text not null default '' check (char_length(confirmation) <= 60),
  method text not null default '' check (char_length(method) <= 40),
  primary key (bill_id, period)
);
create index payment_notes_org on payment_notes (organization_id);

create table credit_disputes (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  bureau text not null check (bureau in ('equifax','experian','transunion','other')),
  item text not null check (char_length(item) between 1 and 120),
  sent_on date not null,
  status text not null default 'open' check (status in ('open','fixed','denied')),
  note text not null default '' check (char_length(note) <= 300),
  closed_on date
);
create index credit_disputes_org on credit_disputes (organization_id);

create table card_history (
  id uuid primary key,
  card_id uuid not null references credit_cards(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  balance_cents integer not null check (balance_cents between 0 and 100000000),
  limit_cents integer not null check (limit_cents between 1 and 100000000),
  day date not null
);
create index card_history_card on card_history (card_id, day);

create table card_bills (
  card_id uuid primary key references credit_cards(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  bill_id uuid not null references my_bills(id) on delete cascade
);

create table money_targets (
  organization_id uuid primary key references organizations(id) on delete cascade,
  monthly_income_cents integer check (monthly_income_cents is null or monthly_income_cents between 1 and 100000000)
);

create table money_wins (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  title text not null check (char_length(title) between 1 and 80),
  amount_cents integer not null check (amount_cents between 1 and 100000000),
  monthly integer not null default 0 check (monthly in (0, 1)),
  day date not null
);
create index money_wins_org on money_wins (organization_id);

create table sell_items (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 80),
  asking_cents integer check (asking_cents is null or asking_cents between 0 and 100000000),
  sold_cents integer check (sold_cents is null or sold_cents between 0 and 100000000),
  where_listed text not null default '' check (char_length(where_listed) <= 60),
  listed_on date not null,
  sold_on date
);
create index sell_items_org on sell_items (organization_id);

create table owed_to_me (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  who text not null check (char_length(who) between 1 and 40),
  amount_cents integer not null check (amount_cents between 1 and 100000000),
  why text not null default '' check (char_length(why) <= 120),
  expected_on date,
  received_on date,
  created_at timestamptz not null default now()
);
create index owed_to_me_org on owed_to_me (organization_id);

create table no_spend_days (
  organization_id uuid not null references organizations(id) on delete cascade,
  day date not null,
  primary key (organization_id, day)
);
