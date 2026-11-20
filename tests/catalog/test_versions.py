"""Catalog operations the crash sweep and retention build on.

The versions are stored by the scrape job.
"""

import uuid
from dataclasses import replace

import pytest
from sqlmodel import col, update

from infrasales.catalog import versions
from infrasales.catalog.models import MAX_TITLE_LENGTH, SourceVersion, VersionState
from tests.scrape.support import RSS, Entry, Scraping, article_page, rss_feed, stored_sources
from tests.scrape.support import stored_versions as stored

pytestmark = pytest.mark.anyio

FEED = "https://news.test/feed.xml"
ARTICLE = "https://news.test/story"


async def scraped_once(scraping: Scraping) -> None:
    scraping.web.serve(ARTICLE, article_page("Story", "The authority decided today."))
    scraping.web.serve(FEED, rss_feed(Entry(ARTICLE)), media_type=RSS)
    await scraping.add_feed("news", FEED)
    await scraping.run_now()


async def test_deleting_a_version_deletes_its_folder_its_row_and_its_empty_source(
    scraping: Scraping,
) -> None:
    await scraped_once(scraping)
    (version,) = await stored(scraping.db)

    assert await versions.delete_version(scraping.db, scraping.sink, version.id)

    assert (await stored(scraping.db), await stored_sources(scraping.db)) == ([], [])
    assert await scraping.files() == {}
    assert not await versions.delete_version(scraping.db, scraping.sink, version.id)  # gone


async def test_deleting_one_of_two_versions_keeps_the_source_and_clears_its_pointer(
    scraping: Scraping,
) -> None:
    await scraped_once(scraping)
    (first,) = await stored(scraping.db)
    second = await written_again(scraping, first.id)
    assert await versions.commit(scraping.db, second) == 2

    await versions.delete_version(scraping.db, scraping.sink, second.id)

    (source,) = await stored_sources(scraping.db)
    ((kept,),) = [await stored(scraping.db)]
    assert (source.latest_version_id, kept.id, kept.superseded_at is not None) == (
        None,
        first.id,
        True,
    )


async def test_a_version_swept_while_it_was_written_is_not_committed(scraping: Scraping) -> None:
    await scraped_once(scraping)
    (first,) = await stored(scraping.db)
    second = await written_again(scraping, first.id)
    assert await versions.sweep(scraping.db, scraping.sink) == 1

    assert await versions.commit(scraping.db, second) is None
    assert await scraping.files(second.storage_key) == {}
    (source,) = await stored_sources(scraping.db)
    assert source.latest_version_id == first.id
    assert [(v.version_no, v.state) for v in await stored(scraping.db)] == [
        (1, VersionState.COMMITTED)
    ]


async def written_again(scraping: Scraping, version_id: uuid.UUID) -> versions.NewVersion:
    """A second version of the Source of `version_id`, started (`writing`), not committed."""
    (first,) = [v for v in await stored(scraping.db) if v.id == version_id]
    (source,) = await stored_sources(scraping.db)
    new = versions.NewVersion(
        id=uuid.uuid7(),
        url=source.url,
        feed_id=first.feed_id,
        run_id=None,
        fetched_at=first.fetched_at,
        http_status=200,
        media_type="text/html",
        raw_sha256=first.raw_sha256,
        text_sha256="0" * 64,
        extractor=first.extractor,
        extractor_version=first.extractor_version,
        storage_key=f"run/news/{uuid.uuid4()}",
    )
    await versions.start(scraping.db, new)
    await scraping.sink.write(f"{new.storage_key}/raw.html", b"<p>changed</p>")
    return new


async def test_committed_versions_are_listed_after_a_cursor_oldest_first(
    scraping: Scraping,
) -> None:
    await scraped_once(scraping)
    (first,) = await versions.committed_after(scraping.db)
    second = await written_again(scraping, first.id)  # being written: not listed yet

    assert await versions.committed_after(scraping.db, first.id) == []
    assert await versions.commit(scraping.db, second) == 2
    (new,) = await versions.committed_after(scraping.db, first.id)
    assert (new.id, new.version_no) == (second.id, 2)
    listed = await versions.committed_after(scraping.db)  # the replaced one too: evidence
    assert [(v.id, v.version_no) for v in listed] == [(first.id, 1), (second.id, 2)]
    assert [v.id for v in await versions.committed_after(scraping.db, limit=1)] == [first.id]


async def test_versions_being_deleted_are_not_listed(scraping: Scraping) -> None:
    await scraped_once(scraping)
    (version,) = await stored(scraping.db)
    async with scraping.db.session() as session:  # marked, as retention does first
        await session.exec(
            update(SourceVersion)
            .where(col(SourceVersion.id) == version.id)
            .values(state=VersionState.DELETED)
        )

    assert await versions.committed_after(scraping.db) == []


async def test_a_long_title_is_cut_for_the_catalog(scraping: Scraping) -> None:
    await scraped_once(scraping)
    (first,) = await stored(scraping.db)
    new = await written_again(scraping, first.id)
    long = replace(new, id=uuid.uuid7(), title="t" * 600)

    await versions.start(scraping.db, long)

    (stored_long,) = [v for v in await stored(scraping.db) if v.id == long.id]
    assert stored_long.title == "t" * MAX_TITLE_LENGTH
