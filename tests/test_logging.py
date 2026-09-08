import json
import logging

import pytest

from mcp_221b.logging_setup import configure_logging, logged_tool, logger


@pytest.fixture
def logs(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MCP_221B_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("MCP_221B_LOG_LEVEL", raising=False)
    path = configure_logging()
    yield path
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)


async def test_logs_metadata_without_inputs_or_stdout(logs, capsys):
    @logged_tool
    async def example(query):
        return {"id": "record123", "findings": [{"status": "blocked"}], "query": query}

    await example("private-query-and-key")
    records = [json.loads(line) for line in logs.read_text().splitlines()]
    assert records[0]["event"] == "tool_started"
    assert records[1]["statuses"] == {"blocked": 1}
    assert records[0]["call_id"] == records[1]["call_id"]
    assert "private-query-and-key" not in logs.read_text()
    captured = capsys.readouterr()
    assert not captured.out
    assert "tool_finished" in captured.err


async def test_error_logging_redacts_exception_message(logs):
    @logged_tool
    async def example():
        raise ValueError("secret-provider-url")

    with pytest.raises(ValueError):
        await example()
    assert "secret-provider-url" not in logs.read_text()
    assert json.loads(logs.read_text().splitlines()[-1])["error_type"] == "ValueError"


def test_reconfiguration_does_not_duplicate_handlers(logs):
    configure_logging()
    assert len(logger.handlers) == 2
    assert all(not isinstance(h, logging.NullHandler) for h in logger.handlers)
