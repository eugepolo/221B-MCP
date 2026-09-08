import asyncio
import io
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mcp_221b.tool_handlers.search_username import SearchUsername, parse_sherlock


def test_sherlock_does_not_turn_errors_into_absence():
    csv = io.StringIO(
        "name,url_user,exists,http_status\n"
        "A,https://a.example/u,Claimed,200\n"
        "B,https://b.example/u,Available,404\n"
        "C,https://c.example/u,Unknown,429\n"
        "D,https://d.example/u,Unknown,\n"
    )
    findings = parse_sherlock(csv)
    assert [f.status for f in findings] == ["found", "not_found", "blocked", "error"]
    assert all(not f.evidence["identity_verified"] for f in findings)


async def test_username_rejects_shell_and_path_inputs():
    providers = SearchUsername(AsyncMock())
    for name in ["../alice", "--help", "alice;id", "alice{?}"]:
        with pytest.raises(ValueError):
            await providers.search_username(name)


async def test_sherlock_subprocess_report_and_missing_site(monkeypatch):
    monkeypatch.setattr(
        "mcp_221b.tool_handlers.search_username.sherlock_command", lambda: "/example/sherlock"
    )

    async def create(*args, **kwargs):
        assert args == (
            "/example/sherlock",
            "--csv",
            "--print-all",
            "--no-color",
            "--timeout",
            "10",
            "--site",
            "GitHub",
            "--site",
            "Missing",
            "alice",
        )
        (Path(kwargs["cwd"]) / "alice.csv").write_text(
            "name,url_user,exists,http_status\nGitHub,https://github.com/alice,Claimed,200\n"
        )
        process = AsyncMock()
        process.returncode = 0
        return process

    monkeypatch.setattr(
        "mcp_221b.tool_handlers.search_username.asyncio.create_subprocess_exec", create
    )
    result = await SearchUsername(AsyncMock()).search_username("alice", ["GitHub", "Missing"])
    assert [f.status for f in result.findings] == ["found", "unknown"]


async def test_sherlock_cancellation_kills_process(monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setattr(
        "mcp_221b.tool_handlers.search_username.sherlock_command", lambda: "/example/sherlock"
    )
    process = Mock(returncode=None)
    process.wait = AsyncMock(side_effect=[asyncio.CancelledError, 0])
    monkeypatch.setattr(
        "mcp_221b.tool_handlers.search_username.asyncio.create_subprocess_exec",
        AsyncMock(return_value=process),
    )
    with pytest.raises(asyncio.CancelledError):
        await SearchUsername(AsyncMock()).search_username("alice")
    process.kill.assert_called_once()
    assert process.wait.await_count == 2
