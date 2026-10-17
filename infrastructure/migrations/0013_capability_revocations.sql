-- V6.8 least privilege: a tool the owner revoked from an agent stays revoked across restarts until the owner restores it.
create table capability_revocations (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  agent_id uuid not null references agents(id) on delete cascade,
  tool_name text not null,
  reason text not null default '',
  revoked_by uuid not null,
  revoked_at timestamptz not null default now(),
  restored_by uuid,
  restored_at timestamptz
);
create unique index capability_revocations_active on capability_revocations (agent_id, tool_name) where restored_at is null;
alter table capability_revocations enable row level security;
create policy capability_revocations_member_read on capability_revocations for select using (public.is_member(organization_id));
