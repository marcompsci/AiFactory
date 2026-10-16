-- A recovery plan with nothing safe to run (two recoveries already failed, or the failure matched no rule) is kept as
-- INFO: a note for the owner, never something that can be approved.
alter table recovery_plans drop constraint if exists recovery_plans_status_check;
alter table recovery_plans add constraint recovery_plans_status_check
  check (status in ('PENDING','APPROVED','DECLINED','EXPIRED','SUPERSEDED','INFO'));
