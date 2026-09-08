import gzip
from unittest.mock import AsyncMock

import httpx
import pytest

from mcp_221b.network import FetchError, Network, validate_public_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1",
        "http://[::1]",
        "http://10.0.0.1",
        "http://example.org:9000",
        "https://user:secret@example.org",
    ],
)
async def test_private_and_invalid_urls_rejected(url):
    with pytest.raises(ValueError):
        await validate_public_url(url)


async def test_redirect_checked_and_secrets_removed(monkeypatch):
    checked = AsyncMock()
    monkeypatch.setattr("mcp_221b.network.validate_public_url", checked)
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={"location": "https://other.example/result"})
        return httpx.Response(200, text="ok")

    network = Network()
    await network.client.aclose()
    network.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        response = await network.get(
            "https://example.org", headers={"X-Subscription-Token": "secret"}
        )
        assert response.text == "ok"
        assert len(checked.await_args_list) == 2
        assert "x-subscription-token" not in requests[1].headers
    finally:
        await network.close()


@pytest.mark.parametrize(
    "code,status", [(404, "not_found"), (403, "blocked"), (429, "blocked"), (500, "error")]
)
async def test_http_failures_are_distinct(monkeypatch, code, status):
    monkeypatch.setattr("mcp_221b.network.validate_public_url", AsyncMock())
    network = Network()
    await network.client.aclose()
    network.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(code))
    )
    try:
        with pytest.raises(FetchError) as error:
            await network.get("https://example.org")
        assert error.value.status == status
    finally:
        await network.close()


async def test_response_limit(monkeypatch):
    monkeypatch.setattr("mcp_221b.network.validate_public_url", AsyncMock())
    network = Network()
    await network.client.aclose()
    network.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 2_000_001))
    )
    try:
        with pytest.raises(FetchError, match="2 MB"):
            await network.get("https://example.org")
    finally:
        await network.close()


async def test_compressed_response_is_decoded_once(monkeypatch):
    monkeypatch.setattr("mcp_221b.network.validate_public_url", AsyncMock())
    network = Network()
    await network.client.aclose()
    network.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, headers={"content-encoding": "gzip"}, content=gzip.compress(b"hello")
            )
        )
    )
    try:
        assert (await network.get("https://example.org")).text == "hello"
    finally:
        await network.close()
