"""Implementation of search_archives."""

from urllib.parse import urlsplit

from mcp_221b.evidence import Finding, Result
from mcp_221b.network import Network


class SearchArchives:
    def __init__(self, network: Network):
        self.network = network

    async def search_archives(self, url: str, limit: int = 20) -> Result:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("Provide an absolute HTTP or HTTPS URL without credentials.")
        if not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100.")
        response = await self.network.get(
            "https://web.archive.org/cdx/search/cdx",
            params={
                "url": url,
                "matchType": "exact",
                "output": "json",
                "fl": "timestamp,original,statuscode,mimetype,digest",
                "filter": "statuscode:200",
                "collapse": "digest",
                "limit": limit,
            },
        )
        rows = response.json()
        findings = []
        for row in rows[1:]:
            capture = dict(zip(rows[0], row, strict=True))
            findings.append(
                Finding(
                    source=f"https://web.archive.org/web/{capture['timestamp']}/{capture['original']}",
                    status="found",
                    evidence=capture,
                )
            )
        return Result(
            tool="search_archives",
            query=url,
            findings=findings,
            notes=[
                "Exact URL lookup, limited and deduplicated by digest; may omit newer captures.",
                "Capture time differs from retrieval time. Archive hits do not verify identity.",
            ],
        )
