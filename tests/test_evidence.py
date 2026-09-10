import json
from pathlib import Path

import pytest

from mcp_221b.evidence import Finding, Result, export_records, record


def test_export_preserves_evidence_and_rejects_traversal():
    result = record(
        Result(
            tool="example",
            query="alice",
            findings=[
                Finding(
                    source="https://example.org/alice",
                    status="found",
                    evidence={"identity_verified": False},
                )
            ],
        )
    )
    exported = export_records([result["id"]])
    assert json.loads(Path(exported["path"]).read_text()) == [result]
    with pytest.raises(ValueError):
        export_records(["../../config"])
    with pytest.raises(ValueError):
        export_records(["a" * 32])


@pytest.mark.parametrize("format", ["json", "markdown"])
def test_unicode_evidence_round_trip(format):
    result = record(Result(tool="example", query="caf\u00e9 \u6771\u4eac \U0001f50e"))
    exported = export_records([result["id"]], format=format)
    text = Path(exported["path"]).read_text(encoding="utf-8")
    if format == "markdown":
        text = "\n".join(line[4:] for line in text.splitlines()[2:])
    assert json.loads(text) == [result]
