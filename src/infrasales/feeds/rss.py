"""The `rss` Lister: the entries of an RSS or Atom feed.

Ported from the draft branch `feat/core-foundation-scraper` (lars-bul); keeps the summary too.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import feedparser

from infrasales.core.text import stripped
from infrasales.feeds.lister import MAX_ITEMS, Item, ListerSettings, UnreadableFeedError
from infrasales.feeds.models import Feed
from infrasales.fetch.fetcher import Fetcher


class RssSettings(ListerSettings):
    """An `rss` Feed needs nothing but its address."""


class RssLister:
    settings = RssSettings

    async def list(self, feed: Feed, fetcher: Fetcher) -> list[Item]:
        response = await fetcher.fetch(feed.url)
        # In a thread: parsing is CPU-bound, and the worker shares its loop with the API.
        return (await asyncio.to_thread(parse_feed, response.content))[:MAX_ITEMS]


def is_feed(content: bytes) -> bool:
    """Whether `content` is an RSS or Atom feed (an empty one counts)."""
    parsed = feedparser.parse(content)
    return bool(parsed.entries) or bool(parsed.get("version"))


def parse_feed(content: bytes) -> list[Item]:
    """The feed's entries with a link, in the feed's order; raises if it is no feed."""
    parsed = feedparser.parse(content)
    if not (parsed.entries or parsed.get("version")):
        msg = "not an RSS or Atom feed"
        raise UnreadableFeedError(msg)
    return [item for entry in parsed.entries if (item := _item(entry))]


def _item(entry: dict[str, Any]) -> Item | None:
    if not (link := stripped(entry.get("link"))):
        return None
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    return Item(
        url=link,
        title=stripped(entry.get("title")),
        published_at=datetime(*stamp[:6], tzinfo=UTC) if stamp else None,
        summary=stripped(entry.get("summary")),
        author=stripped(entry.get("author")),
    )
