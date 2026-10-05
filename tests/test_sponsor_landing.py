"""Sponsor export landing against a real Postgres. Each test is rolled back."""

from datetime import UTC, date, datetime, timedelta

import psycopg
import pytest

from nl_jobs.landing import insert_sponsor_export
from nl_jobs.sources.iwwz_sponsors import SponsorExport, SponsorOutcome

pytestmark = pytest.mark.integration

RUN_DATE = date(2026, 10, 5)
GENERATED_AT = datetime(2026, 10, 5, 9, 22, 33, 123456, tzinfo=UTC)

ALL_NULLS = {
    "id": "0f8fad5bd9cb469fa16570867728950e",
    "name": "Unknown Everything",
    "kvkNumber": None,
    "isIndRecognizedSponsor": None,
    "removedAt": None,
    "mergedIntoId": None,
    "aliasNames": None,
    "techStackTags": None,
    "enrichmentVersion": None,
}
NOT_A_SPONSOR = {"id": "01031782", "name": "Essity", "isIndRecognizedSponsor": False}
SPONSORS = [ALL_NULLS, NOT_A_SPONSOR]


def export(outcome=SponsorOutcome.OK, generated_at=GENERATED_AT, **fields):
    if outcome is SponsorOutcome.OK:
        defaults = {
            "http_status": 200,
            "schema_version": 1,
            "generated_at": generated_at,
            "sponsor_count": len(SPONSORS),
            "sponsors": SPONSORS,
        }
        fields = defaults | fields
    return SponsorExport(
        request_url="https://iwwz.test/api/export/sponsors",
        fetched_at=datetime(2026, 10, 5, 9, 22, 34, tzinfo=UTC),
        outcome=outcome,
        **fields,
    )


def row_count(conn):
    return conn.execute("select count(*) from raw.sponsor_export_rows").fetchone()[0]


def fetch_count(conn):
    return conn.execute("select count(*) from raw.sponsor_export_fetches").fetchone()[0]


def test_accepted_export_lands_one_row_per_sponsor_as_sent(db_conn):
    before = row_count(db_conn)

    fetch_id = insert_sponsor_export(db_conn, export(), RUN_DATE)

    rows = db_conn.execute(
        "select sponsor_id, payload, generated_at, schema_version"
        " from raw.sponsor_export_rows where fetch_id = %s order by sponsor_id",
        (fetch_id,),
    ).fetchall()
    assert row_count(db_conn) == before + 2
    assert [r[1] for r in rows] == [NOT_A_SPONSOR, ALL_NULLS]
    assert all(r[2:] == (GENERATED_AT, 1) for r in rows)


def test_null_stays_null_and_false_stays_false(db_conn):
    fetch_id = insert_sponsor_export(db_conn, export(), RUN_DATE)

    flags = db_conn.execute(
        """
        select sponsor_id,
               payload ->> 'kvkNumber',
               payload -> 'isIndRecognizedSponsor',
               jsonb_typeof(payload -> 'aliasNames')
        from raw.sponsor_export_rows where fetch_id = %s order by sponsor_id
        """,
        (fetch_id,),
    ).fetchall()

    # Unknown is JSON null: not "", not false, not []. And a real false is kept as false.
    assert flags == [
        (NOT_A_SPONSOR["id"], None, False, None),
        (ALL_NULLS["id"], None, None, "null"),
    ]


def test_landing_the_same_export_twice_changes_nothing(db_conn):
    first = insert_sponsor_export(db_conn, export(), RUN_DATE)
    rows, fetches = row_count(db_conn), fetch_count(db_conn)

    second = insert_sponsor_export(db_conn, export(), RUN_DATE)

    assert second == first
    assert (row_count(db_conn), fetch_count(db_conn)) == (rows, fetches)


def test_newer_export_on_the_same_day_is_a_new_snapshot(db_conn):
    first = insert_sponsor_export(db_conn, export(), RUN_DATE)
    rows = row_count(db_conn)

    later = export(generated_at=GENERATED_AT + timedelta(hours=3))
    second = insert_sponsor_export(db_conn, later, RUN_DATE)

    assert second != first
    assert row_count(db_conn) == rows + 2


@pytest.mark.parametrize(
    ("outcome", "fields"),
    [
        (SponsorOutcome.UNREACHABLE, {"error": "ConnectError: no route"}),
        (SponsorOutcome.UNAUTHORIZED, {"http_status": 401, "error": "401"}),
        (SponsorOutcome.RATE_LIMITED, {"http_status": 429, "error": "429"}),
        (SponsorOutcome.SERVER_ERROR, {"http_status": 503, "error": "down"}),
        (SponsorOutcome.INVALID_JSON, {"http_status": 200, "error": "invalid JSON"}),
        (
            SponsorOutcome.UNSUPPORTED_SCHEMA_VERSION,
            {"http_status": 200, "schema_version": 2, "error": "schemaVersion is 2"},
        ),
        (
            SponsorOutcome.COUNT_MISMATCH,
            {"http_status": 200, "schema_version": 1, "generated_at": GENERATED_AT, "error": "x"},
        ),
    ],
)
def test_failed_attempt_lands_its_outcome_and_no_sponsor_rows(db_conn, outcome, fields):
    rows = row_count(db_conn)

    fetch_id = insert_sponsor_export(db_conn, export(outcome, **fields), RUN_DATE)

    landed = db_conn.execute(
        "select outcome, sponsor_count from raw.sponsor_export_fetches where fetch_id = %s",
        (fetch_id,),
    ).fetchone()
    assert landed == (outcome.value, None)
    assert row_count(db_conn) == rows


def test_row_count_that_differs_from_the_envelope_is_refused(db_conn):
    with pytest.raises(RuntimeError, match="expected 3"):
        insert_sponsor_export(db_conn, export(sponsor_count=3), RUN_DATE)


def test_sponsor_rows_cannot_be_updated_or_deleted(db_conn):
    fetch_id = insert_sponsor_export(db_conn, export(), RUN_DATE)

    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db_conn.execute("delete from raw.sponsor_export_rows where fetch_id = %s", (fetch_id,))


def test_failure_without_an_error_is_rejected(db_conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_sponsor_export(db_conn, export(SponsorOutcome.UNAUTHORIZED), RUN_DATE)
