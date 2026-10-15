-- App Lab: research-driven, owner-gated improvements to the owner's GitHub repositories.
-- Nothing reaches GitHub until the owner approves the exact change (step-up), and never the default branch.

create table lab_repositories (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  full_name text not null check (full_name ~ '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'),
  default_branch text not null default 'main',
  status text not null default 'PENDING_AUTHORIZATION' check (status in ('PENDING_AUTHORIZATION','ACTIVE','REVOKED','ERROR')),
  auth_mode text not null default 'token' check (auth_mode in ('token','github_signin','ambient')),
  secret_ciphertext text,
  authorized_by uuid,
  authorized_at timestamptz,
  claude_code_ready smallint not null default 0,
  autopilot smallint not null default 0,
  head_sha text,
  last_scan_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  unique (organization_id, full_name)
);

create table lab_cycles (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  repository_id uuid not null references lab_repositories(id) on delete cascade,
  status text not null check (status in ('RESEARCHING','ANALYZING','MANAGER_REVIEW','AWAITING_OWNER','DONE','FAILED','CANCELLED')),
  trigger text not null check (trigger in ('owner','autopilot')),
  research_mission_id uuid references missions(id),
  analysis_mission_id uuid references missions(id),
  reason text,
  data_mode text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table design_insights (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  cycle_id uuid not null references lab_cycles(id) on delete cascade,
  pattern text not null,
  title text not null,
  why_it_works text not null,
  signals jsonb not null default '{}',
  evidence jsonb not null default '[]',
  data_mode text not null,
  created_at timestamptz not null default now()
);

create table lab_proposals (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  cycle_id uuid not null references lab_cycles(id) on delete cascade,
  repository_id uuid not null references lab_repositories(id) on delete cascade,
  status text not null check (status in ('PROPOSED','MANAGER_REVIEW','AWAITING_OWNER','APPROVED','PUBLISHING','PUBLISHED','REJECTED','DEFERRED',
    'WITHDRAWN','FAILED')),
  title text not null,
  summary text not null,
  insight_ids jsonb not null default '[]',
  files jsonb not null default '[]',
  plan jsonb not null default '[]',
  risk text not null check (risk in ('low','medium','high')),
  route text not null check (route in ('patch','claude_code')),
  base_sha text,
  patch text,
  patch_sha256 text,
  checks jsonb not null default '{}',
  instructions text,
  payload_hash text not null,
  gm_review jsonb not null default '{}',
  decided_by uuid,
  decided_at timestamptz,
  step_up_method text,
  publish_mission_id uuid references missions(id),
  published jsonb not null default '{}',
  tracking jsonb not null default '{}',
  authored_by text,
  data_mode text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table logistics_packages drop constraint if exists logistics_packages_package_type_check;
alter table logistics_packages add constraint logistics_packages_package_type_check check (package_type in
  ('research_brief','product_proposal','design_spec','code_artifact','test_report','revision_request','approval_request',
   'release_package','revenue_report','expense_alert','bill_reminder','fee_research_request','savings_recommendation',
   'purchase_request','payment_proposal','tax_review_package','financial_forecast','owner_approval_request',
   'savings_investigation','design_insights','lab_proposal'));

do $$
declare t text;
begin
  foreach t in array array['lab_repositories','lab_cycles','design_insights','lab_proposals']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('create policy %I on %I for select using (public.is_member(organization_id))', t || '_member_read', t);
  end loop;
end $$;
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on lab_repositories from anon, authenticated';
    execute 'grant select (id, organization_id, full_name, default_branch, status, auth_mode, authorized_by, authorized_at,
             claude_code_ready, autopilot, head_sha, last_scan_at, last_error, created_at) on lab_repositories to authenticated';
  end if;
end $$;
