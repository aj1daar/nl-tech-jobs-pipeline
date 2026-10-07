"""Greenhouse job board API client.

Docs: https://developers.greenhouse.io/job-board.html
Response: {"jobs": [...], "meta": {"total": n}}. An unknown slug returns 404.

This module is the pattern for every other source: one fetch_board(client, slug)
function that never raises for expected failures and always returns a FetchResult.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from nl_jobs.fetch_result import FetchResult, Outcome
from nl_jobs.http_client import get_with_retries

SOURCE = "greenhouse"
BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
PARAMS = {"content": "true"}


def fetch_board(
    client: httpx.Client, slug: str, *, sleep: Callable[[float], None] = time.sleep
) -> FetchResult:
    url = BOARD_URL.format(slug=slug)
    request_url = str(httpx.URL(url, params=PARAMS))

    def result(outcome: Outcome, **fields) -> FetchResult:
        return FetchResult(
            source=SOURCE,
            board_slug=slug,
            request_url=request_url,
            fetched_at=datetime.now(UTC),
            outcome=outcome,
            **fields,
        )

    try:
        response = get_with_retries(client, url, params=PARAMS, sleep=sleep)
    except httpx.TransportError as exc:
        return result(Outcome.FAILED, error=f"{type(exc).__name__}: {exc}")

    status = response.status_code
    if status == 404:
        return result(Outcome.NOT_FOUND, http_status=status)
    if status != 200:
        return result(Outcome.FAILED, http_status=status, error=response.text[:500])

    try:
        payload = response.json()
    except ValueError as exc:
        return result(Outcome.FAILED, http_status=status, error=f"invalid JSON: {exc}")

    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return result(Outcome.FAILED, http_status=status, error="unexpected shape: no jobs list")

    return result(
        Outcome.OK if jobs else Outcome.EMPTY,
        http_status=status,
        job_count=len(jobs),
        payload=payload,
    )
