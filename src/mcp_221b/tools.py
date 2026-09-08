"""Public MCP tool signatures, descriptions, and explicit registration."""

import asyncio
from typing import Literal

from mcp.server.fastmcp import Context, FastMCP

from mcp_221b.evidence import Finding, Result, record
from mcp_221b.logging_setup import logged_tool
from mcp_221b.network import FetchError
from mcp_221b.tool_handlers.export_findings import export_findings as export_handler
from mcp_221b.username_presets import Depth


async def collect(ctx: Context, tool: str, query: str, **kwargs) -> dict:
    providers = ctx.request_context.lifespan_context
    try:
        result = await getattr(providers, tool)(query, **kwargs)
    except FetchError as exc:
        result = Result(
            tool=tool,
            query=query,
            findings=[Finding(source=tool, status=exc.status, evidence={"message": str(exc)})],
        )
    except TimeoutError:
        result = Result(
            tool=tool,
            query=query,
            findings=[
                Finding(source=tool, status="error", evidence={"message": "Operation timed out."})
            ],
        )
    return await asyncio.to_thread(record, result)


@logged_tool
async def search_username(
    username: str, ctx: Context, sites: list[str] | None = None, depth: Depth = "light"
) -> dict:
    """Find candidate accounts with local Sherlock.

    depth: light (default) checks 20 curated popular sites; dev checks developer platforms;
    complete requests all available sites, including adult sites, with a 10-minute deadline.
    Upstream false-positive exclusions apply. Explicit sites override the preset's selection.
    Requires the sherlock package extra. A match does not establish the owner's identity.
    """
    return await collect(ctx, "search_username", username, sites=sites, depth=depth)


@logged_tool
async def search_web(
    query: str,
    ctx: Context,
    limit: int = 10,
    provider: Literal["keyless", "brave"] | None = None,
) -> dict:
    """Find public mentions; defaults to keyless metasearch. Max 20 results.

    Supports search operators where the selected engines support them. Optional provider='brave'
    uses the Brave API and requires a key. Omit provider to use the configured default.
    """
    return await collect(ctx, "search_web", query, limit=limit, provider=provider)


@logged_tool
async def inspect_page(url: str, ctx: Context) -> dict:
    """Fetch a public HTML/text page and extract text, links and emails. No browser rendering."""
    return await collect(ctx, "inspect_page", url)


@logged_tool
async def lookup_domain(domain: str, ctx: Context) -> dict:
    """Look up A, AAAA, MX, NS and TXT DNS records, plus available RDAP registration data."""
    return await collect(ctx, "lookup_domain", domain)


@logged_tool
async def search_archives(url: str, ctx: Context, limit: int = 20) -> dict:
    """Find Wayback captures of an exact URL, deduplicated by digest. At most 100 captures."""
    return await collect(ctx, "search_archives", url, limit=limit)


@logged_tool
async def export_findings(
    record_ids: list[str], format: Literal["json", "markdown"] = "json"
) -> dict:
    """Export 1–100 existing evidence record IDs to a new local JSON or Markdown file."""
    return await export_handler(record_ids, format)


TOOLS = (search_username, search_web, inspect_page, lookup_domain, search_archives, export_findings)


def register_tools(mcp: FastMCP) -> None:
    """Register exactly the public tool list on a server instance."""
    for tool in TOOLS:
        mcp.tool()(tool)
