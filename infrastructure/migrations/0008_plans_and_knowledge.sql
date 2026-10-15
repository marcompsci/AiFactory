-- Plans: agents run on the owner's Codex plan first and the Claude plan when Codex runs out (services/model_gateway/plans.py).
-- Codex Factory joins the factories. Company knowledge base for Phoronomics and Phoronomic Studios: docs and skills the
-- agents pull from; owner/admin write, members read.
alter table factory_links drop constraint if exists factory_links_kind_check;
alter table factory_links add constraint factory_links_kind_check check (kind in ('claude_code','github','codex'));
alter table factory_snapshots drop constraint if exists factory_snapshots_kind_check;
alter table factory_snapshots add constraint factory_snapshots_kind_check check (kind in ('claude_code','github','codex','plan_usage'));

create table plan_settings (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  data jsonb not null default '{}',
  updated_by uuid,
  updated_at timestamptz not null default now(),
  unique (organization_id)
);

create table kb_documents (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  company text not null check (company in ('phoronomics','phoronomic_studios','shared')),
  kind text not null check (kind in ('doc','skill')),
  slug text not null check (slug ~ '^[a-z0-9][a-z0-9-]{0,79}$'),
  title text not null check (length(title) between 1 and 160),
  description text not null default '',
  body text not null default '' check (length(body) <= 400000),
  tags jsonb not null default '[]',
  source text not null default 'editor' check (source in ('editor','upload','import')),
  content_sha256 text not null,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, slug)
);
create index kb_documents_company_idx on kb_documents (organization_id, company, kind);

alter table plan_settings enable row level security;
create policy plan_settings_owner_read on plan_settings for select using (public.is_finance_member(organization_id));
alter table kb_documents enable row level security;
create policy kb_documents_member_read on kb_documents for select using (public.is_member(organization_id));
