import asyncio
import gzip
import socket
import ssl
from unittest.mock import AsyncMock

import httpcore
import httpx
import pytest

from mcp_221b.network import FetchError, Network, PublicNetworkBackend, validate_public_url


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


def dns_answer(address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return (family, socket.SOCK_STREAM, 6, "", (address, 443))


async def test_transport_pins_ip_and_preserves_https_origin(monkeypatch):
    resolver = AsyncMock(return_value=[dns_answer("93.184.216.34")])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    stream = httpcore.AsyncMockStream([b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"])
    stream.start_tls = AsyncMock(return_value=stream)
    stream.write = AsyncMock()
    connect = AsyncMock(return_value=stream)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    network = Network()
    try:
        response = await network.get("https://example.org/page")
        assert response.text == "ok"
        assert str(response.url) == "https://example.org/page"
        assert connect.await_args.args == ("93.184.216.34", 443)
        tls = stream.start_tls.await_args.kwargs
        assert tls["server_hostname"] == "example.org"
        assert tls["ssl_context"].check_hostname
        assert tls["ssl_context"].verify_mode == ssl.CERT_REQUIRED
        sent = b"".join(call.args[0] for call in stream.write.await_args_list)
        assert b"Host: example.org\r\n" in sent
        assert b"GET /page HTTP/1.1" in sent
    finally:
        await network.close()


@pytest.mark.parametrize("private", ["127.0.0.1", "10.0.0.1", "::1"])
async def test_rebinding_between_validation_and_connect_is_rejected(monkeypatch, private):
    resolver = AsyncMock(
        side_effect=[
            [dns_answer("93.184.216.34")],
            [dns_answer(private)],
        ]
    )
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    connect = AsyncMock()
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    network = Network()
    try:
        with pytest.raises(ValueError, match="Only public"):
            await network.get("http://rebind.example")
        connect.assert_not_awaited()
    finally:
        await network.close()


async def test_backend_rejects_mixed_public_private_dns(monkeypatch):
    resolver = AsyncMock(return_value=[dns_answer("93.184.216.34"), dns_answer("10.0.0.1")])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    connect = AsyncMock()
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    with pytest.raises(ValueError, match="Only public"):
        await PublicNetworkBackend().connect_tcp("mixed.example", 443)
    connect.assert_not_awaited()


async def test_backend_falls_back_only_to_validated_addresses(monkeypatch):
    resolver = AsyncMock(return_value=[dns_answer("93.184.216.34"), dns_answer("1.1.1.1")])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    stream = httpcore.AsyncMockStream([])
    connect = AsyncMock(side_effect=[httpcore.ConnectError("unreachable"), stream])
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    assert await PublicNetworkBackend().connect_tcp("example.org", 443) is stream
    assert [call.args[0] for call in connect.await_args_list] == ["93.184.216.34", "1.1.1.1"]
    resolver.assert_awaited_once()


async def test_transport_connect_errors_are_sanitized(monkeypatch):
    monkeypatch.setattr(
        asyncio.get_running_loop(),
        "getaddrinfo",
        AsyncMock(return_value=[dns_answer("93.184.216.34")]),
    )
    monkeypatch.setattr(
        httpcore.AnyIOBackend,
        "connect_tcp",
        AsyncMock(side_effect=httpcore.ConnectError("private details")),
    )
    network = Network()
    try:
        with pytest.raises(FetchError, match="Source request failed or timed out"):
            await network.get("https://example.org")
    finally:
        await network.close()
