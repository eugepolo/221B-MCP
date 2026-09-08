"""Small local evidence store. Export only records collected by this server."""

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from mcp_221b.config import data_path


class Finding(BaseModel):
    source: str
    status: Literal["found", "not_found", "blocked", "error", "unknown"]
    evidence: dict[str, Any] = Field(default_factory=dict)


class Result(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    tool: str
    query: str
    retrieved_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    findings: list[Finding] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        output.write(text)


def record(result: Result) -> dict:
    write_private(data_path() / "evidence" / f"{result.id}.json", result.model_dump_json(indent=2))
    return result.model_dump()


def export_records(record_ids: list[str], format: Literal["json", "markdown"] = "json") -> dict:
    if not 1 <= len(record_ids) <= 100:
        raise ValueError("Provide between 1 and 100 record IDs.")
    records = []
    for record_id in record_ids:
        if not re.fullmatch(r"[a-f0-9]{32}", record_id):
            raise ValueError("Invalid evidence record ID.")
        path = data_path() / "evidence" / f"{record_id}.json"
        if not path.is_file():
            raise ValueError(f"Evidence record {record_id} does not exist.")
        records.append(json.loads(path.read_text()))
    if format not in {"json", "markdown"}:
        raise ValueError("Export format must be json or markdown.")
    # Indented code preserves evidence verbatim without interpreting remote HTML/Markdown.
    content = json.dumps(records, indent=2, ensure_ascii=False)
    if format == "markdown":
        content = "# 221B evidence\n\n" + "\n".join("    " + line for line in content.splitlines())
    path = data_path() / "exports" / f"{uuid4().hex}.{'json' if format == 'json' else 'md'}"
    write_private(path, content + "\n")
    return {"path": str(path.resolve()), "records": len(records), "format": format}
