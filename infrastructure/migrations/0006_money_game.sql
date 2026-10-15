-- The money game: agents compete on verified money only (realized savings, avoided costs the owner confirmed by
-- decision, and revenue the owner explicitly linked to a product the agents built). Scores are append-only.

create table game_seasons (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  key text not null check (key ~ '^[0-9]{4}-[0-9]{2}$'),
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  created_at timestamptz not null default now(),
  unique (organization_id, key)
);

create table game_scores (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  season_id uuid not null references game_seasons(id) on delete cascade,
  agent_id uuid not null references agents(id),
  kind text not null check (kind in ('realized_savings','avoided_cost','attributed_revenue')),
  amount_minor bigint not null check (amount_minor >= 0),
  currency char(3) not null,
  share double precision not null check (share > 0 and share <= 1),
  source_type text not null check (source_type in ('financial_approval','savings_investigation','financial_transaction')),
  source_id uuid not null,
  evidence jsonb not null default '{}',
  data_mode text not null check (data_mode in ('live','simulated')),
  created_at timestamptz not null default now(),
  unique (organization_id, source_type, source_id, agent_id)
);
create index game_scores_season_idx on game_scores (season_id);
create index game_scores_agent_idx on game_scores (agent_id);
create trigger game_scores_append_only before update or delete on game_scores
  for each row execute function forbid_mutation();

create table revenue_links (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  merchant text not null,
  opportunity_id uuid not null references opportunities(id),
  created_by uuid not null,
  active smallint not null default 1,
  created_at timestamptz not null default now()
);

do $$
declare t text;
begin
  foreach t in array array['game_seasons','game_scores','revenue_links']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('create policy %I on %I for select using (public.is_finance_member(organization_id))', t || '_finance_read', t);
  end loop;
end $$;
