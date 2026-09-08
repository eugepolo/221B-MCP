"""Export existing evidence without coupling to MCP."""

import asyncio
from typing import Literal

from mcp_221b.evidence import export_records


async def export_findings(
    record_ids: list[str], format: Literal["json", "markdown"] = "json"
) -> dict:
    return await asyncio.to_thread(export_records, record_ids, format)
