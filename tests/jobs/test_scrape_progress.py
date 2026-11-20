"""How far a scrape run got, as it reports it for "Run now": Feed by Feed, and within each.

Through the scrape job's seam (a fake web, a `memory://` sink, the test database), and the
`Reporter` alone for its pace. Fake time passes only in the fetcher's pauses.
"""

from dataclasses import dataclass, field
from typing import override

import pytest

from infrasales.core.models import JSONValue
from infrasales.fetch.pacing import PAUSE_SECONDS
from infrasales.jobs import scrape
from infrasales.scheduler.registry import Notice
from tests.alerts.support import RecordingNotifier
from tests.scheduler.support import context_for, queued_run
from tests.scrape.support import (
    RSS,
    Entry,
    FakeTime,
    Scraping,
    article_page,
    feed_outcome,
    rss_feed,
)

pytestmark = pytest.mark.anyio

NEWS = "https://news.test/feed.xml"
WIRE = "https://wire.test/rss"
A = "https://news.test/2026/10/heat-network-approved"
B = "https://news.test/2026/10/second-story"
C = "https://news.test/2026/10/third-story"
TEXT = (
    "The town council approved the heat network for the old town at its June session.",
    "The municipal utility will lay ten kilometres of pipe and connect four hundred homes.",
    "The construction work is put out to tender this autumn, and building starts next May.",
)


def serve(scraping: Scraping, *urls: str) -> None:
    """The articles at `urls`, and the news Feed listing them."""
    for url in urls:
        scraping.web.serve(url, article_page(url.rsplit("/", 1)[-1], *TEXT))
    scraping.web.serve(NEWS, rss_feed(*(Entry(url) for url in urls)), media_type=RSS)


async def reported(scraping: Scraping) -> list[JSONValue]:
    """Each progress the scrape job reports, in order, as it runs once."""
    reports: list[JSONValue] = []

    async def report(progress: JSONValue) -> None:
        reports.append(progress)

    run_id = await queued_run(scraping.db, "scrape")
    await scraping.registry()["scrape"].run(context_for(run_id, scraping.db, progress=report))
    return reports


def underway(feed: str, items: int | None = None, done: int = 0, new: int = 0) -> JSONValue:
    return {"feed": feed, "items": items, "done": done, "new": new}


def progress(
    done: int, new: int = 0, current: JSONValue = None, latest: JSONValue = None
) -> JSONValue:
    return {
        "feeds_total": 2,
        "feeds_done": done,
        "versions_new": new,
        "current": current,
        "latest": latest,
    }


async def test_a_feed_is_reported_when_it_starts_once_listed_while_read_and_at_its_end(
    scraping: Scraping,
) -> None:
    serve(scraping, A, B)  # one host: the fetcher pauses between its requests, time passes
    await scraping.add_feed("news", NEWS)
    await scraping.add_feed("wire", WIRE)  # 404: never listed

    reports = await reported(scraping)

    news = feed_outcome("news", items=2, new=2)
    assert reports == [
        progress(0, current=underway("news")),  # "Feed 1 of 2 · news · getting its list of items…"
        progress(0, current=underway("news", items=2)),
        progress(0, 1, current=underway("news", items=2, done=1, new=1)),
        # the last item: no report of its own, the Feed's end follows at once
        progress(1, 2, latest=news),
        progress(1, 2, current=underway("wire"), latest=news),
        progress(2, 2, latest=feed_outcome("wire", unread=None, reason="http 404")),
    ]


async def test_items_read_in_no_time_are_not_reported_one_by_one(scraping: Scraping) -> None:
    serve(scraping, A, A, A, A)  # A fetched once, after a pause; then `seen`, in no time
    await scraping.add_feed("news", NEWS)

    reports = await reported(scraping)

    assert [report["current"] for report in reports if isinstance(report, dict)] == [
        underway("news"),
        underway("news", items=4),
        underway("news", items=4, done=1, new=1),  # the next two within 2 s of it: not told
        None,  # its end
    ]


@dataclass
class SlowAlerts(RecordingNotifier):
    """Takes `seconds` of `time` to hand a notice over: a slow alert channel."""

    time: FakeTime = field(default_factory=FakeTime)
    seconds: float = 30.0

    @override
    async def notify(self, notice: Notice) -> None:
        self.time.now += self.seconds
        await super().notify(notice)


async def test_a_feeds_time_is_its_requests_not_its_reports_or_the_alert_that_it_is_blocked(
    scraping: Scraping,
) -> None:
    scraping.web.serve(NEWS, "Forbidden", status=403)  # robots.txt, a pause, its list: blocked
    await scraping.add_feed("news", NEWS)
    scraping.web.serve(WIRE, rss_feed(), media_type=RSS)
    await scraping.add_feed("wire", WIRE)  # read: the run does not fail
    scraping.alerts = SlowAlerts(time=scraping.web.time)
    time = scraping.web.time

    async def slow_database(_: JSONValue) -> None:
        time.now += 5

    run_id = await queued_run(scraping.db, "scrape")
    job = scraping.registry()["scrape"].run
    result = await job(context_for(run_id, scraping.db, progress=slow_database))

    assert len(scraping.alerts.notices) == 1
    assert isinstance(result, dict)
    assert result["feeds"] == [
        feed_outcome("news", unread=None, reason="blocked", seconds=PAUSE_SECONDS),
        feed_outcome("wire", seconds=PAUSE_SECONDS),  # the same: robots.txt, a pause, its list
    ]


async def test_a_run_now_keeps_its_last_progress_beside_its_result(scraping: Scraping) -> None:
    scraping.web.serve(NEWS, rss_feed(), media_type=RSS)
    await scraping.add_feed("news", NEWS)

    run = await scraping.run_now()

    assert run.progress == {
        "feeds_total": 1,
        "feeds_done": 1,
        "versions_new": 0,
        "current": None,
        "latest": feed_outcome("news"),
    }


async def test_the_reporter_tells_items_at_most_every_few_seconds_and_milestones_at_once() -> None:
    time, told = FakeTime(), list[JSONValue]()

    async def keep(progress: JSONValue) -> None:
        told.append(progress)

    reporter = scrape.Reporter(keep, 1, time, every=2.0)
    news = scrape.FeedOutcome("news", items=5, unread=5)
    result = scrape.ScrapeResult(feeds_read=1, feeds=[news])

    await reporter.started(result, news)
    await reporter.listed(result)
    for seconds in (0.5, 1.0, 0.5, 1.5):  # each item takes as long, after the list at 0
        time.now += seconds
        news.unread = (news.unread or 0) - 1
        await reporter.item(result)
    await reporter.finished(result)

    currents = [report["current"] for report in told if isinstance(report, dict)]
    assert currents == [
        {"feed": "news", "items": None, "done": 0, "new": 0},
        {"feed": "news", "items": 5, "done": 0, "new": 0},
        {"feed": "news", "items": 5, "done": 3, "new": 0},  # 2 s after the list
        None,  # the end: told however soon after
    ]
