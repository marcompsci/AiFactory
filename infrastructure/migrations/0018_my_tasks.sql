-- V6.43 the owner's task list: tasks the factory can work on, each linked to the mission doing it.
create table my_tasks (
  id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  title text not null check (char_length(title) between 2 and 160),
  notes text not null default '',
  kind text not null default 'personal' check (kind in ('code','research','write','personal')),
  priority text not null default 'normal' check (priority in ('urgent','normal','low')),
  status text not null default 'OPEN' check (status in ('OPEN','DONE','DROPPED')),
  due_at timestamptz,
  repeat text not null default 'none' check (repeat in ('none','daily','weekdays','weekly')),
  budget_usd numeric check (budget_usd is null or (budget_usd > 0 and budget_usd <= 50)),
  repository_id uuid references repositories(id) on delete set null,
  mission_id uuid references missions(id) on delete set null,
  runs integer not null default 0,
  starting_at timestamptz,
  repeat_of uuid unique references my_tasks(id) on delete set null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  done_at timestamptz
);
create index my_tasks_org_status on my_tasks (organization_id, status, due_at);

alter table play_proposals drop constraint if exists play_proposals_kind_check;
alter table play_proposals add constraint play_proposals_kind_check
  check (kind in ('create_mission','start_research','cancel_mission','create_schedule','rerun_mission','start_saved','add_task','do_task'));

alter table my_tasks enable row level security;
create policy my_tasks_member_read on my_tasks for select using (public.is_member(organization_id));
