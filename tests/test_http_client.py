import brotli
import httpx
import pytest

from nl_jobs.http_client import make_client, retry_after_seconds


def test_client_decodes_brotli_responses():
    # The iwwz sponsor export is served brotli-compressed; this fails if the extra is missing.
    body = brotli.compress(b'{"ok": true}')
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=body, headers={"Content-Encoding": "br"})
    )

    with make_client(transport=transport) as client:
        assert client.get("https://example.test").json() == {"ok": True}


@pytest.mark.parametrize(
    ("header", "expected"),
    [("5", 5.0), ("3600", 60.0), ("Wed, 21 Oct 2026 07:28:00 GMT", None), (None, None)],
)
def test_retry_after_seconds(header, expected):
    headers = {"Retry-After": header} if header else {}

    assert retry_after_seconds(httpx.Response(429, headers=headers)) == expected
