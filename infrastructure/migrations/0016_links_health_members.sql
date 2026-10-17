-- V6.19 weekday schedules, V6.20 schedule health, V6.21/V6.22 run again and follow-on missions, V6.24 sign-in roster.
alter table mission_schedules drop constraint if exists mission_schedules_cadence_check;
alter table mission_schedules add constraint mission_schedules_cadence_check check (cadence in ('daily','weekly','weekdays'));

create table schedule_health (
  schedule_id uuid primary key references mission_schedules(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  failures integer not null default 0,
  paused_reason text,
  paused_at timestamptz,
  updated_at timestamptz not null default now()
);

create table mission_links (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  kind text not null check (kind in ('rerun','followup')),
  from_mission_id uuid not null references missions(id) on delete cascade,
  to_mission_id uuid references missions(id) on delete set null,
  status text not null check (status in ('WAITING','STARTING','STARTED','CANCELLED','FAILED')),
  spec jsonb not null default '{}',
  reason text,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index mission_links_from on mission_links (from_mission_id);
create index mission_links_waiting on mission_links (status) where status = 'WAITING';

create table org_members (
  organization_id uuid not null references organizations(id) on delete cascade,
  user_id uuid not null,
  role text not null check (role in ('viewer','operator','admin','owner')),
  mode text not null,
  email text,
  first_seen timestamptz not null default now(),
  last_seen timestamptz not null default now(),
  primary key (organization_id, user_id)
);

alter table play_proposals drop constraint if exists play_proposals_kind_check;
alter table play_proposals add constraint play_proposals_kind_check
  check (kind in ('create_mission','start_research','cancel_mission','create_schedule','rerun_mission'));

alter table schedule_health enable row level security;
create policy schedule_health_member_read on schedule_health for select using (public.is_member(organization_id));
alter table mission_links enable row level security;
create policy mission_links_member_read on mission_links for select using (public.is_member(organization_id));
alter table org_members enable row level security;
-- no member policy: the roster (with emails) is read only through the owner-only API
