"""The record every source client returns, whatever happened to the request."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class Outcome(StrEnum):
    OK = "ok"  # 200 with at least one job
    EMPTY = "empty"  # 200 with zero jobs: the board exists and has nothing open
    NOT_FOUND = "not_found"  # 404: slug is wrong or the company left this ATS
    FAILED = "failed"  # no usable answer: network error, 5xx, 429, bad JSON, unknown shape


@dataclass(frozen=True)
class FetchResult:
    source: str
    board_slug: str
    request_url: str
    fetched_at: datetime
    outcome: Outcome
    # None means "no value", never zero: a 404 has no job count, not a count of 0.
    http_status: int | None = None
    job_count: int | None = None
    payload: Any = None
    error: str | None = None
