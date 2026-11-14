-- V6.113–V6.127: income you log, pay schedules, savings goals, subscriptions and credit cards. All typed in by you;
-- nothing is connected to a bank and nothing moves money.
create table income_entries (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  amount_cents integer not null check (amount_cents between 1 and 100000000),
  source text not null check (char_length(source) between 1 and 60),
  day date not null,
  hours double precision check (hours is null or (hours > 0 and hours <= 24)),
  note text not null default '' check (char_length(note) <= 300),
  created_by uuid not null,
  created_at timestamptz not null default now()
);
create index income_entries_org on income_entries (organization_id, day);

create table pay_schedules (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 60),
  cadence text not null check (cadence in ('weekly','biweekly','semimonthly','monthly')),
  anchor_day date not null,
  amount_cents integer check (amount_cents is null or amount_cents between 0 and 100000000),
  created_at timestamptz not null default now()
);
create index pay_schedules_org on pay_schedules (organization_id);

create table savings_goals (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 60),
  target_cents integer not null check (target_cents between 100 and 1000000000),
  deadline date,
  monthly_plan_cents integer check (monthly_plan_cents is null or monthly_plan_cents between 0 and 100000000),
  done integer not null default 0 check (done in (0, 1)),
  created_at timestamptz not null default now()
);
create index savings_goals_org on savings_goals (organization_id);

create table savings_entries (
  id uuid primary key,
  goal_id uuid not null references savings_goals(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  amount_cents integer not null check (amount_cents between -100000000 and 100000000 and amount_cents <> 0),
  day date not null,
  created_at timestamptz not null default now()
);
create index savings_entries_goal on savings_entries (goal_id);

create table bill_meta (
  bill_id uuid primary key references my_bills(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  subscription integer not null default 0 check (subscription in (0, 1)),
  reviewed_at timestamptz
);
create index bill_meta_org on bill_meta (organization_id);

create table credit_cards (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 60),
  limit_cents integer not null check (limit_cents between 100 and 100000000),
  balance_cents integer not null default 0 check (balance_cents between 0 and 100000000),
  statement_day integer check (statement_day is null or statement_day between 1 and 31),
  updated_at timestamptz not null default now()
);
create index credit_cards_org on credit_cards (organization_id);

alter table income_entries enable row level security;
alter table pay_schedules enable row level security;
alter table savings_goals enable row level security;
alter table savings_entries enable row level security;
alter table bill_meta enable row level security;
alter table credit_cards enable row level security;
create policy income_entries_read on income_entries for select using (public.is_member(organization_id));
create policy pay_schedules_read on pay_schedules for select using (public.is_member(organization_id));
create policy savings_goals_read on savings_goals for select using (public.is_member(organization_id));
create policy savings_entries_read on savings_entries for select using (public.is_member(organization_id));
create policy bill_meta_read on bill_meta for select using (public.is_member(organization_id));
create policy credit_cards_read on credit_cards for select using (public.is_member(organization_id));
