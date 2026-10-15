-- AI Civilization V5.1: owner-directed, read-only free-alternative investigations.
-- An investigation authorizes research and sandboxed evaluation only: never a purchase, a cancellation, an external
-- submission, an account change or a production deployment (enforced in services/tools/registry.py, not prompts).

create table savings_investigations (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  packet_id uuid not null references cost_review_packets(id) on delete cascade,
  status text not null check (status in ('REQUESTED','RESEARCHING','EVALUATING','TESTING','MANAGER_REVIEW','AWAITING_OWNER',
    'BLOCKED','FAILED','CANCELLED')),
  requested_by uuid not null,
  owner_note text,
  category text,
  top_candidate_id uuid,
  research_mission_id uuid references missions(id),
  evaluation_mission_id uuid references missions(id),
  sandbox_mission_id uuid references missions(id),
  qa_mission_id uuid references missions(id),
  recommendation jsonb not null default '{}',
  reason text,
  data_mode text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
-- one live investigation per cost review at a time
create unique index savings_investigations_one_active on savings_investigations (packet_id)
  where status not in ('AWAITING_OWNER','BLOCKED','FAILED','CANCELLED');

create table alternative_candidates (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  investigation_id uuid not null references savings_investigations(id) on delete cascade,
  slug text not null,
  name text not null,
  vendor text,
  product_url text,
  docs_url text,
  source_url text not null,
  license text not null,
  license_url text,
  open_source smallint not null default 0,
  pricing jsonb not null default '{}',
  features jsonb not null default '[]',
  claims jsonb not null default '{}',
  limitations jsonb not null default '[]',
  maintenance jsonb not null default '{}',
  estimated_costs jsonb not null default '{}',
  evidence_as_of text not null,
  confidence text not null check (confidence in ('low','medium','high')),
  rank int,
  shortlisted smallint not null default 0,
  data_mode text not null check (data_mode in ('fixture','live')),
  created_at timestamptz not null default now(),
  unique (investigation_id, slug)
);

create table alternative_evidence (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  candidate_id uuid not null references alternative_candidates(id) on delete cascade,
  kind text not null check (kind in ('pricing','license','features','maintenance','documentation','restriction')),
  claim text not null,
  source_url text not null,
  as_of text not null,
  data_mode text not null,
  created_at timestamptz not null default now()
);

create table compatibility_assessments (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  candidate_id uuid not null references alternative_candidates(id) on delete cascade,
  compatibility double precision not null,
  security double precision not null,
  functionality double precision not null,
  migration double precision not null,
  total_cost double precision not null,
  total_score double precision not null,
  rationale jsonb not null default '{}',
  assessed_by uuid references agents(id),
  created_at timestamptz not null default now()
);

create table sandbox_evaluations (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  investigation_id uuid not null references savings_investigations(id) on delete cascade,
  candidate_id uuid not null references alternative_candidates(id) on delete cascade,
  status text not null check (status in ('RUNNING','PASSED','FAILED','ERROR')),
  sandbox text not null,
  network_isolated smallint not null default 0,
  subject text not null,
  command jsonb not null default '[]',
  exit_code int,
  passed int not null default 0,
  failed int not null default 0,
  errors int not null default 0,
  results jsonb not null default '[]',
  output_excerpt text,
  kit_sha256 text,
  duration_ms int,
  artifact_id uuid references artifacts(id),
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create table cost_comparisons (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  investigation_id uuid not null references savings_investigations(id) on delete cascade,
  candidate_id uuid references alternative_candidates(id) on delete cascade,
  label text not null,
  first_year_minor bigint not null,
  three_year_minor bigint not null,
  migration_minor bigint not null default 0,
  notes text,
  data_mode text not null,
  created_at timestamptz not null default now()
);

create table investigation_reviews (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  investigation_id uuid not null references savings_investigations(id) on delete cascade,
  stage text not null check (stage in ('qa','manager')),
  reviewer_agent_id uuid references agents(id),
  verdict text not null,
  summary text not null,
  findings jsonb not null default '[]',
  method text not null default 'rules',
  model text,
  created_at timestamptz not null default now()
);

alter table logistics_packages drop constraint if exists logistics_packages_package_type_check;
alter table logistics_packages add constraint logistics_packages_package_type_check check (package_type in
  ('research_brief','product_proposal','design_spec','code_artifact','test_report','revision_request','approval_request',
   'release_package','revenue_report','expense_alert','bill_reminder','fee_research_request','savings_recommendation',
   'purchase_request','payment_proposal','tax_review_package','financial_forecast','owner_approval_request',
   'savings_investigation'));
alter table logistics_packages drop constraint if exists logistics_packages_finance_subject_check;
alter table logistics_packages add constraint logistics_packages_finance_subject_check check (
  package_type not in ('revenue_report','expense_alert','bill_reminder','fee_research_request','savings_recommendation',
                       'purchase_request','payment_proposal','tax_review_package','financial_forecast','owner_approval_request',
                       'savings_investigation')
  or (subject_type is not null and subject_id is not null));

do $$
declare t text;
begin
  foreach t in array array['savings_investigations','alternative_candidates','alternative_evidence','compatibility_assessments',
    'sandbox_evaluations','cost_comparisons','investigation_reviews']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('create policy %I on %I for select using (public.is_finance_member(organization_id))', t || '_finance_read', t);
  end loop;
end $$;
