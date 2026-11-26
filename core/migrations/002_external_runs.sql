-- Runs Omni did not start but records: Hermes cron sessions, imported by `omni hermes-sync`.
-- fired_by says who started the run; external_id is the source's own id, so a re-import is a no-op.
alter table core.runs add column if not exists fired_by text not null default 'omni';
alter table core.runs add column if not exists external_id text;
create unique index if not exists runs_external_id on core.runs (external_id) where external_id is not null;
