"""Write fetch results to the raw layer. Insert only, never update."""

from datetime import date

import psycopg
from psycopg.types.json import Jsonb

from nl_jobs.fetch_result import FetchResult

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
