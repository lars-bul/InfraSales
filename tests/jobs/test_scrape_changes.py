"""Change detection (ADR 03 §3): a URL InfraSales knows is checked again when it is due.

Through the scrape job's seam: the Worker, a fake web, a `memory://` sink, the test database.
"""

import json
import uuid
from datetime import timedelta
from typing import Any, override

import httpx2
import pytest
from sqlmodel import col, update

from infrasales.catalog import versions as catalog
from infrasales.catalog.layout import run_folder
from infrasales.catalog.models import Source, SourceVersion, VersionState
from infrasales.core.db import Database
from infrasales.core.models import utcnow
from infrasales.extract import registry
from infrasales.extract.extractor import Extracted
from infrasales.extract.html import HtmlExtractor
from infrasales.feeds import kinds
from infrasales.feeds.lister import Item, ListerSettings
from infrasales.feeds.models import Feed, FeedKind
from infrasales.fetch.fetcher import Fetcher
from infrasales.scheduler.models import JobStatus
from tests.scrape.support import (
    HTML,
    RSS,
    Entry,
    Scraping,
    article_page,
    broken_pointers,
    counts,
    rss_feed,
    stored_sources,
)
from tests.scrape.support import stored_versions as versions

pytestmark = pytest.mark.anyio

FEED = "https://news.test/feed.xml"
ARTICLE = "https://news.test/2026/10/waermenetz-ausbau"
SOUTH_ONLY = ("Der Wärmenetz-Ausbau beginnt heute.", "Es wird im Süden allein gebaut.")
WITH_NORTH = ("Der Wärmenetz-Ausbau beginnt heute.", "Es wird jetzt auch im Norden gebaut.")
ETAG = '"v1"'
LAST_MODIFIED = "Fri, 16 Oct 2026 05:00:00 GMT"


async def listed(scraping: Scraping) -> None:
    scraping.web.serve(FEED, rss_feed(Entry(ARTICLE, "Wärmenetz-Ausbau")), media_type=RSS)
    await scraping.add_feed("news", FEED)


async def test_a_304_creates_no_version_and_only_updates_the_last_checked_time(
    scraping: Scraping,
) -> None:
    page = article_page("Wärmenetz-Ausbau", *SOUTH_ONLY)
    validators = {"etag": ETAG, "last-modified": LAST_MODIFIED}

    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.headers.get("if-none-match") == ETAG:
            return httpx2.Response(304, headers={"etag": '"other"'})
        return httpx2.Response(200, headers={"content-type": HTML} | validators, content=page)

    scraping.web.route(ARTICLE, answer)
    await listed(scraping)
    await scraping.run_now()
    ((before,), (version,)) = (await stored_sources(scraping.db), await versions(scraping.db))

    run = await scraping.run_now()

    assert run.status == JobStatus.SUCCEEDED
    assert (counts(run)["versions_new"], counts(run)["versions_unchanged"]) == (0, 1)
    request = scraping.web.requests[-1]
    assert (request.headers["if-none-match"], request.headers["if-modified-since"]) == (
        ETAG,
        LAST_MODIFIED,
    )
    (after,) = await stored_sources(scraping.db)
    assert await versions(scraping.db) == [version]
    assert after.last_checked_at > before.last_checked_at
    assert after.model_dump(exclude={"last_checked_at", "updated_at"}) == before.model_dump(
        exclude={"last_checked_at", "updated_at"}
    )


def framed(*paragraphs: str, ad: str, updated: str) -> str:
    """The article page in a changing frame: an ad and a "last updated" time around it."""
    return article_page("Wärmenetz-Ausbau", *paragraphs).replace(
        "<footer>", f"<aside class='ad'>{ad}</aside><footer>Updated {updated} · "
    )


async def test_the_same_text_in_a_changed_page_creates_no_version_but_stores_the_validators(
    scraping: Scraping,
) -> None:
    scraping.web.serve(ARTICLE, framed(*SOUTH_ONLY, ad="Buy shoes", updated="06:00"))
    await listed(scraping)
    await scraping.run_now()
    (version,) = await versions(scraping.db)
    files = await scraping.files()
    validators = {"etag": '"v2"', "last-modified": "Fri, 16 Oct 2026 08:00:00 GMT"}
    changed_frame = framed(*SOUTH_ONLY, ad="Buy a car", updated="09:00")
    scraping.web.serve(ARTICLE, changed_frame, headers=validators)

    run = await scraping.run_now()

    assert (counts(run)["versions_new"], counts(run)["versions_unchanged"]) == (0, 1)
    assert scraping.web.fetched(ARTICLE) == 2
    assert await versions(scraping.db) == [version]
    assert await scraping.files() == files
    (source,) = await stored_sources(scraping.db)
    assert (source.etag, source.last_modified) == ('"v2"', "Fri, 16 Oct 2026 08:00:00 GMT")
    assert source.last_checked_at > version.fetched_at


async def test_a_changed_text_becomes_the_next_version_and_supersedes_the_previous(
    scraping: Scraping,
) -> None:
    scraping.web.serve(ARTICLE, article_page("Wärmenetz-Ausbau", *SOUTH_ONLY))
    await listed(scraping)
    await scraping.run_now()
    scraping.web.serve(ARTICLE, article_page("Wärmenetz-Ausbau", *WITH_NORTH))

    run = await scraping.run_now()

    assert (counts(run)["versions_new"], counts(run)["versions_unchanged"]) == (1, 0)
    first, second = await versions(scraping.db)
    (source,) = await stored_sources(scraping.db)
    assert (first.version_no, second.version_no) == (1, 2)
    assert (first.state, second.state) == (VersionState.COMMITTED, VersionState.COMMITTED)
    assert first.superseded_at is not None
    assert second.superseded_at is None
    assert (second.source_id, second.run_id) == (source.id, run.id)
    assert source.latest_version_id == second.id
    assert second.storage_key.startswith(f"{run_folder(run.scheduled_for)}/news/")
    extracted = json.loads((await scraping.files())[f"{second.storage_key}/extracted.json"])
    assert "jetzt auch im Norden" in extracted["text"]
    assert await broken_pointers(scraping.db) == {}


async def test_a_text_changed_back_is_a_third_version(scraping: Scraping) -> None:
    pages = iter((SOUTH_ONLY, WITH_NORTH, SOUTH_ONLY))
    await listed(scraping)

    for _ in range(3):
        scraping.web.serve(ARTICLE, article_page("Wärmenetz-Ausbau", *next(pages)))
        await scraping.run_now()

    stored = await versions(scraping.db)
    assert [v.version_no for v in stored] == [1, 2, 3]
    assert stored[0].text_sha256 == stored[2].text_sha256 != stored[1].text_sha256
    assert [v.superseded_at is None for v in stored] == [False, False, True]
    (source,) = await stored_sources(scraping.db)
    assert source.latest_version_id == stored[2].id
    assert await broken_pointers(scraping.db) == {}


class UpgradedHtml:
    """The HTML extractor after an upgrade that reads every page differently (here: louder)."""

    name = "html"
    version = "2+test"

    def __init__(self) -> None:
        self.read: list[bytes] = []

    def extract(self, raw: bytes, url: str) -> Extracted:
        self.read.append(raw)
        extracted = HtmlExtractor().extract(raw, url)
        return Extracted(extracted.text.upper(), extracted.title)


async def test_after_an_extractor_upgrade_an_unchanged_page_creates_no_version(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = article_page("Wärmenetz-Ausbau", *SOUTH_ONLY)
    scraping.web.serve(ARTICLE, page)
    await listed(scraping)
    await scraping.run_now()
    upgraded = UpgradedHtml()
    monkeypatch.setitem(registry.EXTRACTORS, "html", upgraded)

    run = await scraping.run_now()

    assert (counts(run)["versions_new"], counts(run)["versions_unchanged"]) == (0, 1)
    assert len(await versions(scraping.db)) == 1
    assert upgraded.read == [page.encode()] * 2  # the new page, and the latest version's raw file


async def test_after_an_extractor_upgrade_a_changed_page_is_a_new_version_read_by_the_new_one(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    scraping.web.serve(ARTICLE, article_page("Wärmenetz-Ausbau", *SOUTH_ONLY))
    await listed(scraping)
    await scraping.run_now()
    monkeypatch.setitem(registry.EXTRACTORS, "html", UpgradedHtml())
    scraping.web.serve(ARTICLE, article_page("Wärmenetz-Ausbau", *WITH_NORTH))

    run = await scraping.run_now()

    assert counts(run)["versions_new"] == 1
    first, second = await versions(scraping.db)
    assert (first.extractor_version, second.extractor_version) != ("2+test", "2+test")
    assert second.extractor_version == "2+test"


@pytest.mark.parametrize(
    "now", [{"body": "gone", "status": 404}, {"body": b"\x89PNG", "media_type": "image/png"}]
)
async def test_a_known_page_that_cannot_be_got_or_read_now_is_skipped_and_kept(
    scraping: Scraping, now: dict[str, Any]
) -> None:
    scraping.web.serve(ARTICLE, article_page("Wärmenetz-Ausbau", *SOUTH_ONLY))
    await listed(scraping)
    await scraping.run_now()
    (before,) = await stored_sources(scraping.db)
    scraping.web.serve(ARTICLE, **now)

    run = await scraping.run_now()

    assert run.status == JobStatus.SUCCEEDED
    assert (counts(run)["versions_unchanged"], counts(run)["documents_failed"]) == (0, 1)
    assert len(await versions(scraping.db)) == 1
    (after,) = await stored_sources(scraping.db)
    assert after.last_checked_at == before.last_checked_at  # not checked: not seen again


class CarryingLister:
    """An API-like Lister whose item carries its whole content, as given by `pages`."""

    settings = ListerSettings

    def __init__(self, *pages: tuple[str, ...]) -> None:
        self.pages = iter(pages)

    async def list(self, feed: Feed, fetcher: Fetcher) -> list[Item]:
        del feed, fetcher
        page = article_page("Wärmenetz-Ausbau", *next(self.pages)).encode()
        return [Item(ARTICLE, content=page, media_type="text/html")]


async def test_a_known_item_carrying_its_content_is_compared_without_a_fetch(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    lister = CarryingLister(SOUTH_ONLY, SOUTH_ONLY, WITH_NORTH)
    monkeypatch.setitem(kinds.LISTERS, FeedKind.SITEMAP, lister)
    await scraping.add_feed("carrying", "https://api.test/v1", kind=FeedKind.SITEMAP)

    results = [counts(await scraping.run_now()) for _ in range(3)]

    assert [(r["versions_new"], r["versions_unchanged"]) for r in results] == [
        (1, 0),
        (0, 1),
        (1, 0),
    ]
    assert scraping.web.requests == []
    assert [v.http_status for v in await versions(scraping.db)] == [None, None]


async def half_delete(scraping: Scraping, version: SourceVersion) -> None:
    """What a deletion leaves when it stops before its row is deleted (ADR 03 §3)."""
    async with scraping.db.session() as session:
        await session.exec(
            update(SourceVersion)
            .where(col(SourceVersion.id) == version.id)
            .values(state=VersionState.DELETED)
        )
    await scraping.sink.delete(version.storage_key)


async def test_a_latest_version_left_half_deleted_by_a_crash_is_completed_by_the_sweep(
    scraping: Scraping,
) -> None:
    """The next run's sweep deletes it and its Source: the page is new again."""
    scraping.web.serve(ARTICLE, article_page("Wärmenetz-Ausbau", *SOUTH_ONLY))
    await listed(scraping)
    await scraping.run_now()
    (leftover,) = await versions(scraping.db)
    await half_delete(scraping, leftover)

    run = await scraping.run_now()

    assert counts(run)["versions_new"] == 1
    (new,) = await versions(scraping.db)
    (source,) = await stored_sources(scraping.db)
    assert new.id != leftover.id
    assert (new.version_no, new.state, source.latest_version_id) == (
        1,
        VersionState.COMMITTED,
        new.id,
    )
    assert source.id != leftover.source_id
    assert await broken_pointers(scraping.db) == {}


async def test_a_latest_version_being_deleted_during_the_run_is_not_compared_with(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleting a version marks it `deleted` first: until its row is gone, it is pointed at."""
    scraping.web.serve(ARTICLE, article_page("Wärmenetz-Ausbau", *SOUTH_ONLY))
    await listed(scraping)
    await scraping.run_now()
    (leftover,) = await versions(scraping.db)
    find_committed = catalog.find_committed

    async def deleted_meanwhile(db: Database, version_id: uuid.UUID) -> SourceVersion | None:
        await half_delete(scraping, leftover)
        return await find_committed(db, version_id)

    monkeypatch.setattr(catalog, "find_committed", deleted_meanwhile)

    run = await scraping.run_now()

    assert counts(run)["versions_new"] == 1
    _, new = await versions(scraping.db)
    (source,) = await stored_sources(scraping.db)
    assert (new.version_no, new.state, source.latest_version_id) == (
        2,
        VersionState.COMMITTED,
        new.id,
    )
    assert await broken_pointers(scraping.db) == {}


async def test_a_latest_version_whose_files_were_deleted_meanwhile_is_not_compared_with(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its raw file gone (retention deleting it after the run looked it up), nothing compares.

    What was got becomes the next version, as with a version being deleted (above).
    """
    scraping.web.serve(ARTICLE, article_page("Wärmenetz-Ausbau", *SOUTH_ONLY))
    await listed(scraping)
    await scraping.run_now()
    (first,) = await versions(scraping.db)
    await scraping.sink.delete(first.storage_key)  # its files, its row still committed
    monkeypatch.setitem(registry.EXTRACTORS, "html", UpgradedHtml())  # re-reads the raw file

    run = await scraping.run_now()

    assert (counts(run)["versions_new"], counts(run)["documents_failed"]) == (1, 0)
    assert await broken_pointers(scraping.db) == {}


async def aged(scraping: Scraping, *, text_age: timedelta, checked_ago: timedelta) -> None:
    """Its text first seen `text_age` ago, the Source last checked `checked_ago` ago."""
    now = utcnow()
    async with scraping.db.session() as session:
        await session.exec(update(SourceVersion).values(fetched_at=now - text_age))
        await session.exec(update(Source).values(last_checked_at=now - checked_ago))


@pytest.mark.parametrize(
    ("text_age", "checked_ago", "due"),
    [
        (timedelta(days=30), timedelta(days=1), False),  # unchanged long: checked every 3 days
        (timedelta(days=30), timedelta(days=3, hours=1), True),
        (timedelta(days=30), timedelta(days=3, minutes=-30), True),  # this run is close enough
        (timedelta(days=365), timedelta(days=8), True),  # at least once a week
        (timedelta(hours=20), timedelta(hours=3), True),  # recent: every run (every 3 hours)
        (timedelta(days=2), timedelta(hours=3), False),  # every 4.8 hours: every other run
    ],
)
async def test_a_known_url_is_checked_again_only_when_due(
    scraping: Scraping, text_age: timedelta, checked_ago: timedelta, *, due: bool
) -> None:
    """Due once a tenth of the time its text has stayed the same has passed (RFC 9111 §4.2.2)."""
    scraping.web.serve(ARTICLE, article_page("Wärmenetz-Ausbau", *SOUTH_ONLY))
    await listed(scraping)
    await scraping.run_now()
    await aged(scraping, text_age=text_age, checked_ago=checked_ago)
    (before,) = await stored_sources(scraping.db)

    run = await scraping.run_now()

    assert (scraping.web.fetched(ARTICLE), counts(run)["versions_unchanged"]) == (
        (2, 1) if due else (1, 0)
    )
    (after,) = await stored_sources(scraping.db)
    assert (after.last_checked_at > before.last_checked_at) is due


class PickyHtml(UpgradedHtml):
    """An upgraded extractor that fails on the page as it was (say, its old markup)."""

    @override
    def extract(self, raw: bytes, url: str) -> Extracted:
        if "Süden allein".encode() in raw:
            msg = "markup no longer understood"
            raise ValueError(msg)
        return super().extract(raw, url)


async def test_a_latest_version_the_upgraded_extractor_cannot_read_is_not_compared_with(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No like-for-like comparison is possible: what was got becomes the next version."""
    scraping.web.serve(ARTICLE, article_page("Wärmenetz-Ausbau", *SOUTH_ONLY))
    await listed(scraping)
    await scraping.run_now()
    monkeypatch.setitem(registry.EXTRACTORS, "html", PickyHtml())
    scraping.web.serve(ARTICLE, article_page("Wärmenetz-Ausbau", *WITH_NORTH))

    run = await scraping.run_now()

    assert (counts(run)["versions_new"], counts(run)["documents_failed"]) == (1, 0)
