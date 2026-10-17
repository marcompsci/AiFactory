-- V6.16 scheduled missions (created only on the owner's confirm; read-only kinds) and V6.17 mission priority.
create table mission_schedules (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  kind text not null check (kind in ('run_tests','market_research')),
  params jsonb not null default '{}',
  title text not null,
  cadence text not null check (cadence in ('daily','weekly')),
  weekday integer check (weekday between 0 and 6),
  hour integer not null check (hour between 0 and 23),
  minute integer not null default 0 check (minute between 0 and 59),
  tz text not null default 'UTC',
  next_run_at timestamptz not null,
  enabled integer not null default 1,
  created_by uuid not null,
  runs integer not null default 0,
  last_run_at timestamptz,
  last_mission_id uuid,
  last_error text,
  created_at timestamptz not null default now()
);
create index mission_schedules_due on mission_schedules (enabled, next_run_at);

create table mission_priorities (
  mission_id uuid primary key references missions(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  priority text not null default 'normal' check (priority in ('urgent','normal','low')),
  set_by uuid,
  updated_at timestamptz not null default now()
);

alter table play_proposals drop constraint if exists play_proposals_kind_check;
alter table play_proposals add constraint play_proposals_kind_check
  check (kind in ('create_mission','start_research','cancel_mission','create_schedule'));

alter table mission_schedules enable row level security;
create policy mission_schedules_member_read on mission_schedules for select using (public.is_member(organization_id));
alter table mission_priorities enable row level security;
create policy mission_priorities_member_read on mission_priorities for select using (public.is_member(organization_id));
