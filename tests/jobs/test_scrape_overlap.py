"""Feed overlap: each Feed's outcome counts which of its addresses other Feeds list too.

Through the scrape job's seam: the Worker, a fake web, a `memory://` sink, the test database.
"""

import pytest
from sqlmodel import col, update

from infrasales.core.models import JSONValue
from infrasales.feeds.models import Feed
from infrasales.jobs import overlap as feed_overlap
from infrasales.scheduler.models import JobRun
from tests.scrape.support import (
    RSS,
    Entry,
    Scraping,
    article_page,
    counts,
    feed_outcome,
    overlap,
    rss_feed,
)

pytestmark = pytest.mark.anyio

NEWS = "https://news.test/feed.xml"
WIRE = "https://wire.test/rss"
ARCHIVE = "https://archive.test/rss"
A = "https://news.test/2026/10/heat-network-approved"
B = "https://news.test/2026/10/second-story"
C = "https://news.test/2026/10/third-story"
TEXT = (
    "The town council approved the heat network for the old town at its June session.",
    "The municipal utility will lay ten kilometres of pipe and connect four hundred homes.",
    "The construction work is put out to tender this autumn, and building starts next May.",
)


def serve_articles(scraping: Scraping, *urls: str) -> None:
    for url in urls:
        scraping.web.serve(url, article_page(url.rsplit("/", 1)[-1], *TEXT))


def lists(scraping: Scraping, feed: str, *urls: str) -> None:
    """The Feed at `feed` lists `urls`, from now on."""
    scraping.web.serve(feed, rss_feed(*(Entry(url) for url in urls)), media_type=RSS)


async def disable(scraping: Scraping, slug: str) -> None:
    async with scraping.db.session() as session:
        await session.exec(update(Feed).where(col(Feed.slug) == slug).values(enabled=False))


def overlaps(run: JobRun) -> dict[str, JSONValue]:
    """Each Feed's `overlap` in the run's result, by slug."""
    feeds = counts(run)["feeds"]
    assert isinstance(feeds, list)
    found: dict[str, JSONValue] = {}
    for feed in feeds:
        assert isinstance(feed, dict)
        slug = feed["feed"]
        assert isinstance(slug, str)
        found[slug] = feed["overlap"]
    return found


async def test_an_address_two_feeds_list_in_one_run_is_shared_by_both(scraping: Scraping) -> None:
    serve_articles(scraping, A, B, C)
    lists(scraping, NEWS, A, B)
    lists(scraping, WIRE, f"{A}/?utm_source=rss", C)  # A again, as the wire links it
    await scraping.add_feed("news", NEWS)
    await scraping.add_feed("wire", WIRE)

    run = await scraping.run_now()

    assert counts(run)["feeds"] == [
        feed_outcome("news", items=2, new=2, overlap=overlap(1, 1, listed_with={"wire": 1})),
        feed_outcome(
            "wire", items=2, new=1, seen=1, overlap=overlap(1, 1, listed_with={"news": 1})
        ),
    ]


async def test_an_address_a_feed_lists_twice_stays_its_own(scraping: Scraping) -> None:
    serve_articles(scraping, A)
    lists(scraping, NEWS, A, A)
    await scraping.add_feed("news", NEWS)

    run = await scraping.run_now()

    assert counts(run)["feeds"] == [
        feed_outcome("news", items=2, new=1, seen=1, overlap=overlap(1))
    ]


async def test_a_known_source_filed_under_another_feed_is_shared_with_it(
    scraping: Scraping,
) -> None:
    serve_articles(scraping, A, B)
    lists(scraping, NEWS, A)
    lists(scraping, WIRE)
    await scraping.add_feed("news", NEWS)
    await scraping.add_feed("wire", WIRE)
    await scraping.run_now()  # A is filed under news
    lists(scraping, NEWS, B)  # news lists A no more
    lists(scraping, WIRE, A)

    run = await scraping.run_now()

    assert overlaps(run) == {
        "news": overlap(1),
        "wire": overlap(0, 1, filed_under={"news": 1}),  # only the wire knows: news filed A
    }


async def test_a_disabled_feed_a_source_is_filed_under_still_counts(scraping: Scraping) -> None:
    serve_articles(scraping, A)
    lists(scraping, ARCHIVE, A)
    await scraping.add_feed("archive", ARCHIVE)
    await scraping.run_now()  # A is filed under the archive
    await disable(scraping, "archive")
    lists(scraping, NEWS, A)
    lists(scraping, WIRE, A)
    await scraping.add_feed("news", NEWS)
    await scraping.add_feed("wire", WIRE)

    run = await scraping.run_now()

    assert overlaps(run) == {
        "news": overlap(0, 1, listed_with={"wire": 1}, filed_under={"archive": 1}),
        "wire": overlap(0, 1, listed_with={"news": 1}, filed_under={"archive": 1}),
    }


async def test_a_feed_listing_in_the_run_what_is_filed_under_it_counts_once(
    scraping: Scraping,
) -> None:
    """The wire, read after the news, filed A: listed by both in this run, it is counted so."""
    serve_articles(scraping, A)
    lists(scraping, NEWS)
    lists(scraping, WIRE, A)
    await scraping.add_feed("news", NEWS)
    await scraping.add_feed("wire", WIRE)
    await scraping.run_now()  # A is filed under the wire
    lists(scraping, NEWS, A)

    run = await scraping.run_now()

    assert overlaps(run) == {
        "news": overlap(0, 1, listed_with={"wire": 1}),
        "wire": overlap(0, 1, listed_with={"news": 1}),
    }


async def test_the_reported_progress_counts_the_overlap_of_the_feeds_read_so_far(
    scraping: Scraping,
) -> None:
    serve_articles(scraping, A)
    lists(scraping, NEWS, A)
    lists(scraping, WIRE, A)
    await scraping.add_feed("news", NEWS)
    await scraping.add_feed("wire", WIRE)

    run = await scraping.run_now()

    assert isinstance(run.progress, dict)
    latest = run.progress["latest"]
    assert isinstance(latest, dict)
    assert latest["overlap"] == overlap(0, 1, listed_with={"news": 1})


async def test_the_feed_overlap_report_sums_what_the_runs_counted(scraping: Scraping) -> None:
    serve_articles(scraping, A, B, C)
    lists(scraping, NEWS, A, B)
    lists(scraping, WIRE, A, C)
    await scraping.add_feed("news", NEWS)
    await scraping.add_feed("wire", WIRE)
    await scraping.run_now()
    await scraping.run_now()

    async with scraping.db.session() as session:
        report = await feed_overlap.report(session, scraping.clock(), 14)

    assert report.runs == 2
    assert [(f.feed, f.own, f.shared, f.own_share) for f in report.feeds] == [
        ("news", 2, 2, 0.5),
        ("wire", 2, 2, 0.5),
    ]
    assert [(p.feed, p.other, p.listings) for p in report.pairs] == [("news", "wire", 2)]
