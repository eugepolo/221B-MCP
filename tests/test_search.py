import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from mcp_221b.cli import main
from mcp_221b.config import read_config, save_config, search_provider
from mcp_221b.network import FetchError
from mcp_221b.search_worker import search
from mcp_221b.tool_handlers.search_web import SearchWeb


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_221B_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("MCP_221B_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)


def test_provider_default_and_overrides(monkeypatch):
    save_config({"brave_key_storage": "keyring"})
    assert search_provider() == "keyless"
    save_config({"search_provider": "brave"})
    assert search_provider() == "brave"
    monkeypatch.setenv("MCP_221B_SEARCH_PROVIDER", "keyless")
    assert search_provider() == "keyless"
    monkeypatch.setenv("MCP_221B_SEARCH_PROVIDER", "invalid")
    with pytest.raises(ValueError):
        search_provider()


async def test_keyless_default_maps_results_without_brave(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "must-not-be-used")
    process = Mock(returncode=0)
    process.communicate = AsyncMock(
        return_value=(
            json.dumps(
                {
                    "results": [
                        {"url": "https://example.org", "title": "Example", "snippet": "Evidence"}
                    ]
                }
            ).encode(),
            None,
        )
    )
    create = AsyncMock(return_value=process)
    monkeypatch.setattr("mcp_221b.tool_handlers.search_web.asyncio.create_subprocess_exec", create)
    network = AsyncMock()
    result = await SearchWeb(network).search_web('site:example.org "report"', limit=2)
    assert result.findings[0].evidence["provider"] == "keyless"
    assert result.findings[0].source == "https://example.org"
    request = json.loads(process.communicate.call_args.args[0])
    assert request == {"query": 'site:example.org "report"', "limit": 2}
    network.get.assert_not_called()


async def test_explicit_keyless_overrides_brave_default(monkeypatch):
    save_config({"search_provider": "brave"})
    providers = SearchWeb(AsyncMock())
    providers._search_keyless = AsyncMock()
    await providers.search_web("example", provider="keyless")
    providers._search_keyless.assert_awaited_once_with("example", 10)


def test_worker_uses_automatic_engines_and_preserves_query(monkeypatch):
    engine = Mock()
    engine.text.return_value = [{"href": "https://example.org", "title": "T", "body": "B"}]
    constructor = Mock(return_value=engine)
    monkeypatch.setattr("mcp_221b.search_worker.DDGS", constructor)
    result = search('site:example.org "report"', 2)
    engine.text.assert_called_once_with('site:example.org "report"', max_results=2, backend="auto")
    assert result["results"][0]["snippet"] == "B"


@pytest.mark.parametrize(
    "exception,status",
    [(RatelimitException, "blocked"), (TimeoutException, "error"), (DDGSException, "unknown")],
)
def test_worker_failures_are_not_absence(monkeypatch, exception, status):
    engine = Mock()
    engine.text.side_effect = exception("provider detail")
    monkeypatch.setattr("mcp_221b.search_worker.DDGS", Mock(return_value=engine))
    result = search("example", 2)
    assert result["status"] == status
    assert "provider detail" not in result["error"]


async def test_keyless_failure_never_falls_back_to_brave(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "unused")
    process = Mock(returncode=0)
    process.communicate = AsyncMock(
        return_value=(b'{"error":"Rate limited","status":"blocked"}', None)
    )
    monkeypatch.setattr(
        "mcp_221b.tool_handlers.search_web.asyncio.create_subprocess_exec",
        AsyncMock(return_value=process),
    )
    network = AsyncMock()
    with pytest.raises(FetchError) as error:
        await SearchWeb(network).search_web("example")
    assert error.value.status == "blocked"
    network.get.assert_not_called()


@pytest.mark.parametrize("error", [TimeoutError, asyncio.CancelledError])
async def test_keyless_worker_terminated(monkeypatch, error):
    process = Mock(returncode=None)
    process.communicate = AsyncMock(side_effect=error)
    process.wait = AsyncMock()
    monkeypatch.setattr(
        "mcp_221b.tool_handlers.search_web.asyncio.create_subprocess_exec",
        AsyncMock(return_value=process),
    )
    with pytest.raises(error):
        await SearchWeb(AsyncMock()).search_web("example")
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()


def test_init_keyless_does_not_ask_for_key(monkeypatch):
    monkeypatch.setattr("sys.argv", ["221b-mcp", "init"])
    monkeypatch.setattr("builtins.input", lambda _: "")
    prompt = Mock(side_effect=AssertionError("Should not request API key"))
    monkeypatch.setattr("mcp_221b.cli.getpass.getpass", prompt)
    main()
    assert read_config()["search_provider"] == "keyless"
    prompt.assert_not_called()


def test_init_brave_retains_key(monkeypatch):
    save_config({"brave_key_storage": "keyring"})
    monkeypatch.setattr("sys.argv", ["221b-mcp", "init"])
    monkeypatch.setattr("builtins.input", lambda _: "brave")
    monkeypatch.setattr("mcp_221b.cli.getpass.getpass", lambda _: "")
    main()
    assert read_config() == {"brave_key_storage": "keyring", "search_provider": "brave"}
