-- AI Civilization — initial schema (PostgreSQL 15+ / Supabase)
-- UUID ids, UTC timestamptz, organization isolation enforced with RLS.
-- The local dev server uses SQLite with the same tables (services/core/db.py);
-- this file is the production source of truth.

create extension if not exists pgcrypto;
-- pgvector ships with Supabase. On a plain Postgres without it, memory_entries.embedding is created as jsonb instead.
do $$ begin
  if exists (select 1 from pg_available_extensions where name = 'vector') then
    create extension if not exists vector;
  end if;
end $$;
-- Supabase provides auth.uid(). On plain Postgres (CI, self-hosting) a stub returns null, so RLS read policies deny
-- every non-owner role; the API connects as the table owner (service role) and is unaffected.
do $$ begin
  if not exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'auth' and p.proname = 'uid') then
    create schema if not exists auth;
    create function auth.uid() returns uuid language sql stable as 'select null::uuid';
  end if;
end $$;

-- ---------------------------------------------------------------- tenancy
create table organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  daily_budget_usd numeric(12,4) not null default 5.00,
  emergency_stopped smallint not null default 0 check (emergency_stopped in (0,1)),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table memberships (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  user_id uuid not null,                      -- auth.users.id
  role text not null check (role in ('owner','admin','operator','viewer')),
  created_at timestamptz not null default now(),
  unique (organization_id, user_id)
);

create table projects (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  name text not null,
  allowed_tools jsonb not null default '[]',
  created_at timestamptz not null default now()
);

create table repositories (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  project_id uuid not null references projects(id) on delete cascade,
  provider text not null check (provider in ('local','github')),
  full_name text not null,
  default_branch text not null default 'main',
  github_installation_id bigint,
  created_at timestamptz not null default now(),
  unique (project_id, full_name)
);

-- ---------------------------------------------------------------- agents
create table agents (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  key text not null,
  name text not null,
  role text not null,
  home_district text not null,
  avatar jsonb not null default '{}',
  model_provider text not null,
  model_name text not null,
  execution_state text not null default 'IDLE' check (execution_state in
    ('IDLE','ASSIGNED','PLANNING','EXECUTING','WAITING_FOR_TOOL','WAITING_FOR_AGENT',
     'WAITING_FOR_APPROVAL','REVIEWING','COMPLETED','FAILED','CANCELLED')),
  max_usd_per_mission numeric(12,4) not null default 0.50,
  max_concurrent_tasks int not null default 1 check (max_concurrent_tasks > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, key)
);

create table agent_capabilities (
  agent_id uuid not null references agents(id) on delete cascade,
  tool_name text not null,
  primary key (agent_id, tool_name)
);

-- visual position is kept apart from execution state on purpose
create table agent_positions (
  agent_id uuid primary key references agents(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  district text not null,
  waypoint text,
  movement_state text not null default 'STATIONARY' check (movement_state in ('STATIONARY','MOVING')),
  updated_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- missions
create table missions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  project_id uuid not null references projects(id),
  repository_id uuid references repositories(id),
  title text not null,
  prompt text not null,
  status text not null check (status in
    ('CREATED','VALIDATING','PLANNING','QUEUED','RUNNING','WAITING_FOR_APPROVAL','COMPLETED','FAILED','CANCELLED')),
  execution_mode text not null check (execution_mode in ('live','simulation')),
  budget_usd numeric(12,4) not null default 1.00,
  spent_usd_estimated numeric(12,6) not null default 0,
  idempotency_key text,
  failure_reason text,
  outcome text,                               -- e.g. published | not_published | no_change
  paused smallint not null default 0 check (paused in (0,1)),  -- operator pause or automatic budget suspension
  pause_reason text,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);
create index missions_org_status_idx on missions (organization_id, status);

create table tasks (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  mission_id uuid not null references missions(id) on delete cascade,
  agent_id uuid not null references agents(id),
  key text not null,
  title text not null,
  district text not null,
  status text not null check (status in ('PENDING','RUNNING','WAITING_FOR_APPROVAL','COMPLETED','FAILED','CANCELLED','SKIPPED')),
  inputs jsonb not null default '{}',
  permitted_tools jsonb not null default '[]',
  expected_outputs jsonb not null default '{}',
  validation jsonb not null default '{}',
  outputs jsonb,
  attempt int not null default 0,
  max_attempts int not null default 2,
  timeout_seconds int not null default 120,
  ordinal int not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (mission_id, key)
);
create index tasks_mission_idx on tasks (mission_id, ordinal);

create table task_dependencies (
  task_id uuid not null references tasks(id) on delete cascade,
  depends_on_task_id uuid not null references tasks(id) on delete cascade,
  primary key (task_id, depends_on_task_id),
  check (task_id <> depends_on_task_id)
);

create table task_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  task_id uuid not null references tasks(id) on delete cascade,
  attempt int not null,
  status text not null check (status in ('RUNNING','COMPLETED','FAILED','CANCELLED')),
  error text,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  unique (task_id, attempt)
);

create table agent_messages (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  mission_id uuid references missions(id) on delete cascade,
  from_agent_id uuid references agents(id),
  to_agent_id uuid references agents(id),
  kind text not null check (kind in ('handoff','status','question','explanation')),
  body text not null,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- events + outbox
create table events (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  sequence bigint not null,
  mission_id uuid references missions(id) on delete cascade,
  agent_id uuid references agents(id),
  event_type text not null,
  schema_version int not null default 1,
  correlation_id uuid not null,
  execution_mode text not null default 'live' check (execution_mode in ('live','simulation')),
  payload jsonb not null default '{}',
  occurred_at timestamptz not null default now(),
  unique (organization_id, sequence)
);
create index events_mission_idx on events (mission_id, sequence);

-- written in the same transaction as the state change and the events row
create table event_outbox (
  id bigserial primary key,
  event_id uuid not null unique references events(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  published_at timestamptz,
  attempts int not null default 0,
  last_error text,
  created_at timestamptz not null default now()
);
create index event_outbox_unpublished_idx on event_outbox (id) where published_at is null;

-- ---------------------------------------------------------------- approvals, artifacts, tools
create table approvals (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  mission_id uuid not null references missions(id) on delete cascade,
  task_id uuid not null references tasks(id) on delete cascade,
  action text not null,
  summary text not null,
  status text not null check (status in ('PENDING','GRANTED','REJECTED','EXPIRED')),
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz not null default now()
);
create unique index approvals_one_pending_per_task on approvals (task_id) where status = 'PENDING';

create table artifacts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  mission_id uuid references missions(id) on delete cascade,
  task_id uuid references tasks(id) on delete set null,
  agent_id uuid references agents(id),
  kind text not null check (kind in ('diff','test_report','patch','note','plan')),
  title text not null,
  content text not null,                     -- small artifacts inline; large ones go to Supabase Storage
  storage_path text,
  created_at timestamptz not null default now()
);

create table tool_executions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  mission_id uuid references missions(id) on delete cascade,
  task_id uuid references tasks(id) on delete set null,
  agent_id uuid not null references agents(id),
  tool_name text not null,
  arguments jsonb not null default '{}',
  status text not null check (status in ('RUNNING','COMPLETED','FAILED','DENIED')),
  exit_code int,
  output_excerpt text,
  duration_ms int,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create table usage_records (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  mission_id uuid references missions(id) on delete cascade,
  agent_id uuid references agents(id),
  provider text not null,
  model text not null,
  input_tokens int not null default 0,
  output_tokens int not null default 0,
  estimated_cost_usd numeric(12,6) not null default 0,
  provider_reported_cost_usd numeric(12,6),   -- null until the provider reports it; never shown as "charged" otherwise
  created_at timestamptz not null default now()
);
create index usage_org_day_idx on usage_records (organization_id, created_at);

-- ---------------------------------------------------------------- memory + world
create table memory_entries (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  scope text not null check (scope in ('mission','agent','project','shared')),
  mission_id uuid references missions(id) on delete cascade,
  agent_id uuid references agents(id) on delete cascade,
  trust text not null check (trust in ('verified','hypothesis')),
  content text not null,
  source text not null,                       -- attribution: tool execution id, artifact id, or URL
  expires_at timestamptz,
  created_at timestamptz not null default now()
);

do $$ begin
  if exists (select 1 from pg_extension where extname = 'vector') then
    execute 'alter table memory_entries add column embedding vector(1536)';
  else
    execute 'alter table memory_entries add column embedding jsonb';
  end if;
end $$;

create table world_entities (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  kind text not null check (kind in ('district','building','workstation','waypoint')),
  key text not null,
  config jsonb not null default '{}',
  unique (organization_id, kind, key)
);

-- ---------------------------------------------------------------- row level security
create or replace function public.is_member(org uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from memberships m where m.organization_id = org and m.user_id = auth.uid());
$$;

do $$
declare t text;
begin
  foreach t in array array['projects','repositories','agents','agent_positions','missions','tasks',
    'task_runs','agent_messages','events','approvals','artifacts','tool_executions','usage_records',
    'memory_entries','world_entities']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('create policy %I on %I for select using (public.is_member(organization_id))', t || '_member_read', t);
  end loop;
end $$;

alter table organizations enable row level security;
create policy organizations_member_read on organizations for select using (public.is_member(id));
alter table memberships enable row level security;
create policy memberships_self_read on memberships for select using (user_id = auth.uid());
alter table event_outbox enable row level security;   -- no client policies: service role only

-- Writes go through the API (service role), never directly from the browser.
