-- The run ledger: one row per `omni run`, whatever the harness.
create schema if not exists core;

create table if not exists core.runs (
    id            bigserial primary key,
    job           text        not null,
    domain        text        not null,
    harness       text        not null,
    model         text,
    status        text        not null check (status in ('running', 'ok', 'failed', 'timeout', 'refused')),
    reason        text,                    -- why a run was refused or failed
    started_at    timestamptz not null default now(),
    ended_at      timestamptz,
    exit_code     integer,
    cost_usd      numeric(12, 6),          -- null = unknown, never a guessed zero
    cost_source   text,                    -- where cost_usd came from: none | hermes_usage_file | opencode_events | unknown
    tokens_in     bigint,
    tokens_out    bigint,
    log_path      text,
    registry_sha  text        not null,
    host          text        not null
);

create index if not exists runs_job_started on core.runs (job, started_at desc);
create index if not exists runs_started on core.runs (started_at desc);
