"""Read Shodan's indexed host and service observations."""

import asyncio
import ipaddress
from urllib.parse import quote

from mcp_221b.credentials import load_shodan_key
from mcp_221b.evidence import Finding, Result
from mcp_221b.network import FetchError, Network

API = "https://api.shodan.io"
NOTES = ["Shodan observations are historical evidence, not a live connectivity check."]
FIELDS = (
    "org",
    "isp",
    "asn",
    "hostnames",
    "domains",
    "os",
    "ports",
    "tags",
    "country_name",
    "country_code",
    "city",
    "last_update",
    "port",
    "transport",
    "product",
    "version",
    "timestamp",
    "cpe",
    "cpe23",
)


def _ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
        if not address.is_global or "%" in value:
            raise ValueError
        return str(address)
    except ValueError:
        raise ValueError("Provide a public IP address, without a scheme or path.") from None


def _observation(item: dict) -> dict:
    evidence = {field: item[field] for field in FIELDS if field in item}
    if isinstance(item.get("location"), dict):
        evidence["location"] = {
            field: item["location"][field]
            for field in ("country_name", "country_code", "city")
            if field in item["location"]
        }
    banner = item.get("data")
    if isinstance(banner, str):
        evidence["banner"] = banner[:2000]
        evidence["banner_truncated"] = len(banner) > 2000
    return evidence


class Shodan:
    def __init__(self, network: Network):
        self.network = network
        self.slot = asyncio.Semaphore(1)

    async def _request(self, path: str, **params) -> dict:
        key = await asyncio.to_thread(load_shodan_key)
        if not key:
            raise ValueError("Shodan needs a key. Run 221b-mcp init or set SHODAN_API_KEY_FILE.")
        async with self.slot:
            try:
                response = await self.network.get(
                    f"{API}{path}", params={"key": key, **params}, allow_redirects=False
                )
            finally:
                # Shared across both tools; failures are surfaced without automatic retries.
                await asyncio.sleep(1)
        try:
            payload = response.json()
        except ValueError:
            raise FetchError("Invalid Shodan response.") from None
        if not isinstance(payload, dict):
            raise FetchError("Invalid Shodan response.")
        if "error" in payload:
            # Provider error text can contain request details; never relay it verbatim.
            raise FetchError("Shodan could not complete the request; check API access and credits.")
        return payload

    async def lookup_shodan_host(self, ip: str) -> Result:
        ip = _ip(ip)
        source = f"https://www.shodan.io/host/{ip}"
        try:
            payload = await self._request(f"/shodan/host/{ip}", history="false", minify="false")
            services = payload.get("data")
            if payload.get("ip_str") != ip or not isinstance(services, list):
                raise FetchError("Invalid Shodan host response.")
            if not all(isinstance(item, dict) for item in services):
                raise FetchError("Invalid Shodan service response.")
            evidence = {
                "provider": "shodan",
                "ip": ip,
                **_observation(payload),
                "services": [_observation(item) for item in services[:100]],
                "services_returned": min(len(services), 100),
                "services_truncated": len(services) > 100,
            }
            finding = Finding(source=source, status="found", evidence=evidence)
        except FetchError as exc:
            finding = Finding(source=source, status=exc.status, evidence={"message": str(exc)})
        return Result(tool="lookup_shodan_host", query=ip, findings=[finding], notes=NOTES)

    async def search_shodan(self, query: str, limit: int = 10, page: int = 1) -> Result:
        if not query.strip() or len(query) > 600:
            raise ValueError("Query must contain 1–600 characters.")
        if not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100.")
        if page < 1:
            raise ValueError("Page must be at least 1.")
        source = f"https://www.shodan.io/search?query={quote(query, safe='')}"
        notes = [*NOTES, "Search may consume query credits. Only the requested page is fetched."]
        try:
            payload = await self._request(
                "/shodan/host/search", query=query, page=page, minify="true"
            )
            matches, total = payload.get("matches"), payload.get("total")
            if not isinstance(matches, list) or type(total) is not int or total < 0:
                raise FetchError("Invalid Shodan search response.")
            findings = []
            for item in matches[:limit]:
                if not isinstance(item, dict) or not isinstance(item.get("ip_str"), str):
                    raise FetchError("Invalid Shodan service response.")
                try:
                    ip = _ip(item["ip_str"])
                except ValueError:
                    raise FetchError("Invalid Shodan service address.") from None
                findings.append(
                    Finding(
                        source=f"https://www.shodan.io/host/{ip}",
                        status="found",
                        evidence={"provider": "shodan", "ip": ip, **_observation(item)},
                    )
                )
            notes.append(
                f"Total matching services: {total}; page: {page}; returned: {len(findings)}; "
                f"page results omitted by limit: {max(0, len(matches) - limit)}. "
                "Pages contain up to 100 services; limit caps output, not API credit usage."
            )
            if not matches:
                notes.append("No matching services on this page; this does not prove absence.")
        except FetchError as exc:
            findings = [Finding(source=source, status=exc.status, evidence={"message": str(exc)})]
        return Result(tool="search_shodan", query=query, findings=findings, notes=notes)
