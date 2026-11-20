"""The `http` fetcher: size-capped GET requests that never reach private networks.

Every request is checked, each redirect hop included: http(s) only, and every address the host
resolves to must be public. A connection goes to exactly an address that was checked for it
(`CheckedBackend`): looking the host up again to connect would let a name answer "public" for
the check and `169.254.169.254` for the connection (DNS rebinding). Tests pass a `Network` with
an in-process transport, fake DNS and fake time; the checks stay on. robots.txt and the pauses
are hooked into the client by `infrasales.fetch.fetchers`; a bot wall's challenge raises
`BlockedError`, a block answer `RefusedError` (`infrasales.fetch.walls`).
"""

import asyncio
import contextlib
import ipaddress
import socket
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast, override
from urllib.parse import urlsplit

import httpcore2
import httpx2

from infrasales.fetch.fetcher import (
    KEPT_HEADERS,
    ROBOTS_DECISION,
    BlockedError,
    FetchError,
    RefusedError,
    Response,
    StatusError,
    Validators,
)
from infrasales.fetch.pacing import REAL_TIME, Clock
from infrasales.fetch.walls import access_page, challenge, refused

USER_AGENT = "InfraSalesBot/1.0"
MAX_BYTES = 10 << 20  # 10 MiB: more is no article
MAX_REDIRECTS = 5
_TIMEOUT_SECONDS = 15
# IPv6 spellings of an IPv4 address that `is_global` takes for public ones: checked as IPv4.
_EMBEDDING_IPV4 = (
    ipaddress.IPv6Network("::/96"),  # IPv4-compatible (RFC 4291 §2.5.5.1, deprecated): ::a.b.c.d
    ipaddress.IPv6Network("64:ff9b::/96"),  # NAT64's well-known prefix (RFC 6052)
)

type Resolve = Callable[[str], Awaitable[Sequence[str]]]
"""The IP addresses a host name resolves to; raises `OSError` if it does not resolve."""


class UnsafeUrlError(FetchError):
    """The URL is no http(s) address of a public host."""

    reason = "unsafe address"


class ResponseTooLargeError(FetchError):
    """The response body exceeds the size cap."""

    reason = "too large"


class UnreachableError(FetchError):
    """No answer: the connection failed, timed out, or redirected too often."""

    reason = "unreachable"


async def resolve_host(host: str) -> list[str]:
    """The system resolver's addresses for `host`."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


@dataclass(frozen=True, slots=True)
class Network:
    """How fetchers reach the web: the real one, or a fake one (tests).

    Tests pass an in-process transport, fake DNS, and fake time (pauses then cost nothing);
    or, to test connecting itself, a fake `backend` (what `CheckedBackend` connects through).
    """

    transport: httpx2.AsyncBaseTransport | None = None  # None: the real one, `CheckedBackend`'s
    resolve: Resolve | None = None  # None: the system resolver (`resolve_host`)
    clock: Clock = REAL_TIME
    backend: httpcore2.AsyncNetworkBackend | None = None  # None: real connections (AnyIO)


async def check_public(url: str, resolve: Resolve) -> None:
    """Refuse anything but http(s) to public addresses, before a request is sent.

    The connection is checked again, by the address it goes to (`CheckedBackend`).
    """
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        msg = f"not an http(s) address: {url!r}"
        raise UnsafeUrlError(msg)
    await public_addresses(parts.hostname, resolve)


async def public_addresses(host: str, resolve: Resolve) -> list[str]:
    """The addresses `host` resolves to; raises `UnsafeUrlError` unless every one is public."""
    try:
        addresses = list(await resolve(host))
    except OSError as error:
        msg = f"host does not resolve: {host}"
        raise UnsafeUrlError(msg) from error
    if not addresses or not all(_public(address) for address in addresses):
        msg = f"host is not public: {host}"
        raise UnsafeUrlError(msg)
    return addresses


def _public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.partition("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and any(ip in net for net in _EMBEDDING_IPV4):
        ip = ipaddress.IPv4Address(int(ip) & 0xFFFF_FFFF)  # `::127.0.0.1` is 127.0.0.1
    return ip.is_global


class CheckedBackend(httpcore2.AsyncNetworkBackend):
    """Connects only to an address it checked: the host is looked up once, for its connection.

    TLS still checks the certificate against the host name: httpcore hands that to `start_tls`
    itself (`server_hostname`), whatever address was connected to.
    """

    def __init__(self, resolve: Resolve, backend: httpcore2.AsyncNetworkBackend) -> None:
        self._resolve, self._backend = resolve, backend

    @override
    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore2.SOCKET_OPTION] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        """Connect to the first of the host's (public) addresses that answers."""
        *others, last = await public_addresses(host, self._resolve)

        async def connect(address: str) -> httpcore2.AsyncNetworkStream:
            return await self._backend.connect_tcp(
                address, port, timeout, local_address, socket_options
            )

        for address in others:
            with contextlib.suppress(httpcore2.ConnectError, httpcore2.ConnectTimeout):
                return await connect(address)
        return await connect(last)

    @override
    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _CheckedTransport(httpx2.AsyncHTTPTransport):
    """httpx's transport, its connections made by a `CheckedBackend`.

    No proxy, whatever the environment says: a proxy would look the host up itself, unchecked.
    """

    def __init__(self, backend: CheckedBackend) -> None:
        super().__init__(trust_env=False)
        self._pool = httpcore2.AsyncConnectionPool(
            ssl_context=httpx2.create_ssl_context(),
            max_connections=100,  # httpx's defaults
            max_keepalive_connections=20,
            keepalive_expiry=5,
            network_backend=backend,
        )


def _anyio() -> httpcore2.AsyncNetworkBackend:
    """Real connections. httpcore2 declares the class only if anyio is installed (it is)."""
    return cast("httpcore2.AsyncNetworkBackend", httpcore2.AnyIOBackend())


@asynccontextmanager
async def http_client(network: Network) -> AsyncGenerator[httpx2.AsyncClient]:
    """A client that checks every request, redirects included, before it is sent."""
    resolve = network.resolve or resolve_host

    async def guard(request: httpx2.Request) -> None:
        await check_public(str(request.url), resolve)

    backend = CheckedBackend(resolve, network.backend or _anyio())
    async with httpx2.AsyncClient(
        transport=network.transport or _CheckedTransport(backend),
        timeout=_TIMEOUT_SECONDS,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en,de;q=0.8"},
        event_hooks={"request": [guard]},
    ) as client:
        yield client


class HttpFetcher:
    def __init__(self, client: httpx2.AsyncClient, max_bytes: int = MAX_BYTES) -> None:
        """Fetch through `client` (from `http_client`), at most `max_bytes` of body."""
        self._client = client
        self._max_bytes = max_bytes

    async def fetch(self, url: str, validators: Validators | None = None) -> Response:
        """GET `url`, conditionally when given validators; 2xx and 304 are answers."""
        validators = validators or Validators()
        headers = {"If-None-Match": validators.etag} if validators.etag else {}
        if validators.last_modified:
            headers["If-Modified-Since"] = validators.last_modified
        try:
            async with self._client.stream("GET", url, headers=headers) as response:
                kept = {
                    name: response.headers[name]
                    for name in KEPT_HEADERS
                    if name in response.headers
                }
                body = b"" if response.status_code == 304 else await self._body(response)  # noqa: PLR2004
                walled = access_page(str(response.url))
                if walled or challenge(response.status_code, response.headers, body):
                    raise BlockedError(str(response.url), response.status_code)
        except httpx2.HTTPError as error:
            raise UnreachableError(str(error)) from error
        except httpx2.InvalidURL as error:  # `http://[::1/broken`: no address at all
            raise UnsafeUrlError(str(error)) from error
        robots = response.request.extensions.get(ROBOTS_DECISION, "not checked")
        answer = Response(url, str(response.url), response.status_code, kept, body, robots=robots)
        if refused(answer.status):
            raise RefusedError(answer)
        if not (200 <= answer.status < 300 or answer.not_modified):  # noqa: PLR2004
            raise StatusError(answer)
        return answer

    async def _body(self, response: httpx2.Response) -> bytes:
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self._max_bytes:
            raise ResponseTooLargeError(str(response.url))
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > self._max_bytes:
                raise ResponseTooLargeError(str(response.url))
        return bytes(body)
