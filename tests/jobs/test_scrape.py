"""The scrape job through the Worker: a fake web, a `memory://` sink, the test database."""

import hashlib
import json
from datetime import UTC, datetime
from typing import override

import pytest

from infrasales.catalog.models import VersionState
from infrasales.feeds import kinds
from infrasales.feeds.lister import Item, ListerSettings
from infrasales.feeds.models import Feed, FeedKind, FeedState
from infrasales.fetch.fetcher import Fetcher
from infrasales.fetch.http import MAX_BYTES
from infrasales.scheduler.models import JobStatus
from infrasales.sink.store import Sink
from tests.scrape.support import (
    RSS,
    Entry,
    Scraping,
    article_page,
    counts,
    disable_all_feeds,
    feed_outcome,
    memory_sink_uri,
    rss_feed,
    stored_feeds,
    stored_sources,
)
from tests.scrape.support import stored_versions as versions

pytestmark = pytest.mark.anyio

FEED = "https://news.test/feed.xml"
WIRE = "https://wire.test/rss"
ARTICLE = "https://news.test/2026/10/heat-network-approved"
TEXT = (
    "The town council approved the heat network for the old town at its June session.",
    "The municipal utility will lay ten kilometres of pipe and connect four hundred homes.",
    "The construction work is put out to tender this autumn, and building starts next May.",
)  # long enough to pass the quality gate: a complete text, not `partial`
REQUESTED = datetime(2026, 10, 16, 6, 0, 7, 250_000, tzinfo=UTC)  # a "Run now" click


def serve_article(
    scraping: Scraping, url: str = ARTICLE, title: str = "Heat network approved"
) -> None:
    scraping.web.serve(url, article_page(title, *TEXT))


async def test_a_new_article_becomes_a_committed_source_version_with_its_files(
    scraping: Scraping,
) -> None:
    scraping.clock.now = REQUESTED
    serve_article(scraping)
    scraping.web.serve(FEED, rss_feed(Entry(ARTICLE, "Heat network approved")), media_type=RSS)
    feed = await scraping.add_feed("news", FEED)

    run = await scraping.run_now()

    assert (run.status, run.result) == (
        JobStatus.SUCCEEDED,
        {
            "feeds_read": 1,
            "versions_new": 1,
            "versions_unchanged": 0,
            "documents_failed": 0,
            "failed_feeds": [],
            "out_of_time": [],
            "feeds": [feed_outcome("news", items=1, new=1, seconds=6.0)],  # 2 requests, a pause
        },
    )
    (source,) = await stored_sources(scraping.db)
    (version,) = await versions(scraping.db)
    assert (version.state, version.version_no, version.source_id) == (
        VersionState.COMMITTED,
        1,
        source.id,
    )
    assert source.latest_version_id == version.id
    assert (source.url, source.first_feed_id) == (ARTICLE, feed.id)
    assert (version.run_id, version.feed_id, version.http_status) == (run.id, feed.id, 200)
    assert (version.media_type, version.extractor) == ("text/html", "html")
    folder = f"2026-10-16T060007Z/news/{version.id}"
    assert version.storage_key == folder
    files = await scraping.files()
    assert sorted(files) == [
        f"{folder}/extracted.json",
        f"{folder}/metadata.json",
        f"{folder}/raw.html",
    ]
    assert files[f"{folder}/raw.html"] == article_page("Heat network approved", *TEXT).encode()
    extracted = json.loads(files[f"{folder}/extracted.json"])
    assert extracted["title"] == "Heat network approved"
    assert all(paragraph in extracted["text"] for paragraph in TEXT)
    assert "Copyright" not in extracted["text"]  # the page's frame is not the article
    assert extracted["extractor"]["name"] == "html"


async def test_metadata_describes_the_version_in_five_groups_without_a_number(
    scraping: Scraping,
) -> None:
    published = datetime(2026, 10, 16, 5, 30, tzinfo=UTC)
    entry = Entry(
        ARTICLE, "Heat network approved", "Building starts next year.", "Jane Doe", published
    )
    validators = {"etag": '"v1"', "last-modified": "Fri, 16 Oct 2026 05:00:00 GMT"}
    page = article_page("Heat network approved", *TEXT)
    scraping.web.serve(ARTICLE, page, headers=validators | {"set-cookie": "session=secret"})
    scraping.web.serve(FEED, rss_feed(entry), media_type=RSS)
    feed = await scraping.add_feed("news", FEED)

    run = await scraping.run_now()

    ((source,), (version,)) = (await stored_sources(scraping.db), await versions(scraping.db))
    metadata = json.loads((await scraping.files())[f"{version.storage_key}/metadata.json"])
    assert list(metadata) == ["discovery", "fetch", "content", "extraction", "identity"]
    assert "version_no" not in json.dumps(metadata)  # given only at commit
    assert metadata["discovery"] == {
        "feed": {"id": str(feed.id), "slug": "news", "name": "News", "kind": "rss", "url": FEED},
        "listed": {
            "url": ARTICLE,
            "title": "Heat network approved",
            "published_at": "2026-10-16T05:30:00+00:00",
            "summary": "Building starts next year.",
            "author": "Jane Doe",
        },
    }
    fetch = metadata["fetch"]
    assert {key: fetch[key] for key in ("fetcher", "requested_url", "final_url", "status")} == {
        "fetcher": "http",
        "requested_url": ARTICLE,
        "final_url": ARTICLE,
        "status": 200,
    }
    assert {"etag": '"v1"', "content-type": "text/html; charset=utf-8"}.items() <= fetch[
        "headers"
    ].items()
    assert "set-cookie" not in fetch["headers"]  # never cookies
    assert fetch["robots"] == "allowed: no robots.txt"
    assert metadata["content"] == {
        "file": "raw.html",
        "media_type": "text/html",
        "charset": "utf-8",
        "size": len(page.encode()),
        "raw_sha256": hashlib.sha256(page.encode()).hexdigest(),
        "text_sha256": version.text_sha256,
    }
    assert metadata["extraction"] == {
        "extractor": "html",
        "version": version.extractor_version,
        "partial": False,
    }
    assert metadata["identity"] == {
        "source_id": str(source.id),
        "source_version_id": str(version.id),
        "url": ARTICLE,
        "run_id": str(run.id),
        "run_folder": version.storage_key.split("/")[0],
    }
    assert (source.etag, source.last_modified) == ('"v1"', "Fri, 16 Oct 2026 05:00:00 GMT")


async def test_a_second_run_with_the_same_feed_stores_nothing_new(scraping: Scraping) -> None:
    serve_article(scraping)
    scraping.web.serve(FEED, rss_feed(Entry(ARTICLE)), media_type=RSS)
    await scraping.add_feed("news", FEED)
    await scraping.run_now()
    files = await scraping.files()

    second = await scraping.run_now()

    assert second.result == {
        "feeds_read": 1,
        "versions_new": 0,
        "versions_unchanged": 1,  # checked again (tests/jobs/test_scrape_changes.py)
        "documents_failed": 0,
        "failed_feeds": [],
        "out_of_time": [],
        "feeds": [feed_outcome("news", items=1, unchanged=1)],
    }
    assert len(await versions(scraping.db)) == 1
    assert await scraping.files() == files
    assert (scraping.web.fetched(FEED), scraping.web.fetched(ARTICLE)) == (2, 2)


async def test_a_url_two_feeds_list_is_fetched_and_stored_once_under_the_first(
    scraping: Scraping,
) -> None:
    other = "https://news.test/2026/10/second-story"
    serve_article(scraping)
    serve_article(scraping, other, "Second story")
    tracked = f"{ARTICLE}/?utm_source=rss#comments"  # the same address, as another Feed links it
    scraping.web.serve(FEED, rss_feed(Entry(ARTICLE)), media_type=RSS)
    scraping.web.serve(WIRE, rss_feed(Entry(tracked), Entry(other)), media_type=RSS)
    first = await scraping.add_feed("news", FEED)
    second = await scraping.add_feed("wire", WIRE)

    await scraping.run_now()

    assert [r.url.path for r in scraping.web.requests if "news.test" in str(r.url)] == [
        "/robots.txt",
        "/feed.xml",
        "/2026/10/heat-network-approved",
        "/2026/10/second-story",
    ]
    stored = {(v.feed_id, v.storage_key.split("/")[1]) for v in await versions(scraping.db)}
    assert stored == {(first.id, "news"), (second.id, "wire")}
    assert [s.url for s in await stored_sources(scraping.db)] == [ARTICLE, other]


async def test_a_manual_run_files_under_its_request_time_a_scheduled_one_under_its_own(
    scraping: Scraping,
) -> None:
    scraping.web.serve(FEED, rss_feed(Entry(ARTICLE)), media_type=RSS)
    serve_article(scraping)
    await scraping.add_feed("news", FEED)
    scheduled = await scraping.run_scheduled()
    update = f"{ARTICLE}-update"
    scraping.web.serve(FEED, rss_feed(Entry(update)), media_type=RSS)
    serve_article(scraping, update)
    scraping.clock.now = REQUESTED

    manual = await scraping.run_now()

    folders = {v.run_id: v.storage_key.split("/")[0] for v in await versions(scraping.db)}
    assert folders[manual.id] == "2026-10-16T060007Z"  # the moment "Run now" was clicked
    named = datetime.strptime(folders[scheduled.id], "%Y-%m-%dT%H%M%SZ").replace(tzinfo=UTC)
    assert named == scheduled.scheduled_for.replace(microsecond=0)


async def test_private_and_non_http_addresses_are_refused_before_any_request(
    scraping: Scraping,
) -> None:
    """Listed directly or reached by a redirect: the request is never sent."""
    refused = [
        "https://internal.test/admin",  # resolves to 10.0.0.1
        "http://metadata.test/latest/meta-data/",  # a cloud's metadata address
        "ftp://news.test/file.txt",
        "https://unknown.invalid/page",  # does not resolve
        "https://news.test/go",  # redirects to localhost
        f"https://news.test/{'a' * 2048}",  # too long to be an address we keep
    ]
    scraping.web.dns["unknown.invalid"] = []
    scraping.web.redirect("https://news.test/go", "http://localhost:8000/api/audit")
    serve_article(scraping)
    entries = [Entry(url) for url in refused] + [Entry(ARTICLE)]
    scraping.web.serve(FEED, rss_feed(*entries), media_type=RSS)
    await scraping.add_feed("news", FEED)

    run = await scraping.run_now()

    assert scraping.web.hosts() == {"news.test"}
    robots = "https://news.test/robots.txt"
    assert [str(r.url) for r in scraping.web.requests] == [
        robots,
        FEED,
        "https://news.test/go",
        ARTICLE,
    ]
    assert (counts(run)["versions_new"], counts(run)["documents_failed"]) == (1, 6)
    assert [s.url for s in await stored_sources(scraping.db)] == [ARTICLE]


@pytest.mark.parametrize("chunked", [False, True], ids=["declared", "streamed"])
async def test_an_oversized_response_is_refused(scraping: Scraping, *, chunked: bool) -> None:
    huge = "https://news.test/huge"
    scraping.web.serve(huge, b"<html>" + b"a" * MAX_BYTES, chunked=chunked)
    scraping.web.serve(FEED, rss_feed(Entry(huge)), media_type=RSS)
    await scraping.add_feed("news", FEED)

    run = await scraping.run_now()

    assert (counts(run)["versions_new"], counts(run)["documents_failed"]) == (0, 1)
    assert await versions(scraping.db) == []
    assert await scraping.files() == {}


async def test_a_malformed_link_is_skipped_and_its_feed_goes_on(scraping: Scraping) -> None:
    serve_article(scraping)
    entries = [Entry("http://[::1/broken"), Entry(ARTICLE)]  # an IPv6 host without its bracket
    scraping.web.serve(FEED, rss_feed(*entries), media_type=RSS)
    await scraping.add_feed("news", FEED)

    run = await scraping.run_now()

    assert (counts(run)["versions_new"], counts(run)["documents_failed"]) == (1, 1)
    assert counts(run)["failed_feeds"] == []
    assert [s.url for s in await stored_sources(scraping.db)] == [ARTICLE]


class FailingOnceSink(Sink):
    """A sink whose disk fails once: the first file written is refused."""

    def __init__(self, uri: str) -> None:
        super().__init__(uri)
        self.failures = 1

    @override
    async def write(self, key: str, data: bytes) -> None:
        if self.failures:
            self.failures -= 1
            msg = "No space left on device"
            raise OSError(msg)
        await super().write(key, data)


async def test_an_unexpected_failure_skips_only_its_document(scraping: Scraping) -> None:
    """Any error of one document is that document's: the next is read, the Feed is OK.

    Nothing of it was committed, so the next run tries it again.
    """
    scraping.sink = FailingOnceSink(memory_sink_uri())
    second = f"{ARTICLE}-2"
    serve_article(scraping)
    serve_article(scraping, second, "Second story")
    scraping.web.serve(FEED, rss_feed(Entry(ARTICLE), Entry(second)), media_type=RSS)
    await scraping.add_feed("news", FEED)

    run = await scraping.run_now()

    assert run.status == JobStatus.SUCCEEDED
    assert (counts(run)["versions_new"], counts(run)["documents_failed"]) == (1, 1)
    (feed,) = [feed for feed in await stored_feeds(scraping.db) if feed.enabled]
    assert (feed.state, feed.last_error) == (FeedState.OK, None)

    again = await scraping.run_now()

    assert (counts(again)["versions_new"], counts(again)["documents_failed"]) == (1, 0)
    committed = [v for v in await versions(scraping.db) if v.state == VersionState.COMMITTED]
    assert len(committed) == 2


async def test_a_failing_feed_is_recorded_and_the_others_are_read(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(kinds.LISTERS, FeedKind.SITEMAP)  # no Lister
    serve_article(scraping)
    scraping.web.serve(FEED, rss_feed(Entry(ARTICLE)), media_type=RSS)
    scraping.web.serve("https://news.test/page", article_page("Not a feed", *TEXT))
    await scraping.add_feed("internal", "https://internal.test/feed")
    await scraping.add_feed("gone", "https://news.test/gone.xml")  # 404
    await scraping.add_feed("page", "https://news.test/page")
    await scraping.add_feed("api", "https://api.test/v1", kind=FeedKind.SITEMAP)
    await scraping.add_feed("news", FEED)

    run = await scraping.run_now()

    assert run.status == JobStatus.SUCCEEDED
    assert run.result == {
        "feeds_read": 5,
        "versions_new": 1,
        "versions_unchanged": 0,
        "documents_failed": 0,
        "failed_feeds": [
            {"feed": "internal", "reason": "unsafe address"},
            {"feed": "gone", "reason": "http 404"},
            {"feed": "page", "reason": "unreadable"},
            {"feed": "api", "reason": "no lister"},
        ],
        "out_of_time": [],
        "feeds": [  # in the order read, each with what it did; a failed listing: none unread
            feed_outcome("internal", unread=None, reason="unsafe address"),
            feed_outcome("gone", unread=None, reason="http 404"),
            feed_outcome("page", unread=None, reason="unreadable"),
            feed_outcome("api", unread=None, reason="no lister"),
            feed_outcome("news", items=1, new=1),
        ],
    }
    feeds = {feed.slug: feed for feed in await stored_feeds(scraping.db) if feed.enabled}
    assert {slug: (f.state, f.last_error) for slug, f in feeds.items()} == {
        "internal": (FeedState.FAILING, "unsafe address"),
        "gone": (FeedState.FAILING, "http 404"),
        "page": (FeedState.FAILING, "unreadable"),
        "api": (FeedState.FAILING, "no lister"),
        "news": (FeedState.OK, None),
    }
    assert all(feed.last_scraped_at for feed in feeds.values())


async def test_disabled_feeds_are_not_read(scraping: Scraping) -> None:
    await scraping.add_feed("news", FEED)
    await disable_all_feeds(scraping.db)

    run = await scraping.run_now()

    assert counts(run)["feeds_read"] == 0
    assert len(await stored_feeds(scraping.db)) == 1
    assert scraping.web.requests == []


async def test_a_document_without_an_extractor_is_skipped(scraping: Scraping) -> None:
    image = "https://news.test/chart.png"
    scraping.web.serve(image, b"\x89PNG\r\n", media_type="image/png")
    scraping.web.serve(FEED, rss_feed(Entry(image)), media_type=RSS)
    await scraping.add_feed("news", FEED)

    run = await scraping.run_now()

    assert (counts(run)["versions_new"], counts(run)["documents_failed"]) == (0, 1)


async def test_a_feed_naming_an_extractor_has_its_documents_read_by_it(scraping: Scraping) -> None:
    """Served as plain text, the page is still read as HTML: the Feed says so."""
    scraping.web.serve(
        ARTICLE, article_page("Heat network approved", *TEXT), media_type="text/plain"
    )
    scraping.web.serve(FEED, rss_feed(Entry(ARTICLE)), media_type=RSS)
    await scraping.add_feed("news", FEED, extractor="html")
    scraping.web.serve(WIRE, rss_feed(Entry(f"{ARTICLE}-copy")), media_type=RSS)
    scraping.web.serve(f"{ARTICLE}-copy", article_page("Copy", *TEXT))
    await scraping.add_feed("wire", WIRE, extractor="no-such-extractor")

    run = await scraping.run_now()

    assert (counts(run)["versions_new"], counts(run)["documents_failed"]) == (1, 1)
    (version,) = await versions(scraping.db)
    assert (version.extractor, version.media_type) == ("html", "text/plain")
    assert f"{version.storage_key}/raw.txt" in await scraping.files()


class CarryingLister:
    """An API-like Lister whose items carry their whole content: no page is fetched."""

    settings = ListerSettings

    async def list(self, feed: Feed, fetcher: Fetcher) -> list[Item]:
        del feed, fetcher
        page = article_page("Wärmenetz Weststadt", *TEXT).encode()
        return [Item(ARTICLE, title="Wärmenetz Weststadt", content=page, media_type="text/html")]


async def test_items_carrying_their_content_are_stored_without_a_fetch(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(kinds.LISTERS, FeedKind.SITEMAP, CarryingLister())
    await scraping.add_feed("carrying", "https://api.test/v1", kind=FeedKind.SITEMAP)

    run = await scraping.run_now()

    assert counts(run)["versions_new"] == 1
    assert scraping.web.requests == []
    (version,) = await versions(scraping.db)
    metadata = json.loads((await scraping.files())[f"{version.storage_key}/metadata.json"])
    assert (version.http_status, metadata["fetch"]) == (None, None)
    assert metadata["discovery"]["listed"]["title"] == "Wärmenetz Weststadt"
