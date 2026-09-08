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
