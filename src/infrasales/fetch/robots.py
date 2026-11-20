"""robots.txt (RFC 9309): what InfraSales' bot may fetch, and how slowly. Never skipped.

`obey` hooks into an HTTP client so that every request it sends, each redirect hop included,
first asks the host's robots.txt (fetched through the same client: public addresses only,
paced) and then waits for the host's pause (`infrasales.fetch.pacing`). Rules are matched by
Scrapy's parser, Protego (wildcards, `Allow`/`Disallow` precedence, `Crawl-delay`).

A host's robots.txt is fetched once a day: a `RobotsCache` keeps it across runs for 24 hours,
the longest RFC 9309 §2.4 lets a crawler use a cached copy. An unreachable one is kept for the
run only: the next run asks again.

How a robots.txt answer is read (RFC 9309 §2.3.1):

- `2xx`: its rules (the first 500 KiB, the least the RFC lets a crawler read);
- `4xx` (but `429`): there is none, everything is allowed;
- `429`, `5xx`, no answer, an unsafe redirect: unreachable, nothing is allowed;
- a bot wall: the site blocks the bot (`BlockedError`).
"""

from dataclasses import dataclass

import httpx2
from protego import Protego

from infrasales.fetch.fetcher import ROBOTS_DECISION, BlockedError, FetchError
from infrasales.fetch.pacing import REAL_TIME, Clock, Pacer
from infrasales.fetch.walls import access_page, challenge

MAX_ROBOTS_BYTES = 500 << 10
CACHE_SECONDS = 24 * 60 * 60  # RFC 9309 §2.4: a cached robots.txt is used for a day at most
_FETCHING_ROBOTS = "infrasales.robots_txt"  # request extension: a request for robots.txt itself
_CLIENT_ERROR, _SERVER_ERROR, _TOO_MANY = 400, 500, 429


class RobotsError(FetchError):
    """robots.txt does not allow the URL: it is not fetched."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"{reason}: {url}")
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Rules:
    """A host's robots.txt, as read: rules, or allow all (`parser` None), or allow nothing."""

    decision: str  # what an allowed request's `metadata.json` says; or why nothing is allowed
    parser: Protego | None = None
    allowed: bool = True  # without a parser: whether everything, or nothing, is allowed

    def allows(self, url: str, agent: str) -> bool:
        return self.parser.can_fetch(url, agent) if self.parser else self.allowed

    def delay(self, agent: str) -> float | None:
        return self.parser.crawl_delay(agent) if self.parser else None


NONE = Rules("allowed: no robots.txt")
UNREACHABLE = Rules("robots.txt unreachable", allowed=False)

type Origin = tuple[str, str, int | None]  # scheme, host, port: robots.txt is per origin


class RobotsCache:
    """Hosts' robots.txt as read, kept for `CACHE_SECONDS` (one per process: across runs)."""

    def __init__(self, clock: Clock = REAL_TIME, seconds: float = CACHE_SECONDS) -> None:
        self._clock, self._seconds = clock, seconds
        self._rules: dict[Origin, tuple[float, Rules]] = {}  # origin → (expires at, rules)

    def get(self, origin: Origin) -> Rules | None:
        """The origin's rules, if read less than `seconds` ago."""
        expires, rules = self._rules.get(origin, (0.0, None))
        return rules if self._clock.monotonic() < expires else None

    def keep(self, origin: Origin, rules: Rules) -> None:
        """Keep `rules` as just read; expired ones are dropped (one host per HN story adds up)."""
        now = self._clock.monotonic()
        self._rules = {key: kept for key, kept in self._rules.items() if now < kept[0]}
        self._rules[origin] = (now + self._seconds, rules)


class Robots:
    """The robots.txt of every host one client reaches, read once each, and its pacer."""

    def __init__(
        self, client: httpx2.AsyncClient, pacer: Pacer, agent: str, cache: RobotsCache
    ) -> None:
        self._client, self._pacer, self._agent, self._cache = client, pacer, agent, cache
        self._rules: dict[Origin, Rules] = {}  # this client's: unreachable ones included

    async def before(self, request: httpx2.Request) -> None:
        """A request hook: refuse what robots.txt disallows, then wait for the host's pause."""
        if request.extensions.get(_FETCHING_ROBOTS):
            await self._pacer.wait(request.url.host)
            return
        rules = await self.rules(request.url)
        if not rules.allows(str(request.url), self._agent):
            reason = "disallowed by robots.txt" if rules.allowed else rules.decision
            raise RobotsError(str(request.url), reason)
        request.extensions[ROBOTS_DECISION] = rules.decision
        await self._pacer.wait(request.url.host, rules.delay(self._agent))

    async def after(self, response: httpx2.Response) -> None:
        """A response hook: the host's pause starts."""
        self._pacer.done(response.request.url.host)

    async def sitemaps(self, url: str) -> list[str]:
        """The sitemaps the robots.txt of `url`'s origin names (its `Sitemap:` lines)."""
        rules = await self.rules(httpx2.URL(url))
        return list(rules.parser.sitemaps) if rules.parser else []

    async def rules(self, url: httpx2.URL) -> Rules:
        origin = (url.scheme, url.host, url.port)
        if origin not in self._rules:
            rules = self._cache.get(origin)
            if rules is None:
                rules = await self._read(url.copy_with(path="/robots.txt", query=None))
                if rules is not UNREACHABLE:
                    self._cache.keep(origin, rules)
            self._rules[origin] = rules
        return self._rules[origin]

    async def _read(self, url: httpx2.URL) -> Rules:
        try:
            async with self._client.stream(
                "GET", url, extensions={_FETCHING_ROBOTS: True}
            ) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) >= MAX_ROBOTS_BYTES:
                        break
        except httpx2.HTTPError, FetchError:  # no answer, redirected too often, or unsafely
            return UNREACHABLE
        status = response.status_code
        if access_page(str(response.url)) or challenge(status, response.headers, bytes(body)):
            raise BlockedError(str(url), status)
        if 200 <= status < 300:  # noqa: PLR2004
            text = bytes(body[:MAX_ROBOTS_BYTES]).decode("utf-8", errors="replace")
            return Rules("allowed", Protego.parse(text))
        if _CLIENT_ERROR <= status < _SERVER_ERROR and status != _TOO_MANY:
            return NONE
        return UNREACHABLE


def obey(client: httpx2.AsyncClient, pacer: Pacer, agent: str, cache: RobotsCache) -> Robots:
    """Make `client` obey robots.txt and pace its requests, after its other request hooks."""
    robots = Robots(client, pacer, agent, cache)
    client.event_hooks["request"].append(robots.before)
    client.event_hooks["response"].append(robots.after)
    return robots
