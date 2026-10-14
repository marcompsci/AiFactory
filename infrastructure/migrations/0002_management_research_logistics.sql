-- AI Civilization V4.0 — management hierarchy, market intelligence, logistics, two-stage release approval.
-- Applies on top of 0001_init.sql. Column names match services/core/db.py (SQLite locally).

-- ---------------------------------------------------------------- hierarchy
create table departments (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  key text not null,
  name text not null,
  district text not null,
  supervisor_agent_id uuid references agents(id),
  daily_budget_usd numeric(12,4) not null default 2.00,
  max_concurrent_missions int not null default 1 check (max_concurrent_missions > 0),
  created_at timestamptz not null default now(),
  unique (organization_id, key)
);

alter table agents add column department_id uuid references departments(id);
alter table agents add column tier text not null default 'specialist'
  check (tier in ('general_manager','supervisor','specialist'));

-- OWNER -> GENERAL MANAGER -> SUPERVISORS -> SPECIALISTS. supervisor_agent_id null = reports to the owner.
create table agent_reporting_lines (
  agent_id uuid primary key references agents(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  supervisor_agent_id uuid references agents(id),
  check (agent_id <> supervisor_agent_id)
);

create table agent_reports (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  agent_id uuid not null references agents(id),
  supervisor_agent_id uuid references agents(id),
  mission_id uuid references missions(id) on delete cascade,
  task_id uuid references tasks(id) on delete set null,
  kind text not null check (kind in ('progress','blocker','completed_package','quality_concern','estimate','resource_request')),
  body text not null,
  data jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index agent_reports_supervisor_idx on agent_reports (supervisor_agent_id, created_at);

create table manager_decisions (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  manager_agent_id uuid not null references agents(id),
  decision_type text not null check (decision_type in
    ('goal_assignment','opportunity_review','routing','acceptance','escalation','reassignment','milestone_approval',
     'release_review','revision_request','budget_enforcement','drift_check')),
  subject_type text not null,
  subject_id uuid not null,
  outcome text not null,
  rationale text not null,
  method text not null check (method in ('rules','model')),   -- deterministic rule or Opus judgment
  model text,
  inputs jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index manager_decisions_subject_idx on manager_decisions (subject_type, subject_id);

create table goal_checkpoints (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  mission_id uuid not null references missions(id) on delete cascade,
  status text not null check (status in ('on_track','drift','blocked','stalled')),
  findings jsonb not null default '[]',
  created_at timestamptz not null default now()
);

create table scheduled_jobs (
  key text primary key,
  interval_seconds int not null check (interval_seconds > 0),
  last_run_at timestamptz,
  next_run_at timestamptz not null default now(),
  last_result jsonb
);

-- ---------------------------------------------------------------- market intelligence
create table market_sources (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  key text not null,                         -- apple_charts | etsy | depop | app_store_connect | search
  name text not null,
  access text not null check (access in ('public','api_key','partner','owner_authorized','unavailable')),
  terms_url text,
  rate_limit_per_hour int not null default 60,
  daily_query_limit int not null default 50,
  unique (organization_id, key)
);

create table research_runs (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  source_id uuid not null references market_sources(id),
  research_agent_id uuid not null references agents(id),
  mission_id uuid references missions(id),
  query text not null,
  query_hash text not null,
  region text not null default 'US',
  status text not null check (status in ('RUNNING','COMPLETED','FAILED','SKIPPED')),
  data_mode text not null check (data_mode in ('live','fixture','cache')),  -- fixtures are never presented as live research
  error text,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  unique (organization_id, source_id, query_hash, region, started_at)
);
create index research_runs_dedupe_idx on research_runs (source_id, query_hash, region, started_at);

create table research_cache (                -- dedupes identical queries within the TTL
  key text primary key,                       -- source:query_hash:region
  payload jsonb not null,
  data_mode text not null,
  fetched_at timestamptz not null default now(),
  expires_at timestamptz not null
);

create table research_findings (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  run_id uuid not null references research_runs(id) on delete cascade,
  source_platform text not null,
  title text not null,
  summary text not null,
  source_url text not null,
  collected_at timestamptz not null,
  geographic_scope text not null,
  data_coverage text not null,
  measurement_type text not null check (measurement_type in ('direct_sales','popularity_proxy','ranking','review_signal','listing_count')),
  metrics jsonb not null default '{}',
  confidence text not null check (confidence in ('low','medium','high')),
  data_mode text not null check (data_mode in ('live','fixture','cache')),
  created_at timestamptz not null default now()
);

create table opportunities (
  id uuid primary key,                                          -- packet_id
  organization_id uuid not null references organizations(id) on delete cascade,
  source_platform text not null,
  research_agent_id uuid not null references agents(id),
  research_mission_id uuid references missions(id),
  title text not null,
  description text not null,
  evidence jsonb not null default '[]',                         -- [{finding_id, source_url, measurement_type, data_mode}]
  confidence text not null check (confidence in ('low','medium','high')),
  opportunity_score numeric(6,4) not null,
  proposed_department text not null,
  estimated_effort text not null,
  estimated_cost_usd numeric(12,4) not null,
  risk_flags jsonb not null default '[]',
  artifact_references jsonb not null default '[]',
  spec jsonb not null default '{}',             -- approved mission specification, the goal-drift baseline
  status text not null check (status in ('RESEARCHED','MANAGER_REVIEW','ROUTED','DEPARTMENT_ACCEPTED','IN_PRODUCTION',
    'QUALITY_REVIEW','MANAGER_APPROVAL','OWNER_APPROVAL','RELEASE_AUTHORIZED','REVISION_REQUESTED','REJECTED','CANCELLED','DEFERRED')),
  data_mode text not null check (data_mode in ('live','fixture','cache')),
  production_mission_id uuid references missions(id),
  qa_mission_id uuid references missions(id),
  release_mission_id uuid references missions(id),
  release_artifact_id uuid,
  revision_count int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table opportunity_scores (
  opportunity_id uuid not null references opportunities(id) on delete cascade,
  component text not null check (component in ('demand','momentum','saturation','differentiation','feasibility',
    'production_cost','monetization','policy_risk','owner_alignment')),
  score numeric(5,4) not null check (score between 0 and 1),
  weight numeric(6,4) not null,
  evidence jsonb not null default '[]',
  primary key (opportunity_id, component)
);

-- ---------------------------------------------------------------- logistics
create table logistics_nodes (
  id text primary key,                         -- e.g. code-forge:dispatch, junction:code-forge
  organization_id uuid not null references organizations(id) on delete cascade,
  kind text not null check (kind in ('dispatch','receiving','junction')),
  district text,
  position jsonb not null
);

create table logistics_routes (                -- directed belt segments
  id text primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  from_node text not null references logistics_nodes(id),
  to_node text not null references logistics_nodes(id),
  length numeric(10,3) not null check (length > 0),
  status text not null default 'UP' check (status in ('UP','DOWN')),
  unique (from_node, to_node)
);

create table logistics_packages (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  opportunity_id uuid references opportunities(id) on delete cascade,
  mission_id uuid references missions(id),
  task_id uuid references tasks(id),
  package_type text not null check (package_type in ('research_brief','product_proposal','design_spec','code_artifact',
    'test_report','revision_request','approval_request','release_package')),
  priority int not null default 5 check (priority between 1 and 9),
  origin_district text not null,
  destination_district text not null,
  status text not null check (status in ('QUEUED','IN_TRANSIT','ARRIVED','RECEIVED','DELIVERY_FAILED','CANCELLED')),
  route jsonb not null default '[]',           -- [segment ids]
  route_started_at timestamptz,
  eta timestamptz,
  current_node text references logistics_nodes(id),
  artifact_references jsonb not null default '[]',
  attempts int not null default 0,
  next_attempt_at timestamptz,
  dispatched_at timestamptz,
  delivered_at timestamptz,
  created_at timestamptz not null default now()
);
create index logistics_packages_status_idx on logistics_packages (status, eta);

create table package_transitions (
  id bigserial primary key,
  package_id uuid not null references logistics_packages(id) on delete cascade,
  from_status text,
  to_status text not null,
  detail jsonb not null default '{}',
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- reviews and release
create table manager_reviews (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  opportunity_id uuid not null references opportunities(id) on delete cascade,
  artifact_id uuid not null references artifacts(id),
  artifact_digest text not null,
  verdict text not null check (verdict in ('APPROVED_FOR_OWNER_REVIEW','CHANGES_REQUESTED','REJECTED','BLOCKED')),
  summary text not null,
  method text not null check (method in ('rules','model')),
  model text,
  created_at timestamptz not null default now()
);

create table review_checklists (
  id uuid primary key,
  review_id uuid not null references manager_reviews(id) on delete cascade,
  category text not null check (category in ('requirements','functional','tests','security','privacy','accessibility',
    'performance','store_requirements','documentation','market_rationale','cost','known_limitations')),
  status text not null check (status in ('pass','fail','warn','not_applicable')),
  evidence text not null,
  unique (review_id, category)
);

-- Owner decisions and release authorizations are append-only: see triggers below.
create table owner_decisions (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  opportunity_id uuid not null references opportunities(id),
  manager_review_id uuid not null references manager_reviews(id),
  artifact_id uuid not null references artifacts(id),
  artifact_digest text not null,
  decision text not null check (decision in ('APPROVE','REQUEST_CHANGES','REJECT','DEFER')),
  note text,
  decided_by uuid not null,
  created_at timestamptz not null default now()
);

create table release_authorizations (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  opportunity_id uuid not null references opportunities(id),
  owner_decision_id uuid not null unique references owner_decisions(id),
  artifact_id uuid not null references artifacts(id),
  artifact_digest text not null,             -- sha256 of the exact bundle the owner saw
  scope text not null check (scope in ('local_release','app_store_submission','listing_publication','production_deploy')),
  created_at timestamptz not null default now()
);

-- validity is derived, never edited: a later invalidation row (artifact changed, superseded) revokes it
create table release_invalidations (
  id uuid primary key,
  authorization_id uuid not null references release_authorizations(id),
  reason text not null,
  observed_digest text,
  created_at timestamptz not null default now()
);

create table release_executions (
  id uuid primary key,
  authorization_id uuid not null references release_authorizations(id),
  artifact_digest text not null,
  tool_execution_id uuid references tool_executions(id),
  destination text not null,
  created_at timestamptz not null default now()
);

alter table artifacts add column digest text;          -- sha256 for release bundles
alter table artifacts add column opportunity_id uuid references opportunities(id);
alter table missions add column kind text not null default 'fix_failing_test';
alter table missions add column opportunity_id uuid references opportunities(id);
alter table missions add column params jsonb not null default '{}';
alter table artifacts drop constraint if exists artifacts_kind_check;
alter table artifacts add constraint artifacts_kind_check check (kind in
  ('diff','test_report','patch','note','plan','release_bundle','research_brief','manager_review'));

create or replace function forbid_mutation() returns trigger language plpgsql as $$
begin
  raise exception '% is append-only', tg_table_name;
end $$;
create trigger owner_decisions_append_only before update or delete on owner_decisions
  for each row execute function forbid_mutation();
create trigger release_authorizations_append_only before update or delete on release_authorizations
  for each row execute function forbid_mutation();
create trigger release_invalidations_append_only before update or delete on release_invalidations
  for each row execute function forbid_mutation();

do $$
declare t text;
begin
  foreach t in array array['departments','agent_reporting_lines','agent_reports','manager_decisions','goal_checkpoints',
    'market_sources','research_runs','research_findings','opportunities','logistics_nodes','logistics_routes',
    'logistics_packages','manager_reviews','owner_decisions','release_authorizations']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('create policy %I on %I for select using (public.is_member(organization_id))', t || '_member_read', t);
  end loop;
end $$;
alter table opportunity_scores enable row level security;
create policy opportunity_scores_member_read on opportunity_scores for select
  using (exists (select 1 from opportunities o where o.id = opportunity_id and public.is_member(o.organization_id)));
