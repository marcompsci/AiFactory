-- V6.4 the owner's charter and V6.5 recovery plans.
-- The charter holds rules only the owner amends, and they can only make the built-in safety stricter (approvals for
-- publishing, spending and releases stay locked in code). Every amendment is kept; loosening one needs step-up.
-- A recovery plan is the General Manager's proposal after a failed or stalled mission; it runs only on approval.

create table charters (
  organization_id uuid primary key references organizations(id) on delete cascade,
  rules jsonb not null default '{}',
  version integer not null default 0,
  updated_by uuid,
  updated_at timestamptz not null default now()
);

create table charter_amendments (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  version integer not null,
  changed_by uuid not null,
  changes jsonb not null default '{}',
  note text not null default '',
  loosened integer not null default 0,
  step_up_method text,
  created_at timestamptz not null default now(),
  unique (organization_id, version)
);
create trigger charter_amendments_append_only before update or delete on charter_amendments
  for each row execute function forbid_mutation();

create table recovery_plans (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  mission_id uuid not null references missions(id) on delete cascade,
  failure_mode text not null,
  strategy text not null check (strategy in ('retry_later','retry_with_guidance','raise_budget','narrow_scope','none')),
  summary text not null,
  rationale text not null,
  params jsonb not null default '{}',
  status text not null default 'PENDING' check (status in ('PENDING','APPROVED','DECLINED','EXPIRED','SUPERSEDED')),
  new_mission_id uuid references missions(id),
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz not null default now()
);
create index recovery_plans_status_idx on recovery_plans (organization_id, status);
create unique index recovery_plans_one_pending on recovery_plans (mission_id) where status = 'PENDING';

alter table charters enable row level security;
create policy charters_member_read on charters for select using (public.is_member(organization_id));
alter table charter_amendments enable row level security;
create policy charter_amendments_member_read on charter_amendments for select using (public.is_member(organization_id));
alter table recovery_plans enable row level security;
create policy recovery_plans_member_read on recovery_plans for select using (public.is_member(organization_id));
