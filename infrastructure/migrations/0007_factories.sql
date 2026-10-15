-- Claude Code and GitHub factories: read-only views of the owner's Claude Code sessions/memory (on the machine
-- running the API) and of authorized GitHub repositories. Opt-in per source; owner/admin read only.
create table factory_links (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  kind text not null check (kind in ('claude_code','github')),
  enabled smallint not null default 0,
  created_by uuid,
  updated_at timestamptz not null default now(),
  unique (organization_id, kind)
);

create table factory_snapshots (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  kind text not null check (kind in ('claude_code','github')),
  data jsonb not null default '{}',
  mission_id uuid references missions(id),
  synced_at timestamptz not null default now()
);
create index factory_snapshots_kind_idx on factory_snapshots (organization_id, kind, synced_at desc);

do $$
declare t text;
begin
  foreach t in array array['factory_links','factory_snapshots']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('create policy %I on %I for select using (public.is_finance_member(organization_id))', t || '_owner_read', t);
  end loop;
end $$;
