-- chopstr · Migration 0004 · Clips dürfen den Status 'deleted' tragen (Lösch-Workflow, Phase 4)

alter table clips drop constraint if exists clips_status_check;
alter table clips
  add constraint clips_status_check
  check (status in ('draft', 'approved', 'rendering', 'rendered', 'exported', 'failed', 'deleted'));

alter table clips add column if not exists deleted_at timestamptz;

insert into schema_migrations(version) values ('0004_clip_deleted_status') on conflict do nothing;
