-- V6.29 saved requests, V6.30 per-schedule run budgets and run history (costs, V6.31 comparing runs).
create table saved_requests (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  name text not null,
  name_key text not null,
  kind text not null check (kind in ('fix_failing_test','run_tests','market_research')),
  spec jsonb not null default '{}',
  priority text not null default 'normal' check (priority in ('urgent','normal','low')),
  created_by uuid not null,
  uses integer not null default 0,
  last_used_at timestamptz,
  last_mission_id uuid references missions(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (organization_id, name_key)
);

create table schedule_budgets (
  schedule_id uuid primary key references mission_schedules(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  budget_usd numeric not null check (budget_usd > 0 and budget_usd <= 50),
  set_by uuid,
  updated_at timestamptz not null default now()
);

create table schedule_runs (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  schedule_id uuid not null references mission_schedules(id) on delete cascade,
  mission_id uuid not null references missions(id) on delete cascade,
  started_at timestamptz not null default now()
);
create index schedule_runs_schedule on schedule_runs (schedule_id, started_at desc);

alter table play_proposals drop constraint if exists play_proposals_kind_check;
alter table play_proposals add constraint play_proposals_kind_check
  check (kind in ('create_mission','start_research','cancel_mission','create_schedule','rerun_mission','start_saved'));

alter table saved_requests enable row level security;
create policy saved_requests_member_read on saved_requests for select using (public.is_member(organization_id));
alter table schedule_budgets enable row level security;
create policy schedule_budgets_member_read on schedule_budgets for select using (public.is_member(organization_id));
alter table schedule_runs enable row level security;
create policy schedule_runs_member_read on schedule_runs for select using (public.is_member(organization_id));
