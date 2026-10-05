"""Client for the iwwz sponsor export (the IND register of recognised sponsors).

Contract: iwwz repo, docs/ARCHITECTURE.md, section "Sponsor export contract".
One response, no pagination: {"schemaVersion", "generatedAt", "count", "sponsors": [...]}.

Same shape as the board clients: fetch_export never raises for an expected failure and
always returns a result. It differs in two ways: it sends a secret, and every failure
has its own outcome, because "bad key" and "host down" need different reactions.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx

from nl_jobs.config import IwwzSettings
from nl_jobs.http_client import get_with_retries

SOURCE = "iwwz_sponsors"
SUPPORTED_SCHEMA_VERSION = 1
API_KEY_HEADER = "X-Api-Key"
# 401 and 429 are deliberately absent: a bad key stays bad, and retrying a rate limit
# only uses up more of it.
RETRY_STATUSES = frozenset({500, 502, 503, 504})
# The server builds the payload in about 150 ms; the read timeout covers the transfer.
TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)


class SponsorOutcome(StrEnum):
    OK = "ok"
    EMPTY = "empty"  # valid envelope with zero sponsors: suspicious, never landed as a snapshot
    UNREACHABLE = "unreachable"  # no response at all
    UNAUTHORIZED = "unauthorized"  # 401: missing, wrong or revoked key
    RATE_LIMITED = "rate_limited"  # 429
    SERVER_ERROR = "server_error"  # 5xx after retries
    UNEXPECTED_STATUS = "unexpected_status"  # any other status, e.g. a 403 WAF challenge
    INVALID_JSON = "invalid_json"  # 200 whose body is not JSON
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    INVALID_ENVELOPE = "invalid_envelope"  # JSON, but not the documented shape
    COUNT_MISMATCH = "count_mismatch"  # count != len(sponsors): treat as truncated


@dataclass(frozen=True)
class SponsorExport:
    request_url: str
    fetched_at: datetime
    outcome: SponsorOutcome
    http_status: int | None = None
    schema_version: int | None = None
    generated_at: datetime | None = None
    sponsor_count: int | None = None
    # repr=False: 12,800 rows do not belong in a log line.
    sponsors: list[dict[str, Any]] | None = field(default=None, repr=False)
    error: str | None = None


def fetch_export(
    client: httpx.Client, settings: IwwzSettings, *, sleep: Callable[[float], None] = time.sleep
) -> SponsorExport:
    def result(outcome: SponsorOutcome, **fields) -> SponsorExport:
        if fields.get("error"):
            # Last line of defence: no error text may carry the key, whatever produced it.
            fields["error"] = fields["error"].replace(settings.api_key, "[redacted]")
        return SponsorExport(
            request_url=settings.export_url,
            fetched_at=datetime.now(UTC),
            outcome=outcome,
            **fields,
        )

    try:
        response = get_with_retries(
            client,
            settings.export_url,
            headers={API_KEY_HEADER: settings.api_key},
            timeout=TIMEOUT,
            retry_statuses=RETRY_STATUSES,
            sleep=sleep,
        )
    except httpx.TransportError as exc:
        return result(SponsorOutcome.UNREACHABLE, error=f"{type(exc).__name__}: {exc}")

    status = response.status_code
    if status == 401:
        return result(
            SponsorOutcome.UNAUTHORIZED,
            http_status=status,
            error="401: the server rejected IWWZ_API_KEY (missing, wrong or revoked)",
        )
    if status == 429:
        retry_after = response.headers.get("Retry-After", "not given")
        return result(
            SponsorOutcome.RATE_LIMITED,
            http_status=status,
            error=f"429: rate limited, Retry-After: {retry_after}",
        )
    if status >= 500:
        return result(
            SponsorOutcome.SERVER_ERROR, http_status=status, error=response.text[:500] or "no body"
        )
    if status != 200:
        return result(
            SponsorOutcome.UNEXPECTED_STATUS,
            http_status=status,
            error=response.text[:500] or "no body",
        )

    try:
        envelope = response.json()
    except ValueError as exc:
        return result(SponsorOutcome.INVALID_JSON, http_status=status, error=f"invalid JSON: {exc}")
    if not isinstance(envelope, dict):
        return result(
            SponsorOutcome.INVALID_ENVELOPE, http_status=status, error="body is not a JSON object"
        )

    # Check the version before reading anything else: a newer schema may reuse field
    # names with a different meaning, so parsing it "anyway" would be silent corruption.
    version = envelope.get("schemaVersion")
    # type(...) is int, not isinstance: in Python True is an int and True == 1.
    if type(version) is not int or version != SUPPORTED_SCHEMA_VERSION:
        return result(
            SponsorOutcome.UNSUPPORTED_SCHEMA_VERSION,
            http_status=status,
            schema_version=version if type(version) is int else None,
            error=f"schemaVersion is {version!r}, this client supports {SUPPORTED_SCHEMA_VERSION}",
        )

    problem, generated_at = _check_envelope(envelope)
    if problem:
        return result(
            SponsorOutcome.INVALID_ENVELOPE,
            http_status=status,
            schema_version=version,
            error=problem,
        )

    sponsors, count = envelope["sponsors"], envelope["count"]
    known = {"http_status": status, "schema_version": version, "generated_at": generated_at}
    if count != len(sponsors):
        return result(
            SponsorOutcome.COUNT_MISMATCH,
            error=f"count says {count}, sponsors has {len(sponsors)} rows: truncated response",
            **known,
        )
    if not sponsors:
        return result(SponsorOutcome.EMPTY, error="export contained zero sponsors", **known)
    return result(SponsorOutcome.OK, sponsor_count=count, sponsors=sponsors, **known)


def _check_envelope(envelope: dict[str, Any]) -> tuple[str | None, datetime | None]:
    """Return (problem, generated_at). problem is None when the envelope is usable."""
    sponsors, count = envelope.get("sponsors"), envelope.get("count")
    if not isinstance(sponsors, list):
        return "sponsors is not a list", None
    if type(count) is not int:
        return "count is not an integer", None
    try:
        generated_at = datetime.fromisoformat(envelope.get("generatedAt"))
    except (TypeError, ValueError):
        return "generatedAt is not an ISO timestamp", None
    if generated_at.tzinfo is None:
        return "generatedAt has no UTC offset", None

    ids = set()
    for index, row in enumerate(sponsors):
        row_id = row.get("id") if isinstance(row, dict) else None
        # id is opaque text (a KvK number or a hex GUID), never a number.
        if not isinstance(row_id, str) or not row_id:
            return f"sponsors[{index}] has no string id", None
        if row_id in ids:
            return f"sponsors[{index}] repeats id {row_id!r}", None
        ids.add(row_id)
    return None, generated_at
