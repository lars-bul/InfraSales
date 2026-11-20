"""The `http` fetcher's own contract; its rules are tested through the scrape job."""

from collections.abc import AsyncGenerator, Iterable
from typing import override

import httpcore2
import httpx2
import pytest

from infrasales.fetch.fetcher import StatusError, Validators
from infrasales.fetch.http import (
    USER_AGENT,
    CheckedBackend,
    HttpFetcher,
    Network,
    UnreachableError,
    UnsafeUrlError,
    check_public,
    http_client,
    resolve_host,
)
from tests.scrape.support import PUBLIC_IP, FakeWeb

pytestmark = pytest.mark.anyio

PAGE = "https://news.test/page"


@pytest.fixture
async def fetcher_on(web: FakeWeb) -> AsyncGenerator[HttpFetcher]:
    async with http_client(web.network()) as client:
        yield HttpFetcher(client)


@pytest.fixture
def web() -> FakeWeb:
    return FakeWeb()


async def test_a_conditional_request_answered_304_is_an_answer(
    web: FakeWeb, fetcher_on: HttpFetcher
) -> None:
    def unchanged(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["if-none-match"] == '"v1"'
        assert request.headers["if-modified-since"] == "Fri, 16 Oct 2026 05:00:00 GMT"
        assert request.headers["user-agent"] == USER_AGENT
        return httpx2.Response(304, headers={"etag": '"v1"'})

    web.route(PAGE, unchanged)

    response = await fetcher_on.fetch(PAGE, Validators('"v1"', "Fri, 16 Oct 2026 05:00:00 GMT"))

    assert (response.not_modified, response.content) == (True, b"")
    assert response.validators == Validators('"v1"', None)
    assert (response.media_type, response.charset) == ("", None)


async def test_an_error_status_raises_with_the_response(
    web: FakeWeb, fetcher_on: HttpFetcher
) -> None:
    web.serve(PAGE, "Too many requests, slow down", status=429, media_type="text/html")

    with pytest.raises(StatusError) as raised:
        await fetcher_on.fetch(PAGE)

    assert raised.value.reason == "http 429"  # a busy site: no wall
    assert raised.value.response.content == b"Too many requests, slow down"


async def test_a_host_that_does_not_answer_is_unreachable() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        msg = "connection refused"
        raise httpx2.ConnectError(msg, request=request)

    network = Network(httpx2.MockTransport(refuse), FakeWeb().resolve)
    async with http_client(network) as client:
        with pytest.raises(UnreachableError) as raised:
            await HttpFetcher(client).fetch(PAGE)

    assert raised.value.reason == "unreachable"


async def test_too_many_redirects_are_unreachable(web: FakeWeb, fetcher_on: HttpFetcher) -> None:
    web.redirect(PAGE, PAGE)

    with pytest.raises(UnreachableError):
        await fetcher_on.fetch(PAGE)


async def test_a_broken_link_is_an_unsafe_address(web: FakeWeb, fetcher_on: HttpFetcher) -> None:
    """Httpx refuses to build the request (`InvalidURL`, no `HTTPError`): no address at all."""
    with pytest.raises(UnsafeUrlError) as raised:
        await fetcher_on.fetch("http://[::1/broken")

    assert raised.value.reason == "unsafe address"
    assert web.requests == []


@pytest.mark.parametrize(
    "addresses",
    [
        [],
        ["fe80::1%eth0"],
        ["not-an-address"],
        ["::127.0.0.1"],  # IPv4-compatible: loopback
        ["::a9fe:a9fe"],  # IPv4-compatible: 169.254.169.254, a cloud's instance metadata
        ["64:ff9b::a9fe:a9fe"],  # the same, behind a NAT64 gateway
        ["64:ff9b::a00:5"],  # 10.0.0.5, a private network's, behind NAT64
        [PUBLIC_IP, "10.0.0.5"],  # one private address is one too many
    ],
)
async def test_hosts_without_public_addresses_are_refused(addresses: list[str]) -> None:
    async def resolve(_: str) -> list[str]:
        return addresses

    with pytest.raises(UnsafeUrlError, match="not public"):
        await check_public(PAGE, resolve)


async def test_the_system_resolver_answers_with_addresses() -> None:
    assert "127.0.0.1" in await resolve_host("localhost")


async def test_without_a_fake_resolver_tests_reach_no_host() -> None:
    """The real web is out of reach in tests (tests/conftest.py)."""
    async with http_client(Network()) as client:
        with pytest.raises(UnsafeUrlError, match="does not resolve"):
            await HttpFetcher(client).fetch("https://tiefbau-aktuell.test/feed/")


@pytest.mark.parametrize("address", [PUBLIC_IP, "64:ff9b::808:808", "2606:4700::1111"])
async def test_public_addresses_pass_ipv4_behind_nat64_too(address: str) -> None:
    async def resolve(_: str) -> list[str]:
        return [address]

    await check_public(PAGE, resolve)


OK = [b"HTTP/1.1 200 OK\r\n", b"Content-Type: text/plain\r\n", b"Content-Length: 2\r\n\r\n", b"ok"]


class Connections(httpcore2.AsyncMockBackend):
    """Connections answered `200 ok`; records the address each went to, refuses `refusing`."""

    def __init__(self, refusing: Iterable[str] = ()) -> None:
        super().__init__(OK)
        self.to: list[str] = []
        self._refusing = set(refusing)

    @override
    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore2.SOCKET_OPTION] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        self.to.append(host)
        if host in self._refusing:
            msg = "connection refused"
            raise httpcore2.ConnectError(msg)
        return await super().connect_tcp(host, port, timeout, local_address, socket_options)


async def fetch_through(connections: Connections, *answers: list[str]) -> bytes:
    """GET a page over (fake) connections, its host answering `answers` lookup by lookup."""
    lookups = iter(answers)

    async def resolve(_: str) -> list[str]:
        return next(lookups)

    async with http_client(Network(resolve=resolve, backend=connections)) as client:
        return (await HttpFetcher(client).fetch("http://news.test/page")).content


async def test_a_connection_goes_to_the_address_checked_for_it() -> None:
    connections = Connections()

    assert await fetch_through(connections, [PUBLIC_IP], [PUBLIC_IP]) == b"ok"
    assert connections.to == [PUBLIC_IP]  # not the host name: no second, unchecked lookup


async def test_a_host_answering_public_then_private_is_never_connected_to() -> None:
    """DNS rebinding: public for the request's check, the metadata address for its connection."""
    connections = Connections()

    with pytest.raises(UnsafeUrlError, match="not public"):
        await fetch_through(connections, [PUBLIC_IP], ["169.254.169.254"])

    assert connections.to == []


async def test_a_host_s_next_checked_address_is_tried_when_one_does_not_answer() -> None:
    connections = Connections(refusing=["2606:4700::1111"])
    addresses = ["2606:4700::1111", PUBLIC_IP]

    assert await fetch_through(connections, addresses, addresses) == b"ok"
    assert connections.to == addresses


async def test_the_checked_backend_waits_as_the_one_it_connects_through() -> None:
    await CheckedBackend(FakeWeb().resolve, Connections()).sleep(0)
