"""The `sitemap` Lister: the newest entries of a site's sitemap, for sites without a feed.

A Feed's address is a sitemap or a sitemap index (`.xml` or `.xml.gz`). Of an index, only the
newest child sitemaps are read (by their `lastmod`). Entries are dated by their news sitemap
`publication_date`, else `lastmod`; listed are those younger than `MAX_AGE`, newest first,
at most `MAX_ITEMS` (undated ones last), so a first run never fetches a site's whole archive.
Anything that is no sitemap (malformed XML, another document, a DOCTYPE, an index inside an
index, more than the size cap unpacked) fails the Feed.

Ported from the draft branch `feat/core-foundation-scraper` (lars-bul).
"""

import asyncio
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import lxml.etree

from infrasales.core.dates import parse_date
from infrasales.feeds.lister import MAX_ITEMS, Item, ListerSettings, UnreadableFeedError
from infrasales.feeds.models import Feed
from infrasales.fetch.fetcher import Fetcher
from infrasales.fetch.http import MAX_BYTES

MAX_AGE = timedelta(days=30)  # older entries are archive: a first run must not fetch it all
MAX_CHILD_SITEMAPS = 3  # of an index, the newest: they hold the new entries
_EPOCH = datetime.min.replace(tzinfo=UTC)


class SitemapSettings(ListerSettings):
    """A `sitemap` Feed needs nothing but its address (a sitemap or a sitemap index)."""


@dataclass(frozen=True, slots=True)
class Sitemap:
    index: bool  # a sitemap index: its entries are sitemaps
    entries: list[Item]


class SitemapLister:
    settings = SitemapSettings

    async def list(self, feed: Feed, fetcher: Fetcher) -> list[Item]:
        response = await fetcher.fetch(feed.url)
        sitemap = await read_sitemap(response.content)
        entries = await _children(fetcher, sitemap) if sitemap.index else sitemap.entries
        return _newest(entries, since=response.fetched_at - MAX_AGE)[:MAX_ITEMS]


async def _children(fetcher: Fetcher, index: Sitemap) -> list[Item]:
    """The entries of an index's newest sitemaps; one that cannot be read fails the Feed."""
    entries: list[Item] = []
    for child in _newest(index.entries)[:MAX_CHILD_SITEMAPS]:
        sitemap = await read_sitemap((await fetcher.fetch(child.url)).content)
        if sitemap.index:
            msg = f"a sitemap index inside a sitemap index: {child.url}"
            raise UnreadableFeedError(msg)
        entries += sitemap.entries
    return entries


def _newest(entries: list[Item], *, since: datetime = _EPOCH) -> list[Item]:
    """Newest first; entries dated before `since` dropped, undated ones kept, last."""
    recent = [entry for entry in entries if not entry.published_at or entry.published_at >= since]
    return sorted(recent, key=lambda entry: entry.published_at or _EPOCH, reverse=True)


async def read_sitemap(content: bytes) -> Sitemap:
    """`parse_sitemap` in a thread: up to `MAX_BYTES` unpacked, the API must not wait for it."""
    return await asyncio.to_thread(parse_sitemap, content)


def parse_sitemap(content: bytes) -> Sitemap:
    """A sitemap's or sitemap index's entries, in its order, gzipped or not; raises if neither."""
    try:
        root = lxml.etree.fromstring(_gunzip(content), _PARSER)
    except lxml.etree.XMLSyntaxError as error:
        msg = f"not a sitemap: {error}"
        raise UnreadableFeedError(msg) from None
    if (kind := _local(root.tag)) not in _ROOTS or root.getroottree().docinfo.doctype:
        msg = f"not a sitemap: <{kind}> with doctype {root.getroottree().docinfo.doctype!r}"
        raise UnreadableFeedError(msg)
    entries = [item for element in root if (item := _item(element))]
    return Sitemap(index=kind == "sitemapindex", entries=entries)


_ROOTS = {"urlset", "sitemapindex"}


def _gunzip(content: bytes) -> bytes:
    """A `.xml.gz` sitemap unpacked (a file, unlike `Content-Encoding`), to the size cap."""
    if not content.startswith(_GZIP_MAGIC):
        return content
    unpacker = zlib.decompressobj(_GZIP_WINDOW)
    try:
        unpacked = unpacker.decompress(content, MAX_BYTES)
    except zlib.error as error:
        msg = f"broken gzip: {error}"
        raise UnreadableFeedError(msg) from None
    if unpacker.unconsumed_tail:
        msg = f"larger than {MAX_BYTES} bytes unpacked"
        raise UnreadableFeedError(msg)
    return unpacked


_GZIP_MAGIC = b"\x1f\x8b"
_GZIP_WINDOW = 16 + zlib.MAX_WBITS  # a gzip header and trailer around deflate

# No entities, no DTDs, no network: a sitemap is data from a stranger.
_PARSER = lxml.etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)

type _Element = lxml.etree._Element  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]  # lxml's name


def _item(element: _Element) -> Item | None:
    fields = _fields(element)
    if not (loc := fields.get("loc")):
        return None
    news = _fields(next((child for child in element if _local(child.tag) == "news"), None))
    return Item(
        url=loc,
        title=news.get("title"),
        published_at=parse_date(news.get("publication_date")) or parse_date(fields.get("lastmod")),
    )


def _fields(element: _Element | None) -> dict[str, str]:
    """The texts of `element`'s children by local name (`loc`, `lastmod`, …), the first of each."""
    fields: dict[str, str] = {}
    for child in element if element is not None else ():
        if text := (child.text or "").strip():
            fields.setdefault(_local(child.tag), text)
    return fields


def _local(tag: object) -> str:
    """A tag without its namespace; "" for comments and processing instructions."""
    return tag.rpartition("}")[2] if isinstance(tag, str) else ""
