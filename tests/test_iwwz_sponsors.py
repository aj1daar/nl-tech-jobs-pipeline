"""Sponsor export client. No network: httpx.MockTransport answers.

The envelopes here are built inline and are deliberately synthetic: they test how the
client reacts to each kind of answer. The one test against real data is
test_recorded_export_is_accepted, which waits for a fixture cut from the live export.
"""

import json
import logging

import brotli
import httpx
import pytest

from nl_jobs.config import IwwzSettings
from nl_jobs.http_client import make_client
from nl_jobs.sources.iwwz_sponsors import SponsorOutcome, fetch_export
from tests.helpers import FIXTURES

API_KEY = "test-key-3f9c1e7a-never-a-real-one"
SETTINGS = IwwzSettings(export_url="https://iwwz.test/api/export/sponsors", api_key=API_KEY)
RECORDED = FIXTURES / "iwwz" / "sponsors_export.json"

ACTIVE = {"id": "01031782", "name": "Essity", "kvkNumber": "01031782", "removedAt": None}
REMOVED = {"id": "02045678", "name": "Gone BV", "removedAt": "2026-08-01T00:00:00+00:00"}


def envelope(*sponsors, **overrides):
    body = {
        "schemaVersion": 1,
        "generatedAt": "2026-10-05T09:22:33.123456+00:00",
        "count": len(sponsors),
        "sponsors": list(sponsors),
    }
    return body | overrides


def ok_response(body):
    return httpx.Response(200, json=body)


def client_answering(*answers):
    """A client that replays answers in order. An exception instance is raised instead."""
    remaining = list(answers)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = remaining.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    return make_client(transport=httpx.MockTransport(handler)), seen


class Sleeps(list):
    def __call__(self, seconds):
        self.append(seconds)


def test_valid_export_is_ok_and_rows_are_untouched():
    client, seen = client_answering(ok_response(envelope(ACTIVE, REMOVED)))

    export = fetch_export(client, SETTINGS, sleep=Sleeps())

    assert export.outcome is SponsorOutcome.OK
    assert export.sponsors == [ACTIVE, REMOVED]
    assert export.sponsor_count == 2
    assert export.schema_version == 1
    assert export.generated_at.isoformat() == "2026-10-05T09:22:33.123456+00:00"
    assert export.error is None
    assert seen[0].headers["X-Api-Key"] == API_KEY
    assert "br" in seen[0].headers["Accept-Encoding"]


def test_brotli_body_is_decoded():
    body = brotli.compress(json.dumps(envelope(ACTIVE)).encode())
    client, _ = client_answering(
        httpx.Response(200, content=body, headers={"Content-Encoding": "br"})
    )

    assert fetch_export(client, SETTINGS, sleep=Sleeps()).outcome is SponsorOutcome.OK


def test_401_is_unauthorized_and_not_retried():
    sleeps = Sleeps()
    client, seen = client_answering(httpx.Response(401))

    export = fetch_export(client, SETTINGS, sleep=sleeps)

    assert export.outcome is SponsorOutcome.UNAUTHORIZED
    assert (len(seen), sleeps) == (1, [])
    assert export.sponsors is None


def test_429_is_rate_limited_and_not_retried():
    sleeps = Sleeps()
    client, seen = client_answering(httpx.Response(429, headers={"Retry-After": "1800"}))

    export = fetch_export(client, SETTINGS, sleep=sleeps)

    assert export.outcome is SponsorOutcome.RATE_LIMITED
    assert (len(seen), sleeps) == (1, [])
    assert "1800" in export.error


def test_5xx_is_retried_then_server_error():
    sleeps = Sleeps()
    client, seen = client_answering(*(httpx.Response(503, text="down") for _ in range(3)))

    export = fetch_export(client, SETTINGS, sleep=sleeps)

    assert export.outcome is SponsorOutcome.SERVER_ERROR
    assert export.http_status == 503
    assert (len(seen), sleeps) == (3, [1.0, 2.0])


def test_5xx_then_success_is_ok():
    client, _ = client_answering(httpx.Response(502), ok_response(envelope(ACTIVE)))

    assert fetch_export(client, SETTINGS, sleep=Sleeps()).outcome is SponsorOutcome.OK


def test_no_response_is_unreachable_with_no_status():
    error = httpx.ConnectError("name resolution failed")
    client, _ = client_answering(error, error, error)

    export = fetch_export(client, SETTINGS, sleep=Sleeps())

    assert export.outcome is SponsorOutcome.UNREACHABLE
    assert export.http_status is None


def test_other_status_is_unexpected_status():
    # For example a WAF challenge, or the route not being deployed.
    client, _ = client_answering(httpx.Response(403, text="<html>Just a moment...</html>"))

    export = fetch_export(client, SETTINGS, sleep=Sleeps())

    assert export.outcome is SponsorOutcome.UNEXPECTED_STATUS
    assert export.http_status == 403


def test_200_that_is_not_json_is_invalid_json():
    client, _ = client_answering(httpx.Response(200, text="<html>challenge</html>"))

    assert fetch_export(client, SETTINGS, sleep=Sleeps()).outcome is SponsorOutcome.INVALID_JSON


@pytest.mark.parametrize("version", [2, 0, "1", True, None])
def test_any_other_schema_version_is_refused_without_parsing(version):
    client, _ = client_answering(ok_response(envelope(ACTIVE, schemaVersion=version)))

    export = fetch_export(client, SETTINGS, sleep=Sleeps())

    assert export.outcome is SponsorOutcome.UNSUPPORTED_SCHEMA_VERSION
    assert export.sponsors is None
    assert export.sponsor_count is None


def test_count_that_disagrees_with_rows_is_count_mismatch():
    client, _ = client_answering(ok_response(envelope(ACTIVE, count=12797)))

    export = fetch_export(client, SETTINGS, sleep=Sleeps())

    assert export.outcome is SponsorOutcome.COUNT_MISMATCH
    assert export.sponsors is None
    assert "12797" in export.error


@pytest.mark.parametrize(
    "body",
    [
        [],
        envelope(ACTIVE, sponsors={"not": "a list"}),
        envelope(ACTIVE, generatedAt="yesterday"),
        envelope(ACTIVE, generatedAt="2026-10-05T09:22:33"),
        envelope(ACTIVE, count="1"),
        envelope({"name": "no id"}),
        envelope({"id": 1031782, "name": "numeric id"}),
        envelope(ACTIVE, ACTIVE),
    ],
)
def test_wrong_shape_is_invalid_envelope(body):
    client, _ = client_answering(ok_response(body))

    export = fetch_export(client, SETTINGS, sleep=Sleeps())

    assert export.outcome is SponsorOutcome.INVALID_ENVELOPE
    assert export.sponsors is None


def test_zero_sponsors_is_empty_not_ok():
    client, _ = client_answering(ok_response(envelope()))

    export = fetch_export(client, SETTINGS, sleep=Sleeps())

    assert export.outcome is SponsorOutcome.EMPTY
    assert export.sponsor_count is None


def test_nulls_reach_the_caller_as_none():
    row = {"id": "x1", "kvkNumber": None, "aliasNames": None, "isIndRecognizedSponsor": None}
    client, _ = client_answering(ok_response(envelope(row)))

    [sponsor] = fetch_export(client, SETTINGS, sleep=Sleeps()).sponsors

    assert sponsor["kvkNumber"] is None
    assert sponsor["aliasNames"] is None
    assert sponsor["isIndRecognizedSponsor"] is None


ANSWERS_THAT_MUST_NOT_LEAK = {
    "ok": [ok_response(envelope(ACTIVE))],
    "unauthorized": [httpx.Response(401)],
    "rate_limited": [httpx.Response(429)],
    # A server or proxy that echoes the request back, key included.
    "server_error": [httpx.Response(500, text=f"X-Api-Key: {API_KEY}")] * 3,
    "unexpected_status": [httpx.Response(403, text=f"denied for key {API_KEY}")],
    "invalid_json": [httpx.Response(200, text=f"<html>{API_KEY}</html>")],
    "unreachable": [httpx.ConnectError(f"proxy said: bad header {API_KEY}")] * 3,
}


@pytest.mark.parametrize("answers", ANSWERS_THAT_MUST_NOT_LEAK.values(), ids=list)
def test_key_never_reaches_logs_results_or_errors(answers, caplog):
    caplog.set_level(logging.DEBUG)
    client, _ = client_answering(*answers)

    export = fetch_export(client, SETTINGS, sleep=Sleeps())

    assert API_KEY not in caplog.text
    assert API_KEY not in repr(export)
    assert API_KEY not in (export.error or "")
    assert API_KEY not in repr(SETTINGS)


def test_recorded_export_is_accepted():
    # Seven rows cut from the live export on 2026-10-07; count was adjusted to match.
    client, _ = client_answering(httpx.Response(200, content=RECORDED.read_bytes()))

    export = fetch_export(client, SETTINGS, sleep=Sleeps())

    assert export.outcome is SponsorOutcome.OK
    assert export.sponsor_count == len(export.sponsors) == 7
    kinds = {
        "removed": any(s["removedAt"] for s in export.sponsors),
        "merged": any(s["mergedIntoId"] for s in export.sponsors),
        "merge target present": {s["mergedIntoId"] for s in export.sponsors if s["mergedIntoId"]}
        <= {s["id"] for s in export.sponsors},
        "enriched": any(s["enrichedAt"] for s in export.sponsors),
        "never enriched": any(s["enrichedAt"] is None for s in export.sponsors),
        "hex guid id": any(len(s["id"]) == 32 for s in export.sponsors),
    }
    assert all(kinds.values()), f"fixture lacks variety: {kinds}"


def test_recorded_export_has_no_empty_strings_or_lists():
    # The contract promises null for unknown. If this fails, the API changed, not us.
    sponsors = json.loads(RECORDED.read_bytes())["sponsors"]

    assert not [(s["id"], k) for s in sponsors for k, v in s.items() if v in ("", [])]
