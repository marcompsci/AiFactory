-- V6.1 reliability: a completed mission gets an objective check (services/management/reliability.py), stored as a goal
-- checkpoint. Met, partly met (a step skipped by the owner's decision) or not met, next to the existing drift statuses.

alter table goal_checkpoints drop constraint if exists goal_checkpoints_status_check;
alter table goal_checkpoints add constraint goal_checkpoints_status_check
  check (status in ('on_track','drift','blocked','stalled','objective_met','objective_partly_met','objective_not_met'));

-- lessons are read per agent, newest first
create index if not exists memory_entries_agent_created on memory_entries (agent_id, created_at desc);
