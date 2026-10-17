-- V6.9 tamper-evident log: every event is linked to the previous one with SHA-256 (services/core/audit.py).
-- Editing, deleting or reordering an event breaks the chain from that point on; the chain itself is append-only.
create table event_chain (
  organization_id uuid not null references organizations(id) on delete cascade,
  sequence bigint not null,
  event_id uuid not null,
  prev_hash text not null check (length(prev_hash) = 64),
  hash text not null check (length(hash) = 64),
  created_at timestamptz not null default now(),
  primary key (organization_id, sequence)
);
create trigger event_chain_append_only before update or delete on event_chain
  for each row execute function forbid_mutation();
alter table event_chain enable row level security;
create policy event_chain_member_read on event_chain for select using (public.is_member(organization_id));
