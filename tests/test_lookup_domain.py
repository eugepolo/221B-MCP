from unittest.mock import AsyncMock

from mcp_221b.network import FetchError
from mcp_221b.tool_handlers.lookup_domain import LookupDomain


async def test_domain_partial_failures_preserve_dns_evidence(monkeypatch):
    import dns.resolver

    class Answer(list):
        class rrset:
            ttl = 300

    async def resolve(domain, kind, lifetime):
        if kind == "A":
            return Answer(["93.184.216.34"])
        raise dns.resolver.NoAnswer

    monkeypatch.setattr("dns.asyncresolver.Resolver.resolve", AsyncMock(side_effect=resolve))
    network = AsyncMock()
    network.get.side_effect = FetchError("Rate limited", "blocked")
    result = await LookupDomain(network).lookup_domain("Example.org")
    assert result.query == "example.org"
    assert result.findings[0].evidence["records"] == ["93.184.216.34"]
    assert result.findings[-1].status == "blocked"
    assert result.findings[1].status == "not_found"
