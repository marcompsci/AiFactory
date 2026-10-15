-- AI Civilization V5.0: AI Central Bank (financial district).
-- Applies on top of 0002. Column names match services/core/db.py (SQLite locally).
-- Money is stored in integer minor units (cents). Every data row carries data_mode: simulated | upload | live.
-- Financial tables are readable only by owners and admins (RLS); the API connects as the service role.

create table financial_connections (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  kind text not null check (kind in ('bank_feed','card_feed','payment_processor','app_store','marketplace','accounting','billing','upload')),
  provider text not null,
  display_name text not null,
  access_mode text not null default 'read_only' check (access_mode = 'read_only'),   -- write-capable integrations are not allowed
  scopes jsonb not null default '[]',
  status text not null default 'PENDING_AUTHORIZATION' check (status in ('PENDING_AUTHORIZATION','ACTIVE','ERROR','REVOKED')),
  secret_ciphertext text,                     -- Fernet ciphertext; never returned by the API
  authorized_by uuid,
  authorized_at timestamptz,
  data_mode text not null default 'live' check (data_mode in ('simulated','upload','live')),
  last_sync_at timestamptz,
  last_error text,
  created_at timestamptz not null default now()
);

create table financial_accounts (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  connection_id uuid not null references financial_connections(id) on delete cascade,
  external_ref_hmac text not null,            -- keyed HMAC of the provider's account id; the number itself is never stored
  name text not null,
  mask text check (mask is null or length(mask) <= 8),
  account_type text not null,
  currency char(3) not null default 'USD',
  current_balance_minor bigint,
  available_balance_minor bigint,
  balance_as_of timestamptz,
  data_mode text not null check (data_mode in ('simulated','upload','live')),
  created_at timestamptz not null default now(),
  unique (organization_id, connection_id, external_ref_hmac)
);

create table financial_transactions (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  connection_id uuid not null references financial_connections(id) on delete cascade,
  account_id uuid references financial_accounts(id) on delete set null,
  dedupe_key text not null,
  external_id text,
  posted_at timestamptz not null,
  amount_minor bigint not null,               -- negative = money out
  currency char(3) not null default 'USD',
  description text not null,                  -- redacted on import
  merchant text,
  category_key text,
  kind text not null check (kind in ('revenue','expense','fee','refund','transfer','tax','payout','other')),
  is_fee smallint not null default 0,
  recurring smallint not null default 0,
  reconciliation_status text not null default 'UNRECONCILED' check (reconciliation_status in ('UNRECONCILED','MATCHED','NEEDS_REVIEW')),
  matched_type text,
  matched_id uuid,
  data_mode text not null check (data_mode in ('simulated','upload','live')),
  created_at timestamptz not null default now(),
  unique (organization_id, dedupe_key)
);
create index financial_transactions_org_posted_idx on financial_transactions (organization_id, posted_at);

create table revenue_sources (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  connection_id uuid references financial_connections(id) on delete set null,
  name text not null,
  platform text not null,
  data_mode text not null,
  created_at timestamptz not null default now(),
  unique (organization_id, platform, name)
);

create table invoices (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  direction text not null check (direction in ('receivable','payable')),
  counterparty text not null,
  amount_minor bigint not null,
  currency char(3) not null default 'USD',
  issued_at timestamptz,
  due_at timestamptz,
  status text not null default 'OPEN' check (status in ('OPEN','PAID','VOID')),
  document_sha256 text,
  document_path text,
  data_mode text not null,
  created_at timestamptz not null default now()
);

create table bills (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  payee text not null,
  amount_minor bigint not null,
  currency char(3) not null default 'USD',
  due_at timestamptz not null,
  recurrence text,
  autopay smallint not null default 0,
  status text not null default 'UPCOMING' check (status in ('UPCOMING','DUE','PAID','OVERDUE')),
  paid_transaction_id uuid,
  reminded_at timestamptz,
  data_mode text not null,
  created_at timestamptz not null default now()
);

create table subscriptions (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  vendor text not null,
  plan text,
  amount_minor bigint not null,
  currency char(3) not null default 'USD',
  interval text not null check (interval in ('month','year')),
  renews_at timestamptz,
  status text not null default 'ACTIVE',
  contract_terms text,
  category_key text,
  data_mode text not null,
  created_at timestamptz not null default now(),
  unique (organization_id, vendor, plan)
);

create table expense_categories (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  key text not null,
  name text not null,
  tax_treatment text not null check (tax_treatment in ('deductible','partially_deductible','not_deductible','not_expense')),
  tax_line text,
  unique (organization_id, key)
);

create table tax_documents (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  tax_year int not null,
  jurisdiction text not null,
  doc_type text not null,
  status text not null default 'MISSING' check (status in ('MISSING','RECEIVED','VERIFIED')),
  sha256 text,
  storage_path text,
  source text,
  note text,
  data_mode text not null,
  created_at timestamptz not null default now()
);

create table tax_estimates (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  tax_year int not null,
  jurisdiction text not null,
  period text not null,
  gross_revenue_minor bigint not null,
  deductible_expenses_minor bigint not null,
  net_profit_minor bigint not null,
  estimated_tax_minor bigint not null,
  reserve_minor bigint not null,
  assumptions jsonb not null default '{}',
  uncertainty jsonb not null default '[]',
  missing_evidence jsonb not null default '[]',
  data_mode text not null,
  created_at timestamptz not null default now()
);

create table cost_review_packets (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  origin text not null check (origin in ('purchase_request','fee_detected')),
  status text not null check (status in ('SUBMITTED','AT_BANK','RESEARCH_REQUESTED','RESEARCHING','FINDINGS_RETURNED',
    'GM_REVIEW','OWNER_DECISION','APPROVED','EXECUTED','REJECTED','DEFERRED','CLOSED')),
  requested_by_agent_id uuid references agents(id),
  request_mission_id uuid references missions(id),
  research_mission_id uuid references missions(id),
  analysis_mission_id uuid references missions(id),
  execution_mission_id uuid references missions(id),
  subject_type text,
  subject_id uuid,
  vendor text not null,
  item text not null,
  justification text,
  amount_minor bigint not null check (amount_minor >= 0),
  currency char(3) not null default 'USD',
  interval text not null check (interval in ('one_time','month','year')),
  classification text check (classification in ('recurring','one_time','optional','contractual','legally_required')),
  classification_reason text,
  annualized_minor bigint,
  significant smallint not null default 0,
  risk text check (risk in ('low','medium','high')),
  research_rounds int not null default 0,
  findings jsonb not null default '[]',
  recommendation jsonb not null default '{}',
  gm_decision jsonb not null default '{}',
  owner_note text,
  deferred_until timestamptz,
  data_mode text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table savings_opportunities (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  packet_id uuid not null references cost_review_packets(id) on delete cascade,
  title text not null,
  current_annual_minor bigint not null,
  proposed_annual_minor bigint not null,
  migration_cost_minor bigint not null default 0,
  first_year_saving_minor bigint not null,
  confidence text not null,
  alternative jsonb not null default '{}',
  status text not null default 'PROPOSED' check (status in ('PROPOSED','ACCEPTED','DECLINED')),
  data_mode text not null,
  created_at timestamptz not null default now()
);

create table financial_approvals (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  packet_id uuid references cost_review_packets(id),
  action_type text not null check (action_type in ('purchase','payment','transfer','official_submission','tax_filing',
    'financial_publication','banking_change')),
  amount_minor bigint not null check (amount_minor >= 0),
  currency char(3) not null,
  recipient text not null,
  account_ref text not null,
  details jsonb not null default '{}',
  payload_hash text not null,
  status text not null default 'REQUESTED' check (status in ('REQUESTED','APPROVED','REJECTED','DEFERRED','MORE_RESEARCH',
    'EXPIRED','INVALIDATED','EXECUTED')),
  requested_by_agent_id uuid references agents(id),
  expires_at timestamptz not null,
  decided_by uuid,
  decided_role text,
  decided_at timestamptz,
  step_up_method text,
  executed_at timestamptz,
  execution_ref text,
  execution_mode text,
  data_mode text not null,
  created_at timestamptz not null default now()
);
create index financial_approvals_packet_idx on financial_approvals (packet_id, created_at);

-- Tamper-evident: append-only (trigger below) and hash-chained (services/finance/audit.py verifies the chain).
create table financial_audit_events (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  seq bigint not null,
  actor_type text not null check (actor_type in ('owner','user','agent','system')),
  actor_id uuid,
  action text not null,
  subject_type text not null,
  subject_id uuid,
  detail jsonb not null default '{}',
  prev_hash text not null,
  hash text not null,
  created_at timestamptz not null default now(),
  unique (organization_id, seq)
);

create table financial_sync_runs (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  connection_id uuid not null references financial_connections(id) on delete cascade,
  status text not null check (status in ('RUNNING','COMPLETED','PARTIAL','FAILED')),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  fetched int not null default 0,
  inserted int not null default 0,
  duplicates int not null default 0,
  rejected int not null default 0,
  coverage jsonb not null default '{}',
  errors jsonb not null default '[]',
  data_mode text not null
);

create table financial_reports (               -- authoritative record behind REVENUE_REPORT / FINANCIAL_FORECAST packages
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  kind text not null check (kind in ('revenue_report','financial_forecast')),
  period_start timestamptz not null,
  period_end timestamptz not null,
  data jsonb not null default '{}',
  data_mode text not null,
  created_at timestamptz not null default now()
);

create table stepup_secrets (                 -- TOTP secrets for step-up authentication (Fernet-encrypted)
  user_id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  secret_ciphertext text not null,
  last_used_step bigint not null default 0,
  created_at timestamptz not null default now()
);

-- Physical packages can carry any authoritative record, not just opportunities.
alter table logistics_packages drop constraint if exists logistics_packages_package_type_check;
alter table logistics_packages add constraint logistics_packages_package_type_check check (package_type in
  ('research_brief','product_proposal','design_spec','code_artifact','test_report','revision_request','approval_request',
   'release_package','revenue_report','expense_alert','bill_reminder','fee_research_request','savings_recommendation',
   'purchase_request','payment_proposal','tax_review_package','financial_forecast','owner_approval_request'));
alter table logistics_packages add column subject_type text;
alter table logistics_packages add column subject_id uuid;
create index logistics_packages_subject_idx on logistics_packages (subject_id);
alter table logistics_packages add constraint logistics_packages_finance_subject_check check (
  package_type not in ('revenue_report','expense_alert','bill_reminder','fee_research_request','savings_recommendation',
                       'purchase_request','payment_proposal','tax_review_package','financial_forecast','owner_approval_request')
  or (subject_type is not null and subject_id is not null));

create trigger financial_audit_events_append_only before update or delete on financial_audit_events
  for each row execute function forbid_mutation();

-- ---------------------------------------------------------------- row level security: owners and admins only
create or replace function public.is_finance_member(org uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from memberships m where m.organization_id = org and m.user_id = auth.uid()
                 and m.role in ('owner','admin'));
$$;

do $$
declare t text;
begin
  foreach t in array array['financial_connections','financial_accounts','financial_transactions','revenue_sources','invoices',
    'bills','subscriptions','expense_categories','tax_documents','tax_estimates','cost_review_packets','savings_opportunities',
    'financial_approvals','financial_audit_events','financial_sync_runs','financial_reports']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('create policy %I on %I for select using (public.is_finance_member(organization_id))', t || '_finance_read', t);
  end loop;
end $$;
alter table stepup_secrets enable row level security;   -- no client policies: service role only
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'authenticated') then   -- Supabase client roles
    execute 'revoke all on financial_connections from anon, authenticated';
    execute 'grant select (id, organization_id, kind, provider, display_name, access_mode, scopes, status, authorized_by,
             authorized_at, data_mode, last_sync_at, last_error, created_at) on financial_connections to authenticated';  -- never the ciphertext
    execute 'revoke all on stepup_secrets from anon, authenticated';
  end if;
end $$;

