"""Bounded HTTP fetching for public sources."""

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlsplit

import httpcore
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
    await resolve_public_addresses(
        parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    )


async def resolve_public_addresses(host: str, port: int) -> list[str]:
    try:
        addresses = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=10,
        )
    except (OSError, TimeoutError) as exc:
        raise FetchError("Could not resolve the source hostname.") from exc
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Only public internet addresses are supported.")

    return list(dict.fromkeys(a[4][0] for a in addresses))


class PublicNetworkBackend(httpcore.AnyIOBackend):
    """Resolve once per connection and pass only validated IP literals to the socket layer."""

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        async with asyncio.timeout(timeout):
            addresses = await resolve_public_addresses(host, port)
            for index, address in enumerate(addresses):
                try:
                    return await super().connect_tcp(
                        address,
                        port,
                        timeout=timeout,
                        local_address=local_address,
                        socket_options=socket_options,
                    )
                except (httpcore.ConnectError, httpcore.ConnectTimeout):
                    if index == len(addresses) - 1:
                        raise


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        async for chunk in self.stream:
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class PublicHTTPTransport(httpx.AsyncBaseTransport):
    """Keep origin-based pooling and TLS verification while controlling DNS at connect time."""

    def __init__(self):
        self.pool = httpcore.AsyncConnectionPool(
            network_backend=PublicNetworkBackend(),
            max_connections=10,
            max_keepalive_connections=5,
        )

    async def handle_async_request(self, request):
        response = await self.pool.handle_async_request(
            httpcore.Request(
                method=request.method,
                url=httpcore.URL(
                    scheme=request.url.raw_scheme,
                    host=request.url.raw_host,
                    port=request.url.port,
                    target=request.url.raw_path,
                ),
                headers=request.headers.raw,
                content=request.stream,
                extensions=request.extensions,
            )
        )
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=_ResponseStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self):
        await self.pool.aclose()


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
            transport=PublicHTTPTransport(),
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
            except (
                httpx.HTTPError,
                httpcore.NetworkError,
                httpcore.ProtocolError,
                httpcore.TimeoutException,
                TimeoutError,
            ) as exc:
                raise FetchError("Source request failed or timed out.") from exc
