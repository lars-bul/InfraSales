"""Retention of Source Versions (ADR 03 §8), through `infrasales prune`.

The versions are written by the scrape job (through the Worker, against a fake web), then aged
by hand: a version's age is when it stopped being current, `superseded_at` for a replaced one,
its Source's `last_checked_at` for the current one.
"""

import asyncio
import os
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import cast

import httpx2
import pytest
from sqlmodel import col, update

from infrasales import retention
from infrasales.audit.models import AuditEvent
from infrasales.catalog import versions
from infrasales.catalog.models import Source, SourceVersion, VersionState
from infrasales.cli import main
from infrasales.core.db import Database
from infrasales.core.models import utcnow
from infrasales.settings import RetentionSettings
from infrasales.sink.store import Sink
from tests.helpers import POSTGRES_URL, audit_events
from tests.scrape.support import (
    RSS,
    Entry,
    Scraping,
    article_page,
    broken_pointers,
    memory_sink_uri,
    rss_feed,
    stored_sources,
    stored_versions,
)

pytestmark = pytest.mark.anyio
DAY = timedelta(days=1)
FEED = "https://news.test/feed"
ARTICLE = "https://news.test/rollout"
BODY = "The company rolls its assistant out country by country, starting with paying users. " * 4


def rewritten(*texts: str) -> Callable[[httpx2.Request], httpx2.Response]:
    """The article's page: each request gets the next text, the last one stays."""
    pages = list(texts)

    def answer(_: httpx2.Request) -> httpx2.Response:
        text = pages.pop(0) if len(pages) > 1 else pages[0]
        page = article_page("Wärmenetz-Ausbau", text, BODY)  # long enough to be complete
        return httpx2.Response(200, headers={"content-type": "text/html"}, text=page)

    return answer


async def scraped(scraping: Scraping, *texts: str) -> list[SourceVersion]:
    """One version of the article per text, the last one current; versions in number order."""
    scraping.web.route(ARTICLE, rewritten(*texts))
    scraping.web.serve(FEED, rss_feed(Entry(ARTICLE, "Wärmenetz-Ausbau")), media_type=RSS)
    await scraping.add_feed("news", FEED)
    for _ in texts:
        await scraping.run_now()
    return sorted(await stored_versions(scraping.db), key=lambda v: v.version_no or 0)


async def superseded(scraping: Scraping, version: SourceVersion, at: datetime) -> None:
    async with scraping.db.session() as session:
        await session.exec(
            update(SourceVersion)
            .where(col(SourceVersion.id) == version.id)
            .values(superseded_at=at)
        )


async def checked(scraping: Scraping, at: datetime) -> None:
    """Every Source was last checked `at`."""
    async with scraping.db.session() as session:
        await session.exec(update(Source).values(last_checked_at=at))


YEAR = RetentionSettings(source_days=365)  # a period set: none is set by default


async def prune(
    scraping: Scraping, now: datetime | None = None, settings: RetentionSettings = YEAR
) -> dict[str, int]:
    """A round of `infrasales prune`; on PostgreSQL as the retention role, with its grants only."""
    db = Database(os.environ["TEST_RETENTION_DATABASE_URL"]) if POSTGRES_URL else scraping.db
    try:
        return await retention.prune(db, scraping.sink, settings, now or utcnow())
    finally:
        if db is not scraping.db:
            await db.dispose()


async def test_a_replaced_version_goes_with_its_folder_a_year_after_it_was_replaced(
    scraping: Scraping,
) -> None:
    now = utcnow()
    first, second, current = await scraped(
        scraping, "Only in the US.", "Now in Canada too.", "Now also in the EU."
    )
    await superseded(scraping, first, now - 366 * DAY)
    await superseded(scraping, second, now - 364 * DAY)

    deleted = await prune(scraping, now)

    assert [v.id for v in await stored_versions(scraping.db)] == [second.id, current.id]
    folders = {key.rsplit("/", 1)[0] for key in await scraping.files()}
    assert folders == {second.storage_key, current.storage_key}
    assert deleted["source_version"] == 1
    assert await broken_pointers(scraping.db) == {}


async def test_without_a_period_every_version_is_kept_for_good(scraping: Scraping) -> None:
    """The evidence of every claim (ADR 06 §7): nothing expires unless a period is set."""
    now = utcnow()
    first, current = await scraped(scraping, "Only in the US.", "Now also in the EU.")
    await superseded(scraping, first, now - 3650 * DAY)
    await checked(scraping, now - 3650 * DAY)

    deleted = await prune(scraping, now, RetentionSettings())

    assert [v.id for v in await stored_versions(scraping.db)] == [first.id, current.id]
    assert (deleted["source_version"], deleted["source"]) == (0, 0)


async def test_a_page_left_unchecked_for_a_year_goes_with_its_source(scraping: Scraping) -> None:
    """An article that left its Feed: no run checks it again."""
    now = utcnow()
    await scraped(scraping, "Only in the US.")
    await checked(scraping, now - 366 * DAY)

    deleted = await prune(scraping, now)

    assert (await stored_versions(scraping.db), await stored_sources(scraping.db)) == ([], [])
    assert await scraping.files() == {}
    assert (deleted["source_version"], deleted["source"]) == (1, 1)


async def test_a_page_checked_lately_keeps_its_text_however_old(scraping: Scraping) -> None:
    """An authority's page unchanged for two years: every run confirms it."""
    now = utcnow()
    (version,) = await scraped(scraping, "Only in the US.")
    async with scraping.db.session() as session:
        await session.exec(update(SourceVersion).values(fetched_at=now - 730 * DAY))
    await checked(scraping, now - 364 * DAY)

    deleted = await prune(scraping, now)

    (kept,) = await stored_versions(scraping.db)
    (source,) = await stored_sources(scraping.db)
    assert (kept.id, source.latest_version_id) == (version.id, version.id)
    assert {key.rsplit("/", 1)[0] for key in await scraping.files()} == {version.storage_key}
    assert (deleted["source_version"], deleted["source"]) == (0, 0)


async def retained(scraping: Scraping, version: SourceVersion, until: datetime) -> None:
    """The next stage keeps `version` until `until` (a claim cites it)."""
    async with scraping.db.session() as session:
        await session.exec(
            update(SourceVersion)
            .where(col(SourceVersion.id) == version.id)
            .values(retain_until=until)
        )


async def test_a_version_retained_for_an_event_is_kept_until_then(scraping: Scraping) -> None:
    now = utcnow()
    first, second, current = await scraped(
        scraping, "Only in the US.", "Now in Canada too.", "Now also in the EU."
    )
    for version in (first, second):
        await superseded(scraping, version, now - 400 * DAY)
    await retained(scraping, first, now + DAY)
    await retained(scraping, second, now - DAY)  # until yesterday: expired since

    deleted = await prune(scraping, now)

    assert [v.id for v in await stored_versions(scraping.db)] == [first.id, current.id]
    assert deleted["source_version"] == 1


async def test_a_version_s_retention_is_extended_never_shortened(scraping: Scraping) -> None:
    now = utcnow()
    first, current = await scraped(scraping, "Only in the US.", "Now also in the EU.")
    await superseded(scraping, first, now - 400 * DAY)

    assert await versions.retain(scraping.db, first.id, now + 30 * DAY)
    assert await versions.retain(scraping.db, first.id, now + DAY)  # sooner: no change
    assert not await versions.retain(scraping.db, uuid.uuid7(), now + DAY)  # no such version

    await prune(scraping, now + 2 * DAY)
    assert [v.id for v in await stored_versions(scraping.db)] == [first.id, current.id]
    await prune(scraping, now + 31 * DAY)
    assert [v.id for v in await stored_versions(scraping.db)] == [current.id]
    assert not await versions.retain(scraping.db, first.id, now + 60 * DAY)  # gone: too late


async def test_a_current_version_retained_for_an_event_keeps_its_source(
    scraping: Scraping,
) -> None:
    now = utcnow()
    (version,) = await scraped(scraping, "Only in the US.")
    await checked(scraping, now - 400 * DAY)
    await retained(scraping, version, now + DAY)

    await prune(scraping, now)

    (source,) = await stored_sources(scraping.db)
    assert source.latest_version_id == version.id


async def test_a_page_left_unchecked_keeps_its_current_text_while_an_older_one_is_kept(
    scraping: Scraping,
) -> None:
    """The latest pointer keeps naming the highest committed version (ADR 03 §3).

    Deleting the current version while an older one is kept for a claim would leave that one
    committed and the Source pointing at none: the current text goes with the last kept one.
    """
    now = utcnow()
    first, second, current = await scraped(
        scraping, "Only in the US.", "Now in Canada too.", "Now also in the EU."
    )
    for version in (first, second):
        await superseded(scraping, version, now - 400 * DAY)
    await checked(scraping, now - 400 * DAY)
    await retained(scraping, first, now + DAY)

    deleted = await prune(scraping, now)

    assert [v.id for v in await stored_versions(scraping.db)] == [first.id, current.id]
    assert (deleted["source_version"], deleted["source"]) == (1, 0)
    assert await broken_pointers(scraping.db) == {}

    await retained(scraping, first, now - DAY)  # the claim no longer needs it
    deleted = await prune(scraping, now)

    assert (await stored_sources(scraping.db), await scraping.files()) == ([], {})
    assert (deleted["source_version"], deleted["source"]) == (2, 1)


async def test_a_version_being_written_keeps_its_source_and_the_current_one(
    scraping: Scraping,
) -> None:
    """A run is writing a new text of a page long unchecked: `writing` belongs to the scrape."""
    now = utcnow()
    (version,) = await scraped(scraping, "Only in the US.")
    await checked(scraping, now - 400 * DAY)
    (source,) = await stored_sources(scraping.db)
    await versions.start(scraping.db, new_text(version, source.url))

    deleted = await prune(scraping, now)

    states = [(v.id == version.id, v.state) for v in await stored_versions(scraping.db)]
    assert states == [(True, VersionState.COMMITTED), (False, VersionState.WRITING)]
    assert deleted["source_version"] == 0


def new_text(version: SourceVersion, url: str) -> versions.NewVersion:
    return versions.NewVersion(
        id=uuid.uuid7(),
        url=url,
        feed_id=version.feed_id,
        run_id=None,
        fetched_at=utcnow(),
        http_status=200,
        media_type="text/html",
        raw_sha256="0" * 64,
        text_sha256="1" * 64,
        extractor=version.extractor,
        extractor_version=version.extractor_version,
        storage_key=f"elsewhere/news/{uuid.uuid4()}",
    )


async def articles(scraping: Scraping, count: int) -> None:
    """`count` articles listed by one Feed, scraped once: a Source and a version each."""
    urls = [f"https://news.test/story-{n}" for n in range(count)]
    for url in urls:
        scraping.web.serve(url, article_page("Story", f"The authority decided on {url}.", BODY))
    scraping.web.serve(FEED, rss_feed(*(Entry(url) for url in urls)), media_type=RSS)
    await scraping.add_feed("news", FEED)
    await scraping.run_now()


async def test_each_batch_and_the_round_are_audited_with_their_counts(
    scraping: Scraping, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retention, "_BATCH", 2)
    now = utcnow()
    await articles(scraping, 3)
    await checked(scraping, now - 366 * DAY)

    deleted = await prune(scraping, now)

    events = [e for e in await audit_events(database_url) if e.action.startswith("retention.")]
    batches = [(e.target, e.details) for e in events if e.action == "retention.deleted"]
    assert batches == [
        ("source_version", {"rows": 2}),
        ("source", {"rows": 2}),
        ("source_version", {"rows": 1}),
        ("source", {"rows": 1}),
    ]
    (pruned,) = [e for e in events if e.action == "retention.pruned"]
    assert (pruned.actor, pruned.details) == (None, deleted)
    assert (deleted["source_version"], deleted["source"]) == (3, 3)
    assert await scraping.files() == {}


async def test_folders_no_version_names_are_deleted_and_audited(
    scraping: Scraping, database_url: str
) -> None:
    """Left by an attempt that froze, was swept and wrote on: a copy without a record."""
    now = utcnow()
    (committed,) = await scraped(scraping, "Only in the US.")
    (source,) = await stored_sources(scraping.db)
    writing = new_text(committed, source.url)
    await versions.start(scraping.db, writing)  # a run writing a new text right now
    await scraping.sink.write(f"{writing.storage_key}/raw.html", b"<html>")
    orphan = f"2026-10-16T060000Z/news/{uuid.uuid7()}"
    await scraping.sink.write(f"{orphan}/raw.html", b"<html>")
    stray = "2026-10-16T060000Z/news/index"  # as deep as a version's folder, not named like one
    await scraping.sink.write(f"{stray}/notes.txt", b"not a version's folder")

    deleted = await prune(scraping, now)

    assert deleted["sink_folder"] == 1
    folders = {key.rsplit("/", 1)[0] for key in await scraping.files()}
    assert folders == {committed.storage_key, writing.storage_key, stray}
    events = [e for e in await audit_events(database_url) if e.target == "sink_folder"]
    assert [(e.action, e.details) for e in events] == [("retention.deleted", {"folders": 1})]

    assert (await prune(scraping, now))["sink_folder"] == 0  # nothing left over


async def test_a_round_cut_off_while_deleting_files_is_completed_by_the_next(
    scraping: Scraping, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Marked `deleted` and audited first: no reader trusts the version once the files go."""
    now = utcnow()
    (version,) = await scraped(scraping, "Only in the US.")
    await checked(scraping, now - 366 * DAY)
    delete = Sink.delete

    async def unreachable(_: Sink, folder: str) -> None:
        monkeypatch.setattr(Sink, "delete", delete)  # back next time
        raise ConnectionError(folder)

    monkeypatch.setattr(Sink, "delete", unreachable)

    with pytest.raises(ConnectionError):
        await prune(scraping, now)

    assert await versions.find_committed(scraping.db, version.id) is None
    assert await scraping.files() != {}

    await prune(scraping, now)

    assert (await stored_sources(scraping.db), await scraping.files()) == ([], {})
    events = await audit_events(database_url)
    assert _deletions(events) == {"source_version": 1, "source": 1}  # each once


def _deletions(events: list[AuditEvent]) -> dict[str, int]:
    counted = Counter[str]()
    for event in events:
        if event.action == "retention.deleted" and event.target:
            counted[event.target] += cast("int", event.details["rows"])
    return dict(counted)


async def test_infrasales_prune_deletes_expired_versions_with_their_files(
    scraping: Scraping, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command, as the retention service runs it: its settings name the sink."""
    uri = memory_sink_uri()
    scraping.sink = Sink(uri)
    await scraped(scraping, "Only in the US.")
    await checked(scraping, utcnow() - 366 * DAY)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SINK__URI", uri)
    monkeypatch.setenv("RETENTION__SOURCE_DAYS", "365")  # kept for good without a period

    await asyncio.to_thread(main, ["prune"])  # its own event loop, as from a shell

    assert (await stored_sources(scraping.db), await scraping.files()) == ([], {})
