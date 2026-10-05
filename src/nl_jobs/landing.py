"""Write fetch results to the raw layer. Insert only, never update."""

from datetime import date

import psycopg
from psycopg.types.json import Jsonb

from nl_jobs.fetch_result import FetchResult
from nl_jobs.sources.iwwz_sponsors import SponsorExport, SponsorOutcome

INSERT_FETCH = """
    insert into raw.board_fetches
        (source, board_slug, run_date, fetched_at, request_url,
         outcome, http_status, job_count, payload, error)
    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    returning fetch_id
"""


def insert_fetch(conn: psycopg.Connection, result: FetchResult, run_date: date) -> int:
    """Insert one fetch attempt and return its fetch_id. The caller owns the transaction."""
    payload = Jsonb(result.payload) if result.payload is not None else None
    row = conn.execute(
        INSERT_FETCH,
        (
            result.source,
            result.board_slug,
            run_date,
            result.fetched_at,
            result.request_url,
            result.outcome.value,
            result.http_status,
            result.job_count,
            payload,
            result.error,
        ),
    ).fetchone()
    assert row is not None
    return row[0]


FIND_LANDED_EXPORT = """
    select fetch_id from raw.sponsor_export_fetches
    where outcome = 'ok' and generated_at = %s
"""

INSERT_SPONSOR_FETCH = """
    insert into raw.sponsor_export_fetches
        (run_date, fetched_at, request_url, outcome,
         http_status, schema_version, generated_at, sponsor_count, error)
    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    returning fetch_id
"""

# The whole array goes to Postgres once and is split into rows there. Each element is
# stored as it arrived: no flattening, no coercion, JSON null stays JSON null.
INSERT_SPONSOR_ROWS = """
    insert into raw.sponsor_export_rows
        (fetch_id, generated_at, schema_version, sponsor_id, payload)
    select %s, %s, %s, sponsor ->> 'id', sponsor
    from jsonb_array_elements(%s) as sponsor
"""


def insert_sponsor_export(conn: psycopg.Connection, export: SponsorExport, run_date: date) -> int:
    """Land one export attempt and return its fetch_id. The caller owns the transaction.

    A failed attempt lands only its fetch row. An accepted export also lands one row per
    sponsor. Landing the same export (same generatedAt) again changes nothing and returns
    the existing fetch_id; a later export with a newer generatedAt is a new snapshot.
    """
    accepted = export.outcome is SponsorOutcome.OK
    if accepted:
        landed = conn.execute(FIND_LANDED_EXPORT, (export.generated_at,)).fetchone()
        if landed:
            return landed[0]

    row = conn.execute(
        INSERT_SPONSOR_FETCH,
        (
            run_date,
            export.fetched_at,
            export.request_url,
            export.outcome.value,
            export.http_status,
            export.schema_version,
            export.generated_at,
            export.sponsor_count,
            export.error,
        ),
    ).fetchone()
    assert row is not None
    fetch_id = row[0]

    if accepted:
        inserted = conn.execute(
            INSERT_SPONSOR_ROWS,
            (fetch_id, export.generated_at, export.schema_version, Jsonb(export.sponsors)),
        ).rowcount
        if inserted != export.sponsor_count:
            raise RuntimeError(
                f"landed {inserted} sponsor rows, expected {export.sponsor_count}; rolling back"
            )
    return fetch_id
