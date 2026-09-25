"""Raw landing against a real Postgres. Each test runs in a transaction that is rolled back."""

from datetime import UTC, date, datetime

import psycopg
import pytest

from nl_jobs.fetch_result import FetchResult, Outcome
from nl_jobs.landing import insert_fetch
from nl_jobs.migrate import apply_migrations

pytestmark = pytest.mark.integration

RUN_DATE = date(2026, 9, 25)


def fetch(outcome, **fields):
    return FetchResult(
        source="greenhouse",
        board_slug="catawiki",
        request_url="https://boards-api.greenhouse.io/v1/boards/catawiki/jobs?content=true",
        fetched_at=datetime(2026, 9, 25, 6, 0, tzinfo=UTC),
        outcome=outcome,
        **fields,
    )


def test_ok_fetch_lands_payload_as_jsonb(db_conn):
    payload = {"jobs": [{"id": 1, "title": "Backend Engineer"}], "meta": {"total": 1}}

    fetch_id = insert_fetch(
        db_conn, fetch(Outcome.OK, http_status=200, job_count=1, payload=payload), RUN_DATE
    )

    row = db_conn.execute(
        "select outcome, job_count, payload, run_date from raw.board_fetches where fetch_id = %s",
        (fetch_id,),
    ).fetchone()
    assert row == ("ok", 1, payload, RUN_DATE)


def test_not_found_lands_with_nulls_not_zeros(db_conn):
    fetch_id = insert_fetch(db_conn, fetch(Outcome.NOT_FOUND, http_status=404), RUN_DATE)

    row = db_conn.execute(
        "select job_count, payload from raw.board_fetches where fetch_id = %s", (fetch_id,)
    ).fetchone()
    assert row == (None, None)


def test_rerun_appends_a_second_attempt(db_conn):
    first = insert_fetch(db_conn, fetch(Outcome.FAILED, error="ReadTimeout: slow"), RUN_DATE)
    second = insert_fetch(
        db_conn, fetch(Outcome.EMPTY, http_status=200, job_count=0, payload={"jobs": []}), RUN_DATE
    )

    assert second > first


def test_raw_rows_cannot_be_updated(db_conn):
    fetch_id = insert_fetch(db_conn, fetch(Outcome.NOT_FOUND, http_status=404), RUN_DATE)

    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db_conn.execute("update raw.board_fetches set error = 'x' where fetch_id = %s", (fetch_id,))


def test_inconsistent_outcome_is_rejected(db_conn):
    # "ok" without a payload would silently read as "zero jobs" downstream.
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_fetch(db_conn, fetch(Outcome.OK, http_status=200), RUN_DATE)


def test_migrations_are_applied_once(db_conn):
    assert apply_migrations(db_conn) == []
