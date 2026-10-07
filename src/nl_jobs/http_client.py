"""Shared HTTP plumbing: one configured client and a polite retry loop."""

import time
from collections.abc import Callable
from typing import Any

import httpx

USER_AGENT = "nl-tech-jobs-pipeline/0.1 (+https://github.com/aj1daar/nl-tech-jobs-pipeline)"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER_SECONDS = 60.0


def make_client(**kwargs: Any) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
        **kwargs,
    )


def get_with_retries(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, str] | None = None,
    attempts: int = 3,
    backoff_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """GET with retries on transport errors and RETRY_STATUSES.

    Returns the last response, which may still be an error status.
    Raises httpx.TransportError only if the final attempt never got a response.
    """
    for attempt in range(1, attempts + 1):
        delay = backoff_seconds * 2 ** (attempt - 1)
        try:
            response = client.get(url, params=params)
        except httpx.TransportError:
            if attempt == attempts:
                raise
            sleep(delay)
            continue
        if response.status_code not in RETRY_STATUSES or attempt == attempts:
            return response
        sleep(retry_after_seconds(response) or delay)
    raise AssertionError("unreachable: the loop always returns or raises")


def retry_after_seconds(response: httpx.Response) -> float | None:
    """Seconds from a numeric Retry-After header, capped. HTTP-date values are ignored."""
    value = response.headers.get("Retry-After", "")
    try:
        return min(float(value), MAX_RETRY_AFTER_SECONDS)
    except ValueError:
        return None
