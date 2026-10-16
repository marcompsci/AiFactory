-- V6 playable town: the owner's pixel-art avatar and position, conversations with agent NPCs, and proposals.
-- A proposal is a structured action (create a mission, start research, cancel a mission) that an NPC offers after the
-- owner asks for something. It runs only when the owner taps Confirm; walking away or closing the game never confirms it.

create table play_players (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  user_id uuid not null,
  data jsonb not null default '{}',
  updated_at timestamptz not null default now(),
  unique (organization_id, user_id)
);

create table play_messages (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  user_id uuid not null,
  agent_id uuid not null,
  speaker text not null check (speaker in ('owner','npc')),
  text text not null check (length(text) between 1 and 8000),
  proposal_id uuid,
  created_at timestamptz not null default now()
);
create index play_messages_thread_idx on play_messages (organization_id, user_id, agent_id, created_at);

create table play_proposals (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  user_id uuid not null,
  agent_id uuid not null,
  kind text not null check (kind in ('create_mission','start_research','cancel_mission')),
  params jsonb not null default '{}',
  summary text not null,
  status text not null default 'PENDING' check (status in ('PENDING','CONFIRMED','DECLINED','EXPIRED','FAILED')),
  result jsonb,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  decided_at timestamptz
);
create index play_proposals_user_idx on play_proposals (organization_id, user_id, status);

-- Each person sees only their own avatar, conversations and proposals.
alter table play_players enable row level security;
create policy play_players_self on play_players for select using (user_id = auth.uid());
alter table play_messages enable row level security;
create policy play_messages_self on play_messages for select using (user_id = auth.uid());
alter table play_proposals enable row level security;
create policy play_proposals_self on play_proposals for select using (user_id = auth.uid());
