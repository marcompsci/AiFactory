-- V6.88–V6.97: links on tasks, and more ways to repeat (every 2 weeks, monthly, the last day of the month, yearly,
-- every N days).
alter table my_tasks drop constraint if exists my_tasks_repeat_check;
alter table my_tasks add constraint my_tasks_repeat_check check (repeat ~ '^(none|daily|weekdays|weekly|biweekly|monthly|monthly:(29|30)|monthly_last|yearly|days:([2-9]|[1-9][0-9]|[12][0-9][0-9]|3[0-5][0-9]|36[0-5]))$');

create table task_links (
  id uuid primary key,
  task_id uuid not null references my_tasks(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  url text not null check (char_length(url) between 10 and 2048 and url ~ '^https?://'),
  title text not null default '' check (char_length(title) <= 120),
  created_by uuid not null,
  created_at timestamptz not null default now()
);
create index task_links_task on task_links (task_id, created_at);

alter table task_links enable row level security;
create policy task_links_read on task_links for select using (public.is_member(organization_id));
