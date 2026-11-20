"""Suggesting a Feed for a site's address: its feed if it has one, else its sitemap.

Ported from the draft branch `feat/core-foundation-scraper` (lars-bul). In this order:
the address itself is a feed or a sitemap; the page links its feed (`<link rel="alternate">`);
a feed at a usual path; a sitemap that robots.txt declares; a sitemap at a usual path. Every
request goes through the `http` fetcher (public addresses only, size-capped) and obeys
robots.txt, like the scrape's; requests to the site are paused, for a shorter while than the
scrape's: a suggestion is a dozen requests an admin waits for, not a run of hundreds.
Pages and feeds are parsed in a thread: the API shares its event loop with the worker.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast
from urllib.parse import urljoin, urlsplit

import feedparser
import lxml.etree
import lxml.html

from infrasales.core.text import stripped
from infrasales.feeds.lister import UnreadableFeedError
from infrasales.feeds.models import FeedKind
from infrasales.feeds.rss import is_feed
from infrasales.feeds.sitemap import parse_sitemap
from infrasales.fetch.fetcher import Fetcher, FetchError, Response
from infrasales.fetch.http import USER_AGENT, HttpFetcher, Network, http_client
from infrasales.fetch.pacing import Budget, Pacer
from infrasales.fetch.robots import RobotsCache, obey

PAUSE_SECONDS = 1.0  # between requests to the site; a longer Crawl-delay still counts
# For the whole suggestion: an admin is waiting. A site with neither a linked feed nor anything
# at the usual paths takes about 12 requests (robots.txt included), 1 s apart.
TIME_LIMIT_SECONDS = 20
FEED_TYPES = frozenset({"application/rss+xml", "application/atom+xml", "application/rdf+xml"})
COMMON_FEEDS = ("/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml", "/index.xml")
COMMON_SITEMAPS = ("/sitemap.xml", "/sitemap_index.xml", "/news-sitemap.xml")

type Sitemaps = Callable[[str], Awaitable[list[str]]]
"""The sitemaps a URL's robots.txt names."""


class NothingFoundError(Exception):
    """The site has neither a feed nor a sitemap InfraSales could find."""


@dataclass(frozen=True, slots=True)
class Found:
    name: str  # the site's (or feed's) title, else its host
    kind: FeedKind
    url: str  # the feed's or sitemap's address


async def suggest(url: str, network: Network) -> Found:
    """The Feed to add for the site at `url`, found within `TIME_LIMIT_SECONDS`.

    Raises `NothingFoundError`, `FetchError` if `url` itself cannot be read (`UnsafeUrlError`
    for a private address, `RobotsError` if robots.txt disallows it), `BlockedError` behind a
    bot wall, `TimeoutError` when time runs out, `OutOfTimeError` when the site's pauses
    would not end in time.
    """
    budget = Budget(TIME_LIMIT_SECONDS, network.clock, 1)
    budget.next_feed()
    async with asyncio.timeout(TIME_LIMIT_SECONDS), http_client(network) as client:
        pacer = Pacer(network.clock, budget, PAUSE_SECONDS)
        robots = obey(client, pacer, USER_AGENT, RobotsCache(network.clock))
        return await discover(HttpFetcher(client), url, robots.sitemaps)


async def discover(fetcher: Fetcher, url: str, sitemaps: Sitemaps) -> Found:
    """The feed first, then the sitemap; see the module's documentation for the order."""
    page = await fetcher.fetch(url)
    parts = urlsplit(page.final_url)
    host = parts.hostname or url
    if await asyncio.to_thread(is_feed, page.content):
        title = await asyncio.to_thread(_feed_title, page.content)
        return Found(title or host, FeedKind.RSS, page.final_url)
    if await asyncio.to_thread(_is_sitemap, page.content):
        return Found(host, FeedKind.SITEMAP, page.final_url)
    title, alternates = await asyncio.to_thread(_read_page, page)
    name = title or host
    origin = f"{parts.scheme}://{parts.netloc}"
    for candidate in dict.fromkeys([*alternates, *(origin + path for path in COMMON_FEEDS)]):
        if await _holds(fetcher, candidate, is_feed):
            return Found(name, FeedKind.RSS, candidate)
    declared = await sitemaps(page.final_url)
    for candidate in dict.fromkeys([*declared, *(origin + path for path in COMMON_SITEMAPS)]):
        if await _holds(fetcher, candidate, _is_sitemap):
            return Found(name, FeedKind.SITEMAP, candidate)
    raise NothingFoundError


async def _holds(fetcher: Fetcher, url: str, test: Callable[[bytes], bool]) -> bool:
    """Whether `url` answers with what `test` accepts; unreadable candidates hold nothing."""
    try:
        content = (await fetcher.fetch(url)).content
    except FetchError:
        return False
    return await asyncio.to_thread(test, content)


def _feed_title(content: bytes) -> str | None:
    return stripped(feedparser.parse(content).feed.get("title"))


def _read_page(page: Response) -> tuple[str | None, list[str]]:
    """An HTML page's title and the feeds it links (absolute addresses; unreadable ones left)."""
    try:
        doc = lxml.html.fromstring(page.content)
    except ValueError, lxml.etree.LxmlError:
        return None, []
    title = (doc.findtext(".//title") or "").strip()[:200] or None
    links = cast(
        "list[lxml.html.HtmlElement]",
        doc.xpath('//link[contains(@rel, "alternate")][@type][@href]'),
    )
    feeds = [
        address
        for link in links
        if link.get("type", "").lower() in FEED_TYPES
        and (address := _absolute(page.final_url, link.get("href", "")))
    ]
    return title, feeds


def _absolute(base: str, href: str) -> str | None:
    """`href` read against `base`; None if it is no address (`http://[::1/broken`)."""
    try:
        return urljoin(base, href)
    except ValueError:
        return None


def _is_sitemap(content: bytes) -> bool:
    """Whether `content` is a sitemap or sitemap index, as the `sitemap` Lister reads them."""
    try:
        parse_sitemap(content)
    except UnreadableFeedError:
        return False
    return True
