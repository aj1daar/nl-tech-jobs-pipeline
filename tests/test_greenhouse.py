"""Greenhouse client against recorded responses. No network: httpx.MockTransport answers."""

import httpx
import pytest

from nl_jobs.fetch_result import Outcome
from nl_jobs.http_client import USER_AGENT, make_client
from nl_jobs.sources import greenhouse
from tests.helpers import load_fixture, load_json_fixture


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


def json_response(status, fixture_name, **kwargs):
    content = load_fixture("greenhouse", fixture_name)
    return httpx.Response(status, content=content, **kwargs)


class Sleeps(list):
    """Records requested sleeps instead of sleeping."""

    def __call__(self, seconds):
        self.append(seconds)


def test_board_with_jobs_is_ok_and_keeps_payload_untouched():
    client, seen = client_answering(json_response(200, "catawiki_jobs.json"))

    result = greenhouse.fetch_board(client, "catawiki", sleep=Sleeps())

    assert result.outcome is Outcome.OK
    assert result.http_status == 200
    assert result.job_count == 3
    assert result.payload == load_json_fixture("greenhouse", "catawiki_jobs.json")
    assert result.error is None
    assert result.fetched_at.tzinfo is not None
    assert seen[0].url == result.request_url
    assert seen[0].url.params["content"] == "true"
    assert seen[0].headers["User-Agent"] == USER_AGENT


def test_board_with_zero_jobs_is_empty_not_failed():
    client, _ = client_answering(json_response(200, "empty_board.json"))

    result = greenhouse.fetch_board(client, "quiet-company", sleep=Sleeps())

    assert result.outcome is Outcome.EMPTY
    assert result.job_count == 0
    assert result.payload == {"jobs": [], "meta": {"total": 0}}


def test_unknown_slug_is_not_found_with_no_job_count():
    client, _ = client_answering(json_response(404, "not_found.json"))

    result = greenhouse.fetch_board(client, "nl-jobs-no-such-board", sleep=Sleeps())

    assert result.outcome is Outcome.NOT_FOUND
    assert result.http_status == 404
    assert result.job_count is None
    assert result.payload is None


def test_server_errors_are_retried_then_recorded_as_failed():
    sleeps = Sleeps()
    client, seen = client_answering(*(httpx.Response(503, text="unavailable") for _ in range(3)))

    result = greenhouse.fetch_board(client, "catawiki", sleep=sleeps)

    assert len(seen) == 3
    assert sleeps == [1.0, 2.0]
    assert result.outcome is Outcome.FAILED
    assert result.http_status == 503
    assert result.error == "unavailable"


def test_rate_limit_waits_for_retry_after_then_succeeds():
    sleeps = Sleeps()
    client, _ = client_answering(
        httpx.Response(429, headers={"Retry-After": "7"}),
        json_response(200, "catawiki_jobs.json"),
    )

    result = greenhouse.fetch_board(client, "catawiki", sleep=sleeps)

    assert sleeps == [7.0]
    assert result.outcome is Outcome.OK


def test_network_error_is_failed_with_no_http_status():
    timeout = httpx.ConnectTimeout("timed out")
    client, _ = client_answering(timeout, timeout, timeout)

    result = greenhouse.fetch_board(client, "catawiki", sleep=Sleeps())

    assert result.outcome is Outcome.FAILED
    assert result.http_status is None
    assert result.error == "ConnectTimeout: timed out"


@pytest.mark.parametrize(
    ("body", "error_start"),
    [
        (b"<html>maintenance</html>", "invalid JSON"),
        (b'{"error": "nope"}', "unexpected shape"),
        (b"[]", "unexpected shape"),
    ],
)
def test_unusable_200_body_is_failed(body, error_start):
    client, _ = client_answering(httpx.Response(200, content=body))

    result = greenhouse.fetch_board(client, "catawiki", sleep=Sleeps())

    assert result.outcome is Outcome.FAILED
    assert result.error.startswith(error_start)
    assert result.payload is None
    assert result.job_count is None
