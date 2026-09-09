"""Implementation of search_web."""

import asyncio
import json
import sys

from mcp_221b.config import brave_key, search_provider
from mcp_221b.evidence import Finding, Result
from mcp_221b.network import FetchError, Network


class SearchWeb:
    def __init__(self, network: Network):
        self.network = network
        self.brave_slot = asyncio.Semaphore(1)
        self.keyless_slot = asyncio.Semaphore(1)

    async def search_web(self, query: str, limit: int = 10, provider: str | None = None) -> Result:
        if not query.strip() or len(query) > 600 or len(query.split()) > 75:
            raise ValueError("Query must contain 1–600 characters and at most 75 words.")
        if not 1 <= limit <= 20:
            raise ValueError("Limit must be between 1 and 20.")
        selected = provider if provider is not None else search_provider()
        if selected == "keyless":
            return await self._search_keyless(query, limit)
        if selected != "brave":
            raise ValueError("Search provider must be keyless or brave.")
        key = await asyncio.to_thread(brave_key)
        if not key:
            raise ValueError("Brave needs a key. Run 221b-mcp init or set BRAVE_API_KEY_FILE.")
        async with self.brave_slot:
            try:
                response = await self.network.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": limit},
                    headers={"X-Subscription-Token": key},
                )
            finally:
                # Conservative baseline; HTTP 429 is reported rather than retried automatically.
                await asyncio.sleep(1)
        payload = response.json()
        findings = [
            Finding(
                source=item["url"],
                status="found",
                evidence={
                    "provider": "brave",
                    "title": item.get("title", ""),
                    "snippet": item.get("description", ""),
                },
            )
            for item in payload.get("web", {}).get("results", [])[:limit]
        ]
        return Result(
            tool="search_web",
            query=query,
            findings=findings,
            notes=["Provider: Brave API. Search snippets are unverified leads."],
        )

    async def _search_keyless(self, query: str, limit: int) -> Result:
        async with self.keyless_slot:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "mcp_221b.search_worker",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                output, _ = await asyncio.wait_for(
                    process.communicate(json.dumps({"query": query, "limit": limit}).encode()),
                    timeout=45,
                )
            except (TimeoutError, asyncio.CancelledError):
                if process.returncode is None:
                    process.kill()
                await process.wait()
                raise
            finally:
                await asyncio.sleep(1)
        if process.returncode:
            raise FetchError("Keyless search worker failed.")
        payload = json.loads(output)
        if "error" in payload:
            raise FetchError(payload["error"], payload["status"])
        return Result(
            tool="search_web",
            query=query,
            findings=[
                Finding(
                    source=row["url"],
                    status="found",
                    evidence={
                        "provider": "keyless",
                        "backend": "ddgs:auto",
                        "title": row["title"],
                        "snippet": row["snippet"],
                    },
                )
                for row in payload["results"][:limit]
            ],
            notes=[
                "Provider: keyless DDGS metasearch with automatic engine selection.",
                "Individual engine attribution is not supplied by this adapter.",
                "Snippets are unverified leads. Empty results do not prove absence.",
            ],
        )
