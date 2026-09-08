import os
import sys
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_221b.evidence import Result, record
from mcp_221b.runtime import ToolHandlers


async def test_missing_key_does_not_make_request():
    network = AsyncMock()
    with pytest.raises(ValueError, match="BRAVE_API_KEY"):
        await ToolHandlers(network).search_web("example", provider="brave")
    network.get.assert_not_called()


async def test_search_and_archive_mapping(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "test-key")
    network = AsyncMock()
    network.get.return_value = httpx.Response(
        200,
        json={
            "web": {
                "results": [
                    {"url": "https://example.org", "title": "Example", "description": "Snippet"}
                ]
            }
        },
    )
    providers = ToolHandlers(network)
    result = await providers.search_web("example", provider="brave")
    assert result.findings[0].evidence["snippet"] == "Snippet"
    assert "test-key" not in result.model_dump_json()
    network.get.return_value = httpx.Response(
        200,
        json=[
            ["timestamp", "original", "statuscode", "mimetype", "digest"],
            ["20240101000000", "https://example.org", "200", "text/html", "ABC"],
        ],
    )
    result = await providers.search_archives("https://example.org")
    assert (
        result.findings[0].source
        == "https://web.archive.org/web/20240101000000/https://example.org"
    )


async def test_stdio_handshake_tool_listing_and_export():
    saved = record(Result(tool="fixture", query="example"))
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_221b", "serve"],
        env={**os.environ},
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == {
                "search_username",
                "search_web",
                "inspect_page",
                "lookup_domain",
                "search_archives",
                "export_findings",
            }
            for tool in tools.tools:
                assert "ctx" not in tool.inputSchema.get("properties", {})
            result = await session.call_tool("export_findings", {"record_ids": [saved["id"]]})
            assert not result.isError
            invalid = await session.call_tool("search_web", {"query": ""})
            assert invalid.isError
