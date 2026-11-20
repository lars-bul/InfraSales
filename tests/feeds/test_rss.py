from datetime import UTC, datetime

import pytest

from infrasales.feeds.lister import Item, UnreadableFeedError
from infrasales.feeds.rss import is_feed, parse_feed
from tests.scrape.support import Entry, article_page, rss_feed

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Authority news</title>
  <entry>
    <title>Tariff approved</title>
    <link href="https://behoerde.test/news/tarif"/>
    <updated>2026-10-15T09:00:00Z</updated>
    <summary>The authority approved the tariff.</summary>
    <author><name>Press Office</name></author>
  </entry>
  <entry><title>No link</title></entry>
</feed>"""


def test_atom_entries_become_items_with_what_the_feed_says() -> None:
    assert parse_feed(ATOM) == [
        Item(
            url="https://behoerde.test/news/tarif",
            title="Tariff approved",
            published_at=datetime(2026, 10, 15, 9, tzinfo=UTC),
            summary="The authority approved the tariff.",
            author="Press Office",
        )
    ]


def test_an_empty_feed_is_a_feed_a_page_is_not() -> None:
    empty = rss_feed().encode()
    page = article_page("Hello", "Not a feed.").encode()

    assert (is_feed(empty), is_feed(page)) == (True, False)
    assert parse_feed(empty) == []
    with pytest.raises(UnreadableFeedError):
        parse_feed(page)


def test_rss_items_keep_the_feeds_order() -> None:
    feed = rss_feed(Entry("https://news.test/b", "B"), Entry("https://news.test/a", "A"))

    assert [item.title for item in parse_feed(feed.encode())] == ["B", "A"]
