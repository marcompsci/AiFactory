-- V6.68–V6.87: checklists, lists, estimates, snooze, waiting-on, templates, result feedback and focus sessions.
create table task_meta (
  task_id uuid primary key references my_tasks(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  list_name text check (list_name is null or list_name ~ '^[a-z0-9][a-z0-9_-]{0,39}$'),
  estimate_minutes integer check (estimate_minutes is null or estimate_minutes between 5 and 600),
  snoozed_until timestamptz,
  blocked_by uuid references my_tasks(id) on delete set null,
  client_ref text check (client_ref is null or client_ref ~ '^[A-Za-z0-9-]{8,64}$'),
  updated_at timestamptz not null default now()
);
create index task_meta_org on task_meta (organization_id);
create unique index task_meta_client_ref on task_meta (organization_id, client_ref) where client_ref is not null;

create table task_items (
  id uuid primary key,
  task_id uuid not null references my_tasks(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  text text not null check (char_length(text) between 1 and 200),
  done integer not null default 0 check (done in (0, 1)),
  position integer not null default 0,
  from_agents integer not null default 0 check (from_agents in (0, 1)),
  created_at timestamptz not null default now(),
  done_at timestamptz
);
create index task_items_task on task_items (task_id, position);

create table task_templates (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 60),
  title text not null check (char_length(title) between 2 and 160),
  notes text not null default '',
  kind text not null default 'personal' check (kind in ('code','research','write','personal')),
  priority text not null default 'normal' check (priority in ('urgent','normal','low')),
  list_name text,
  estimate_minutes integer,
  budget_usd numeric check (budget_usd is null or (budget_usd > 0 and budget_usd <= 50)),
  items jsonb not null default '[]',
  created_by uuid not null,
  created_at timestamptz not null default now()
);
create index task_templates_org on task_templates (organization_id);

create table task_feedback (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  task_id uuid not null references my_tasks(id) on delete cascade,
  mission_id uuid not null unique references missions(id) on delete cascade,
  rating integer not null check (rating in (-1, 1)),
  reason text not null default '' check (char_length(reason) <= 300),
  agent_key text,
  created_by uuid not null,
  created_at timestamptz not null default now()
);
create index task_feedback_org on task_feedback (organization_id);

create table focus_sessions (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  task_id uuid not null references my_tasks(id) on delete cascade,
  minutes integer not null check (minutes between 1 and 240),
  started_at timestamptz not null,
  created_by uuid not null,
  created_at timestamptz not null default now()
);
create index focus_sessions_org on focus_sessions (organization_id, started_at);

alter table task_meta enable row level security;
alter table task_items enable row level security;
alter table task_templates enable row level security;
alter table task_feedback enable row level security;
alter table focus_sessions enable row level security;
create policy task_meta_read on task_meta for select using (public.is_member(organization_id));
create policy task_items_read on task_items for select using (public.is_member(organization_id));
create policy task_templates_read on task_templates for select using (public.is_member(organization_id));
create policy task_feedback_read on task_feedback for select using (public.is_member(organization_id));
create policy focus_sessions_read on focus_sessions for select using (public.is_member(organization_id));
