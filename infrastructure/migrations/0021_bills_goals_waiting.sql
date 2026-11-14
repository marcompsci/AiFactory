-- V6.98–V6.112: your own bills (my_bills; finance keeps its synced `bills` separately) (tracked, never paid by the app), weekly goals, waiting for people, end-of-day notes, list styles.
create table my_bills (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 80),
  amount_cents integer check (amount_cents is null or amount_cents between 0 and 100000000),
  currency text not null default 'USD' check (currency ~ '^[A-Z]{3}$'),
  cadence text not null default 'monthly' check (cadence in ('monthly','yearly')),
  due_day integer not null check (due_day between 1 and 31),
  due_month integer check (due_month is null or due_month between 1 and 12),
  autopay integer not null default 0 check (autopay in (0, 1)),
  link_url text check (link_url is null or (char_length(link_url) between 10 and 2048 and link_url ~ '^https?://')),
  notes text not null default '' check (char_length(notes) <= 1000),
  remind_days integer not null default 3 check (remind_days between 0 and 14),
  active integer not null default 1 check (active in (0, 1)),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  check (cadence = 'monthly' or due_month is not null)
);
create index my_bills_org on my_bills (organization_id);

create table my_bill_payments (
  id uuid primary key,
  bill_id uuid not null references my_bills(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  period text not null check (period ~ '^[0-9]{4}(-[0-9]{2})?$'),
  amount_cents integer check (amount_cents is null or amount_cents between 0 and 100000000),
  paid_at timestamptz not null,
  created_by uuid not null,
  constraint my_bill_payments_once unique (bill_id, period)
);
create index my_bill_payments_bill on my_bill_payments (bill_id);

create table week_goals (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  week_start date not null,
  position integer not null default 0,
  text text not null check (char_length(text) between 1 and 120),
  done integer not null default 0 check (done in (0, 1)),
  created_at timestamptz not null default now()
);
create index week_goals_org on week_goals (organization_id, week_start);

create table task_goals (
  task_id uuid primary key references my_tasks(id) on delete cascade,
  goal_id uuid not null references week_goals(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade
);
create index task_goals_goal on task_goals (goal_id);

create table task_waiting (
  task_id uuid primary key references my_tasks(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  person text not null check (char_length(person) between 1 and 60),
  follow_up_at timestamptz not null,
  created_at timestamptz not null default now()
);
create index task_waiting_org on task_waiting (organization_id);

create table day_notes (
  organization_id uuid not null references organizations(id) on delete cascade,
  day date not null,
  note text not null default '' check (char_length(note) <= 1000),
  moved integer not null default 0,
  created_at timestamptz not null default now(),
  primary key (organization_id, day)
);

create table list_styles (
  organization_id uuid not null references organizations(id) on delete cascade,
  list_name text not null check (list_name ~ '^[a-z0-9][a-z0-9_-]{0,39}$'),
  color text not null check (color ~ '^#[0-9A-Fa-f]{6}$'),
  icon text not null check (char_length(icon) between 1 and 40),
  primary key (organization_id, list_name)
);

alter table my_bills enable row level security;
alter table my_bill_payments enable row level security;
alter table week_goals enable row level security;
alter table task_goals enable row level security;
alter table task_waiting enable row level security;
alter table day_notes enable row level security;
alter table list_styles enable row level security;
create policy my_bills_read on my_bills for select using (public.is_member(organization_id));
create policy my_bill_payments_read on my_bill_payments for select using (public.is_member(organization_id));
create policy week_goals_read on week_goals for select using (public.is_member(organization_id));
create policy task_goals_read on task_goals for select using (public.is_member(organization_id));
create policy task_waiting_read on task_waiting for select using (public.is_member(organization_id));
create policy day_notes_read on day_notes for select using (public.is_member(organization_id));
create policy list_styles_read on list_styles for select using (public.is_member(organization_id));
