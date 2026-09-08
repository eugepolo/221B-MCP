"""Operational logs without investigation content or protocol stdout traffic."""

import functools
import json
import logging
import os
import time
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from osint_mcp.config import data_path

logger = logging.getLogger("osint_mcp")


def log_directory() -> Path:
    return (
        Path(os.environ["OSINT_MCP_LOG_DIR"])
        if os.environ.get("OSINT_MCP_LOG_DIR")
        else (data_path() / "logs")
    )


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
                "level": record.levelname,
                "pid": record.process,
                "event": record.getMessage(),
                **getattr(record, "fields", {}),
            }
        )


class PrivateRotatingHandler(RotatingFileHandler):
    def _open(self):
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        return os.fdopen(fd, self.mode, encoding=self.encoding)


def configure_logging() -> Path:
    level = os.environ.get("OSINT_MCP_LOG_LEVEL", "INFO").upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValueError("OSINT_MCP_LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR.")
    directory = log_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"server-{os.getpid()}.jsonl"
    # Per-process files avoid rotation races between Codex and Inspector instances.
    file_handler = PrivateRotatingHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handlers = [file_handler, logging.StreamHandler()]  # StreamHandler defaults to stderr.
    for old in logger.handlers[:]:
        logger.removeHandler(old)
        old.close()
    for handler in handlers:
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return path


def logged_tool(function):
    """Preserve MCP signatures and log metadata only, even on unexpected errors."""

    @functools.wraps(function)
    async def wrapped(*args, **kwargs):
        started = time.monotonic()
        fields = {"tool": function.__name__, "call_id": uuid4().hex}
        logger.info("tool_started", extra={"fields": fields})
        try:
            result = await function(*args, **kwargs)
        except BaseException as exc:
            # Do not include exception strings/tracebacks: providers may embed URLs or keys.
            logger.warning(
                "tool_failed",
                extra={
                    "fields": {
                        **fields,
                        "error_type": type(exc).__name__,
                        "duration_ms": round((time.monotonic() - started) * 1000),
                    }
                },
            )
            raise
        statuses = {}
        for finding in result.get("findings", []):
            status = finding["status"]
            statuses[status] = statuses.get(status, 0) + 1
        logger.info(
            "tool_finished",
            extra={
                "fields": {
                    **fields,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "record_id": result.get("id"),
                    "statuses": statuses,
                    "exported_records": result.get("records"),
                }
            },
        )
        return result

    return wrapped
