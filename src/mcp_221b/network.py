"""Bounded HTTP fetching for public sources."""

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlsplit

import httpx


class _SecretRequestFilter(logging.Filter):
    def filter(self, record):
        # HTTPX logs request URLs at INFO, including provider query-string keys.
        if "key=" in record.getMessage().lower():
            record.msg = "Authenticated HTTP request (URL omitted)."
            record.args = ()
        return True


_secret_filter = _SecretRequestFilter()


class FetchError(Exception):
    def __init__(self, message: str, status: str = "error"):
        super().__init__(message)
        self.status = status


async def validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Provide an absolute HTTP or HTTPS URL.")
    if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
        raise ValueError("URL credentials and nonstandard ports are not supported.")
    try:
        addresses = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(
                parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
            ),
            timeout=10,
        )
    except (OSError, TimeoutError) as exc:
        raise FetchError("Could not resolve the source hostname.") from exc
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Only public internet addresses are supported.")


class Network:
    def __init__(self):
        for name in (
            "httpx",
            "httpcore.connection",
            "httpcore.http11",
            "httpcore.http2",
            "httpcore.proxy",
            "httpcore.socks",
        ):
            logging.getLogger(name).addFilter(_secret_filter)
        self.client = httpx.AsyncClient(
            timeout=20,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "221b-mcp/0.1 (+public-source-research)"},
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        self.slots = asyncio.Semaphore(5)

    async def close(self):
        await self.client.aclose()

    async def get(
        self, url: str, *, params=None, headers=None, allow_redirects: bool = True
    ) -> httpx.Response:
        async with self.slots:
            try:
                async with asyncio.timeout(45):
                    for _ in range(6):
                        await validate_public_url(url)
                        async with self.client.stream(
                            "GET", url, params=params, headers=headers
                        ) as response:
                            if response.is_redirect:
                                if not allow_redirects:
                                    raise FetchError("Source returned an unexpected redirect.")
                                location = response.headers.get("location")
                                if not location:
                                    raise FetchError("Redirect has no destination.")
                                url = urljoin(str(response.url), location)
                                # Never forward a provider credential to a redirect destination.
                                params, headers = None, None
                                continue
                            if response.status_code >= 400:
                                status = (
                                    "blocked"
                                    if response.status_code in {401, 403, 429}
                                    else "not_found"
                                    if response.status_code == 404
                                    else "error"
                                )
                                raise FetchError(
                                    f"Source returned HTTP {response.status_code}.", status
                                )
                            body = bytearray()
                            async for chunk in response.aiter_bytes():
                                body.extend(chunk)
                                if len(body) > 2_000_000:
                                    raise FetchError("Source response exceeds the 2 MB limit.")
                            return httpx.Response(
                                response.status_code,
                                headers={
                                    key: value
                                    for key, value in response.headers.items()
                                    if key not in {"content-encoding", "content-length"}
                                },
                                content=bytes(body),
                                request=response.request,
                            )
                    raise FetchError("Too many redirects.")
            except (httpx.HTTPError, TimeoutError) as exc:
                raise FetchError("Source request failed or timed out.") from exc
