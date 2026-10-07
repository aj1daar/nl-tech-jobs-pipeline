-- Raw landing table: one row per fetch attempt of one ATS board.
-- Append-only. Reruns add rows; staging picks the attempt that counts for each run_date.

create schema if not exists raw;

create table raw.board_fetches (
    fetch_id     bigint generated always as identity primary key,
    source       text        not null,
    board_slug   text        not null,
    run_date     date        not null,  -- the day this run is for (Airflow logical date)
    fetched_at   timestamptz not null,  -- when the response arrived
    request_url  text        not null,
    outcome      text        not null
        check (outcome in ('ok', 'empty', 'not_found', 'failed')),
    http_status  integer,               -- null when no response arrived at all
    job_count    integer,               -- null unless the board answered with a jobs list
    payload      jsonb,                 -- the full response body, untouched
    error        text,

    -- Encode the failure modes so a bug cannot land an inconsistent row.
    constraint answered_has_payload
        check ((outcome in ('ok', 'empty')) = (payload is not null and job_count is not null)),
    constraint ok_has_jobs    check (outcome <> 'ok'    or job_count > 0),
    constraint empty_has_none check (outcome <> 'empty' or job_count = 0),
    constraint not_found_is_404 check (outcome <> 'not_found' or http_status = 404),
    constraint failed_has_error check (outcome <> 'failed' or error is not null)
);

create index board_fetches_board_day on raw.board_fetches (source, board_slug, run_date);

-- Enforce immutability in the database, not only by convention.
create function raw.forbid_mutation() returns trigger
language plpgsql as $$
begin
    raise exception 'raw tables are append-only: % on %.% is not allowed',
        tg_op, tg_table_schema, tg_table_name;
end;
$$;

create trigger board_fetches_no_update_delete
    before update or delete on raw.board_fetches
    for each row execute function raw.forbid_mutation();

create trigger board_fetches_no_truncate
    before truncate on raw.board_fetches
    for each statement execute function raw.forbid_mutation();
