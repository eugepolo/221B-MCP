from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from mcp_221b.server import mcp
from mcp_221b.tool_handlers.search_username import SearchUsername
from mcp_221b.username_presets import DEV_SITES, LIGHT_SITES


@pytest.mark.parametrize(
    "depth,expected",
    [
        ("light", LIGHT_SITES),
        ("dev", DEV_SITES),
        ("complete", ()),
    ],
)
async def test_preset_invocation(monkeypatch, depth, expected):
    monkeypatch.setattr(
        "mcp_221b.tool_handlers.search_username.sherlock_command", lambda: "/fake/sherlock"
    )
    seen = []

    async def create(*args, **kwargs):
        seen.extend(args)
        (Path(kwargs["cwd"]) / "alice.csv").write_text(
            "name,url_user,exists,http_status\nGitHub,https://github.com/alice,Claimed,200\n"
        )
        process = Mock(returncode=0)
        process.wait = AsyncMock(return_value=0)
        return process

    monkeypatch.setattr(
        "mcp_221b.tool_handlers.search_username.asyncio.create_subprocess_exec", create
    )
    result = await SearchUsername(AsyncMock()).search_username("alice", depth=depth)
    assert [seen[i + 1] for i, arg in enumerate(seen) if arg == "--site"] == list(expected)
    assert ("--nsfw" in seen) == (depth == "complete")
    assert "--ignore-exclusions" not in seen
    assert any(f"Scope: {depth}" in note for note in result.notes)
    assert any(f"{600 if depth == 'complete' else 120} seconds" in n for n in result.notes)


def test_presets_are_distinct_and_light_has_twenty_sites():
    assert len(LIGHT_SITES) == len(set(LIGHT_SITES)) == 20
    assert len(DEV_SITES) == len(set(DEV_SITES))
    assert "Docker Hub" in DEV_SITES
    assert "Instagram" not in DEV_SITES


async def test_explicit_sites_override_complete_without_cap(monkeypatch):
    monkeypatch.setattr(
        "mcp_221b.tool_handlers.search_username.sherlock_command", lambda: "/fake/sherlock"
    )
    selected = [f"Site{i}" for i in range(25)]

    async def create(*args, **kwargs):
        assert args.count("--site") == 25
        assert "--nsfw" not in args
        (Path(kwargs["cwd"]) / "alice.csv").write_text("name,url_user,exists,http_status\n")
        process = Mock(returncode=0)
        process.wait = AsyncMock(return_value=0)
        return process

    monkeypatch.setattr(
        "mcp_221b.tool_handlers.search_username.asyncio.create_subprocess_exec", create
    )
    result = await SearchUsername(AsyncMock()).search_username(
        "alice", sites=selected, depth="complete"
    )
    assert len(result.findings) == 25
    assert all(f.status == "unknown" for f in result.findings)
    assert any("Scope: custom" in note for note in result.notes)


@pytest.mark.parametrize("kwargs", [{"depth": "invalid"}, {"sites": []}])
async def test_invalid_scope_rejected(kwargs):
    with pytest.raises(ValueError):
        await SearchUsername(AsyncMock()).search_username("alice", **kwargs)


async def test_mcp_depth_schema():
    tool = next(t for t in await mcp.list_tools() if t.name == "search_username")
    schema = tool.inputSchema["properties"]["depth"]
    assert schema["enum"] == ["light", "dev", "complete"]
    assert schema["default"] == "light"
