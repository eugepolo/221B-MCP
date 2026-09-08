"""Implementation of lookup_domain."""

import asyncio
import re
from urllib.parse import quote

import dns.asyncresolver
import dns.exception

from mcp_221b.evidence import Finding, Result
from mcp_221b.network import FetchError, Network


class LookupDomain:
    def __init__(self, network: Network):
        self.network = network

    async def lookup_domain(self, domain: str) -> Result:
        domain = domain.rstrip(".").encode("idna").decode("ascii").lower()
        if (
            len(domain) > 253
            or "." not in domain
            or not all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in domain.split(".")
            )
        ):
            raise ValueError("Provide a domain name, without a scheme or path.")
        resolver = dns.asyncresolver.Resolver()

        async def resolve(kind: str) -> Finding:
            source = f"dns:{domain}?type={kind}"
            try:
                answer = await resolver.resolve(domain, kind, lifetime=8)
                return Finding(
                    source=source,
                    status="found",
                    evidence={
                        "type": kind,
                        "records": [str(item) for item in answer],
                        "ttl": answer.rrset.ttl,
                    },
                )
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                return Finding(source=source, status="not_found", evidence={"type": kind})
            except dns.exception.DNSException:
                return Finding(
                    source=source, status="error", evidence={"message": "DNS query failed."}
                )

        async def rdap() -> Finding:
            source = f"https://rdap.org/domain/{quote(domain, safe='')}"
            try:
                response = await self.network.get(source)
                data = response.json()
                return Finding(
                    source=str(response.url),
                    status="found",
                    evidence={
                        key: data[key]
                        for key in (
                            "ldhName",
                            "handle",
                            "status",
                            "events",
                            "nameservers",
                            "entities",
                            "notices",
                        )
                        if key in data
                    },
                )
            except FetchError as exc:
                return Finding(source=source, status=exc.status, evidence={"message": str(exc)})
            except (ValueError, KeyError):
                return Finding(
                    source=source, status="error", evidence={"message": "Invalid RDAP response."}
                )

        findings = await asyncio.gather(
            *(resolve(k) for k in ("A", "AAAA", "MX", "NS", "TXT")), rdap()
        )
        return Result(
            tool="lookup_domain",
            query=domain,
            findings=list(findings),
            notes=["Registration may be redacted. DNS does not establish mailbox existence."],
        )
