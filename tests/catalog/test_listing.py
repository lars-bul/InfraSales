"""The catalog read for people; the Source API's tests (`test_router.py`) cover it end to end."""

import json
import uuid
from datetime import UTC, datetime

import pytest

from infrasales.catalog import listing
from infrasales.catalog.layout import EXTRACTED
from infrasales.catalog.models import SourceVersion
from infrasales.feeds.models import Feed, FeedKind
from tests.scrape.support import memory_sink

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 17, 6, tzinfo=UTC)


def version(number: int | None) -> SourceVersion:
    return SourceVersion(
        source_id=uuid.uuid7(),
        version_no=number,
        feed_id=uuid.uuid7(),
        fetched_at=NOW,
        media_type="text/html",
        raw_sha256="0" * 64,
        text_sha256="0" * 64,
        extractor="html",
        extractor_version="1",
        storage_key=f"run/news/{uuid.uuid7()}",
    )


FEED = Feed(name="News", slug="news", kind=FeedKind.RSS, url="https://news.test/feed.xml")


def test_a_version_is_read_with_its_feed() -> None:
    read = listing.version_read(version(3), FEED)

    assert (read.number, read.feed.slug, read.feed.name, read.title) == (3, "news", "News", None)


def test_a_version_not_yet_committed_has_no_number_to_show() -> None:
    with pytest.raises(ValueError, match="not committed"):
        listing.version_read(version(None), FEED)


async def test_a_versions_text_is_what_its_extractor_wrote() -> None:
    sink, stored = memory_sink(), version(2)
    extracted = {"title": "Story", "author": None, "published_at": NOW.isoformat(), "text": "Hi"}
    await sink.write(f"{stored.storage_key}/{EXTRACTED}", json.dumps(extracted).encode())

    text = await listing.text(sink, stored)

    assert (text.number, text.title, text.author, text.published_at, text.text) == (
        2,
        "Story",
        None,
        NOW,
        "Hi",
    )


async def test_a_version_without_files_raises() -> None:
    with pytest.raises(FileNotFoundError):
        await listing.raw(memory_sink(), version(1))
