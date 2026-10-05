-- Raw landing for the iwwz sponsor export. Two tables, both append-only:
--   sponsor_export_fetches  one row per fetch attempt, whatever its outcome
--   sponsor_export_rows     one row per sponsor per successful export, payload as received
-- Every successful fetch is a full snapshot of the register, keyed by the server's
-- generatedAt, so "who was a sponsor on date X" stays answerable.

create table raw.sponsor_export_fetches (
    fetch_id        bigint generated always as identity primary key,
    run_date        date        not null,  -- the day this run is for
    fetched_at      timestamptz not null,  -- when the response (or the failure) arrived
    request_url     text        not null,
    outcome         text        not null
        check (outcome in (
            'ok', 'empty', 'unreachable', 'unauthorized', 'rate_limited', 'server_error',
            'unexpected_status', 'invalid_json', 'unsupported_schema_version',
            'invalid_envelope', 'count_mismatch'
        )),
    http_status     integer,               -- null when no response arrived at all
    schema_version  integer,               -- null when the body never got that far
    generated_at    timestamptz,           -- the envelope's generatedAt
    sponsor_count   integer,               -- null unless the export was accepted
    error           text,

    constraint ok_is_complete check (
        (outcome = 'ok') = (sponsor_count is not null)
        and (outcome <> 'ok' or (
            http_status = 200 and schema_version = 1 and generated_at is not null
            and sponsor_count > 0 and error is null
        ))
    ),
    constraint not_ok_has_error check (outcome = 'ok' or error is not null),
    constraint unreachable_has_no_status check (outcome <> 'unreachable' or http_status is null)
);

-- One accepted export per generatedAt: landing the same response twice is a no-op.
create unique index sponsor_export_fetches_ok_generated_at
    on raw.sponsor_export_fetches (generated_at) where outcome = 'ok';
create index sponsor_export_fetches_run_date on raw.sponsor_export_fetches (run_date);

create table raw.sponsor_export_rows (
    fetch_id        bigint      not null references raw.sponsor_export_fetches (fetch_id),
    generated_at    timestamptz not null,
    schema_version  integer     not null,
    ingested_at     timestamptz not null default now(),
    sponsor_id      text        not null,  -- the row's "id": opaque text, not a number
    payload         jsonb       not null,  -- the sponsor object exactly as sent, nulls included
    primary key (generated_at, sponsor_id)
);

create index sponsor_export_rows_fetch on raw.sponsor_export_rows (fetch_id);

create trigger sponsor_export_fetches_no_update_delete
    before update or delete on raw.sponsor_export_fetches
    for each row execute function raw.forbid_mutation();
create trigger sponsor_export_fetches_no_truncate
    before truncate on raw.sponsor_export_fetches
    for each statement execute function raw.forbid_mutation();

create trigger sponsor_export_rows_no_update_delete
    before update or delete on raw.sponsor_export_rows
    for each row execute function raw.forbid_mutation();
create trigger sponsor_export_rows_no_truncate
    before truncate on raw.sponsor_export_rows
    for each statement execute function raw.forbid_mutation();
