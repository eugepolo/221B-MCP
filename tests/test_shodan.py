import logging
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from mcp_221b import credentials
from mcp_221b.evidence import export_records, record
from mcp_221b.network import Network
from mcp_221b.runtime import ToolHandlers
from mcp_221b.tool_handlers.shodan import Shodan


@pytest.fixture(autouse=True)
def isolated_shodan(monkeypatch):
    monkeypatch.setattr(credentials, "_os_backend", Mock(side_effect=AssertionError("OS store")))
    monkeypatch.setattr("mcp_221b.tool_handlers.shodan.asyncio.sleep", AsyncMock())


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("SHODAN_API_KEY", "test-shodan-secret")
    network = AsyncMock()
    return Shodan(network)


async def test_host_mapping_and_export(provider):
    provider.network.get.return_value = httpx.Response(
        200,
        json={
            "ip_str": "8.8.8.8",
            "org": "Example",
            "ports": [53],
            "last_update": "2026-01-01T00:00:00",
            "data": [
                {
                    "port": 53,
                    "transport": "udp",
                    "timestamp": "2025-12-31T00:00:00",
                    "data": "x" * 2500,
                },
            ],
        },
    )
    result = await provider.lookup_shodan_host("8.8.8.8")
    finding = result.findings[0]
    assert finding.source == "https://www.shodan.io/host/8.8.8.8"
    assert finding.evidence["last_update"] != result.retrieved_at
    service = finding.evidence["services"][0]
    assert service["timestamp"] == "2025-12-31T00:00:00"
    assert len(service["banner"]) == 2000 and service["banner_truncated"]
    saved = record(result)
    exported = export_records([saved["id"]])
    from pathlib import Path

    assert "test-shodan-secret" not in Path(exported["path"]).read_text()
    provider.network.get.assert_awaited_once_with(
        "https://api.shodan.io/shodan/host/8.8.8.8",
        params={"key": "test-shodan-secret", "history": "false", "minify": "false"},
        allow_redirects=False,
    )


async def test_search_is_one_page_of_services(provider):
    provider.network.get.return_value = httpx.Response(
        200,
        json={
            "total": 300,
            "matches": [
                {"ip_str": "8.8.8.8", "port": port, "transport": "tcp"} for port in [80, 443]
            ],
        },
    )
    result = await provider.search_shodan('org:"Example"', limit=1, page=2)
    assert len(result.findings) == 1
    assert result.findings[0].evidence["port"] == 80
    assert any("Total matching services: 300; page: 2; returned: 1" in n for n in result.notes)
    assert any("omitted by limit: 1" in n for n in result.notes)
    assert provider.network.get.await_count == 1
    assert provider.network.get.call_args.kwargs["params"]["page"] == 2
    assert "test-shodan-secret" not in result.model_dump_json()


async def test_empty_search(provider):
    provider.network.get.return_value = httpx.Response(200, json={"matches": [], "total": 0})
    result = await provider.search_shodan("example")
    assert result.findings == []
    assert any("does not prove absence" in n for n in result.notes)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "example.org", "8.8.8.8/path"])
async def test_invalid_host_does_not_request(provider, ip):
    with pytest.raises(ValueError):
        await provider.lookup_shodan_host(ip)
    provider.network.get.assert_not_called()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": " "},
        {"query": "x" * 601},
        {"query": "x", "limit": 0},
        {"query": "x", "limit": 101},
        {"query": "x", "page": 0},
    ],
)
async def test_invalid_search_does_not_request(provider, kwargs):
    with pytest.raises(ValueError):
        await provider.search_shodan(**kwargs)
    provider.network.get.assert_not_called()


@pytest.mark.parametrize(
    "method,arg", [("lookup_shodan_host", "8.8.8.8"), ("search_shodan", "example")]
)
async def test_missing_key_does_not_request(method, arg, monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "not-a-shodan-key")
    handlers = ToolHandlers(AsyncMock())
    with pytest.raises(ValueError, match="SHODAN_API_KEY_FILE"):
        await getattr(handlers, method)(arg)
    handlers.shodan.network.get.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"error": "test-shodan-secret"},
        {"matches": "bad", "total": 1},
        {"matches": [{}], "total": 1},
        {"matches": [], "total": "0"},
    ],
)
async def test_invalid_response_is_sanitized(provider, payload):
    provider.network.get.return_value = httpx.Response(200, json=payload)
    result = await provider.search_shodan("example")
    assert result.findings[0].status == "error"
    assert "test-shodan-secret" not in result.model_dump_json()


@pytest.mark.parametrize(
    "code,status",
    [
        (401, "blocked"),
        (403, "blocked"),
        (429, "blocked"),
        (404, "not_found"),
        (500, "error"),
        (302, "error"),
    ],
)
async def test_network_errors_and_logs(monkeypatch, caplog, code, status):
    monkeypatch.setenv("SHODAN_API_KEY", "test-shodan-secret")
    monkeypatch.setattr("mcp_221b.network.validate_public_url", AsyncMock())
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(code, headers={"location": "https://other.example/?key=secret"})

    network = Network()
    await network.client.aclose()
    network.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        with caplog.at_level(logging.DEBUG):
            result = await Shodan(network).lookup_shodan_host("8.8.8.8")
        assert result.findings[0].status == status
        assert len(requests) == 1
        assert "test-shodan-secret" not in caplog.text + result.model_dump_json()
    finally:
        await network.close()


async def test_host_service_limit(provider):
    provider.network.get.return_value = httpx.Response(
        200,
        json={
            "ip_str": "8.8.8.8",
            "data": [{"port": 80}] * 101,
        },
    )
    result = await provider.lookup_shodan_host("8.8.8.8")
    evidence = result.findings[0].evidence
    assert len(evidence["services"]) == 100
    assert evidence["services_returned"] == 100
    assert evidence["services_truncated"] is True


@pytest.mark.parametrize(
    "method,arg", [("lookup_shodan_host", "8.8.8.8"), ("search_shodan", "example")]
)
async def test_non_json_response(provider, method, arg):
    provider.network.get.return_value = httpx.Response(200, text="test-shodan-secret")
    result = await getattr(provider, method)(arg)
    assert result.findings[0].status == "error"
    assert "test-shodan-secret" not in result.model_dump_json()


async def test_timeout_is_sanitized(monkeypatch, caplog):
    monkeypatch.setenv("SHODAN_API_KEY", "test-shodan-secret")
    monkeypatch.setattr("mcp_221b.network.validate_public_url", AsyncMock())

    def timeout(request):
        logging.getLogger("httpcore.http11").debug("request target: %s", request.url)
        raise httpx.ReadTimeout(f"timeout: {request.url}", request=request)

    network = Network()
    await network.client.aclose()
    network.client = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    try:
        with caplog.at_level(logging.DEBUG):
            result = await Shodan(network).search_shodan("example")
        assert result.findings[0].status == "error"
        assert "test-shodan-secret" not in caplog.text + result.model_dump_json()
    finally:
        await network.close()
