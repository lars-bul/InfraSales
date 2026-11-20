"""The scrape job collects politely and keeps going (BIG-21), seen through the Worker.

robots.txt, pauses between requests to one site, bot walls, one Feed failing or all, the
quality gate (`partial`), and the run's time budget. Time is fake (`FakeWeb.time`): it passes
only when the fetcher pauses, so the pauses are measured, not waited for.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial

import httpx2
import pytest

from infrasales.extract import registry
from infrasales.extract.html import HtmlExtractor
from infrasales.feeds.models import Feed, FeedKind, FeedState
from infrasales.fetch.pacing import PAUSE_SECONDS
from infrasales.fetch.robots import CACHE_SECONDS, MAX_ROBOTS_BYTES
from infrasales.jobs.scrape import scrape_job
from infrasales.scheduler.models import JobStatus
from infrasales.scheduler.registry import ScheduledJob
from infrasales.scheduler.worker import Worker
from tests.scheduler.support import FAST
from tests.scrape.support import (
    PDF,
    RSS,
    Entry,
    Scraping,
    article_page,
    counts,
    feed_outcome,
    pdf_document,
    rss_feed,
    stored_feeds,
    stored_run,
    stored_sources,
)
from tests.scrape.support import stored_versions as versions

pytestmark = pytest.mark.anyio

FEED = "https://news.test/feed.xml"
ROBOTS = "https://news.test/robots.txt"
WIRE = "https://wire.test/rss"
TEXT = (
    "The town council approved the heat network for the old town at its June session.",
    "The municipal utility will lay ten kilometres of pipe and connect four hundred homes.",
    "The construction work is put out to tender this autumn, and building starts next May.",
)


def article(scraping: Scraping, path: str, title: str = "Heat network approved") -> str:
    url = f"https://news.test/{path}"
    scraping.web.serve(url, article_page(title, *TEXT))
    return url


async def test_robots_txt_keeps_disallowed_urls_unfetched_and_sets_the_pace(
    scraping: Scraping,
) -> None:
    allowed, private = article(scraping, "news/a"), article(scraping, "private/b")
    scraping.web.serve(
        ROBOTS,
        "User-agent: *\nDisallow: /\n\n"
        "User-agent: InfraSalesBot\nDisallow: /private/\nCrawl-delay: 30\n",
        media_type="text/plain",
    )
    scraping.web.serve(FEED, rss_feed(Entry(allowed), Entry(private)), media_type=RSS)
    await scraping.add_feed("news", FEED)

    run = await scraping.run_now()

    assert (counts(run)["versions_new"], counts(run)["documents_failed"]) == (1, 1)
    assert scraping.web.fetched(private) == 0
    assert [str(r.url) for r in scraping.web.requests] == [ROBOTS, FEED, allowed]
    assert scraping.web.times("news.test") == [0, 30, 60]  # Crawl-delay apart
    (version,) = await versions(scraping.db)
    metadata = json.loads((await scraping.files())[f"{version.storage_key}/metadata.json"])
    assert metadata["fetch"]["robots"] == "allowed"


def refuse(request: httpx2.Request) -> httpx2.Response:
    msg = "connection refused"
    raise httpx2.ConnectError(msg, request=request)


@pytest.mark.parametrize(
    ("robots", "fetched", "walled"),
    [
        (httpx2.Response(200, text="User-agent: *\nDisallow: /news/\n"), False, False),
        (httpx2.Response(200, text="User-agent: *\nAllow: /\n"), True, False),
        (
            httpx2.Response(
                200, text="User-agent: *\nDisallow: /news/\n#" + "-" * MAX_ROBOTS_BYTES
            ),
            False,
            False,
        ),
        (httpx2.Response(404), True, False),  # none: everything allowed
        (httpx2.Response(401), True, False),  # likewise (RFC 9309: 4xx is "unavailable")
        (httpx2.Response(429, text="slow down"), False, False),  # unreachable: nothing allowed
        (httpx2.Response(503), False, False),
        (httpx2.Response(302, headers={"location": "http://internal.test/"}), False, False),
        (refuse, False, False),
        (httpx2.Response(429, text="<title>Vercel Security Checkpoint</title>"), False, True),
        (httpx2.Response(200, headers={"cf-mitigated": "challenge"}), False, True),
        (httpx2.Response(302, headers={"location": "https://unblock.news.test/"}), False, True),
    ],
    ids=[
        "disallowed",
        "allowed",
        "huge",  # read up to 500 KiB
        "none",
        "unauthorized",
        "busy",
        "server error",
        "unsafe redirect",
        "no answer",
        "bot wall",
        "challenge",
        "access page",
    ],
)
async def test_how_a_robots_txt_answer_is_read(
    scraping: Scraping,
    robots: httpx2.Response | Callable[[httpx2.Request], httpx2.Response],
    *,
    fetched: bool,
    walled: bool,
) -> None:
    story = article(scraping, "news/a")
    scraping.web.route(ROBOTS, robots if callable(robots) else lambda _: robots)
    scraping.web.serve(WIRE, rss_feed(Entry(story)), media_type=RSS)
    await scraping.add_feed("wire", WIRE)

    run = await scraping.run_now()

    assert scraping.web.fetched(story) == fetched
    assert scraping.web.hosts() <= {"news.test", "wire.test", "unblock.news.test"}  # never internal
    assert len(await versions(scraping.db)) == fetched
    (feed,) = [feed for feed in await stored_feeds(scraping.db) if feed.enabled]
    assert feed.last_error is None  # the wall is the story's site's, not the Feed's
    sites = ["news.test"] if walled else []
    assert counts(run)["feeds"] == [
        feed_outcome("wire", items=1, new=int(fetched), failed=int(not fetched), walled=sites)
    ]


async def test_a_feed_robots_txt_disallows_fails_with_the_reason(scraping: Scraping) -> None:
    scraping.web.serve(ROBOTS, "User-agent: InfraSalesBot\nDisallow: /feed.xml\n")
    await scraping.add_feed("news", FEED)
    scraping.web.serve(WIRE, rss_feed(), media_type=RSS)
    await scraping.add_feed("wire", WIRE)

    run = await scraping.run_now()

    assert scraping.web.fetched(FEED) == 0
    reason = "disallowed by robots.txt"
    assert counts(run)["failed_feeds"] == [{"feed": "news", "reason": reason}]


async def test_robots_txt_is_read_once_a_day_across_runs(scraping: Scraping) -> None:
    """RFC 9309 §2.4: a cached robots.txt is used for a day at most."""
    scraping.web.serve(ROBOTS, "User-agent: *\nDisallow: /private/\n", media_type="text/plain")
    scraping.web.serve(FEED, rss_feed(Entry(article(scraping, "news/a"))), media_type=RSS)
    await scraping.add_feed("news", FEED)

    for _ in range(3):  # every 3 hours, for a day
        await scraping.run_now()
    reads_in_a_day = scraping.web.fetched(ROBOTS)
    scraping.web.time.now += CACHE_SECONDS
    await scraping.run_now()

    assert (reads_in_a_day, scraping.web.fetched(ROBOTS)) == (1, 2)


async def test_an_unreachable_robots_txt_is_asked_again_by_the_next_run(
    scraping: Scraping,
) -> None:
    """Unreachable means nothing is allowed: kept for one run only, not for a day."""
    scraping.web.serve(ROBOTS, "Service unavailable", status=503)
    scraping.web.serve(FEED, rss_feed(Entry(article(scraping, "news/a"))), media_type=RSS)
    await scraping.add_feed("news", FEED)
    scraping.web.serve(WIRE, rss_feed(), media_type=RSS)
    await scraping.add_feed("wire", WIRE)  # read: the run does not fail

    first = await scraping.run_now()
    scraping.web.serve(ROBOTS, "User-agent: *\nAllow: /\n", media_type="text/plain")
    second = await scraping.run_now()

    assert counts(first)["failed_feeds"] == [{"feed": "news", "reason": "robots.txt unreachable"}]
    assert (counts(second)["failed_feeds"], counts(second)["versions_new"]) == ([], 1)
    assert scraping.web.fetched(ROBOTS) == 2


async def test_requests_to_one_site_are_paused_requests_to_others_are_not(
    scraping: Scraping,
) -> None:
    first, second = article(scraping, "news/a"), article(scraping, "news/b")
    elsewhere = "https://wire.test/story"
    scraping.web.serve(elsewhere, article_page("Elsewhere", *TEXT))
    entries = (Entry(first), Entry(elsewhere), Entry(second))
    scraping.web.serve(FEED, rss_feed(*entries), media_type=RSS)
    await scraping.add_feed("news", FEED)

    await scraping.run_now()

    assert [r.url.host for r in scraping.web.requests] == [
        "news.test",  # robots.txt: none (404), so everything is allowed
        "news.test",  # the feed
        "news.test",  # first
        "wire.test",  # robots.txt
        "wire.test",  # elsewhere
        "news.test",  # second
    ]
    pause = PAUSE_SECONDS
    assert scraping.web.times("news.test") == [0, pause, 2 * pause, 3 * pause]
    assert scraping.web.times("wire.test") == [2 * pause, 3 * pause]
    assert [s.url for s in await stored_sources(scraping.db)] == [first, elsewhere, second]
    run_files = await scraping.files()
    assert all(
        json.loads(data)["fetch"]["robots"] == "allowed: no robots.txt"
        for key, data in run_files.items()
        if key.endswith("metadata.json")
    )


async def test_a_feed_behind_a_bot_wall_is_blocked_and_alerted_the_others_go_on(
    scraping: Scraping,
) -> None:
    walled = "https://walled.test/feed/"
    checkpoint = "<html><title>Vercel Security Checkpoint</title>Verifying your browser</html>"
    scraping.web.serve(walled, checkpoint, status=429)
    allowed = article(scraping, "news/a")
    scraping.web.serve(FEED, rss_feed(Entry(allowed)), media_type=RSS)
    await scraping.add_feed("walled", walled)
    await scraping.add_feed("news", FEED)

    run = await scraping.run_now()

    assert run.status == JobStatus.SUCCEEDED
    assert counts(run)["failed_feeds"] == [{"feed": "walled", "reason": "blocked"}]
    assert counts(run)["versions_new"] == 1
    feeds = {feed.slug: feed for feed in await stored_feeds(scraping.db) if feed.enabled}
    assert (feeds["walled"].state, feeds["walled"].last_error) == (FeedState.BLOCKED, "blocked")
    assert feeds["news"].state == FeedState.OK
    (notice,) = scraping.alerts.notices
    assert notice.subject() == "infrasales: the Feed walled is blocked"
    assert "https://walled.test/feed/" in notice.text()
    assert scraping.web.fetched(walled) == 1  # nothing tries again, or around it


@pytest.mark.parametrize("status", [401, 403, 451])
async def test_a_block_answer_for_one_document_fails_only_that_document(
    scraping: Scraping, status: int
) -> None:
    refused = "https://news.test/members/only"
    scraping.web.serve(refused, "Forbidden", status=status)
    other = article(scraping, "news/other")
    scraping.web.serve(FEED, rss_feed(Entry(refused), Entry(other)), media_type=RSS)
    await scraping.add_feed("news", FEED)

    run = await scraping.run_now()

    assert run.status == JobStatus.SUCCEEDED
    assert (counts(run)["versions_new"], counts(run)["documents_failed"]) == (1, 1)
    assert counts(run)["failed_feeds"] == []
    assert (await _feed(scraping, "news")).state == FeedState.OK
    assert scraping.alerts.notices == []


@pytest.mark.parametrize("lister", ["rss", "sitemap index"], ids=["feed url", "child sitemap"])
async def test_a_block_answer_to_a_listing_request_blocks_the_feed(
    scraping: Scraping, lister: str
) -> None:
    if lister == "rss":
        scraping.web.serve(FEED, "Forbidden", status=403)
        await scraping.add_feed("news", FEED)
    else:
        index, child = "https://news.test/sitemap.xml", "https://news.test/sitemap-1.xml"
        scraping.web.serve(
            index,
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<sitemap><loc>{child}</loc></sitemap></sitemapindex>",
            media_type="application/xml",
        )
        scraping.web.serve(child, "Forbidden", status=403)
        await scraping.add_feed("news", index, kind=FeedKind.SITEMAP)
    scraping.web.serve(WIRE, rss_feed(), media_type=RSS)
    await scraping.add_feed("wire", WIRE)

    run = await scraping.run_now()

    assert counts(run)["failed_feeds"] == [{"feed": "news", "reason": "blocked"}]
    assert (await _feed(scraping, "news")).state == FeedState.BLOCKED
    assert len(scraping.alerts.notices) == 1


@pytest.mark.parametrize(
    "headers",
    [{"cf-mitigated": "challenge"}, {"x-vercel-mitigated": "challenge"}],
    ids=["cloudflare", "vercel"],
)
async def test_a_challenge_on_one_document_of_its_own_site_blocks_the_feed(
    scraping: Scraping, headers: dict[str, str]
) -> None:
    challenged = "https://news.test/2026/10/rule"
    scraping.web.serve(challenged, "Forbidden", status=403, headers=headers)
    other = article(scraping, "news/other")
    scraping.web.serve(FEED, rss_feed(Entry(challenged), Entry(other)), media_type=RSS)
    await scraping.add_feed("news", FEED)
    scraping.web.serve(WIRE, rss_feed(), media_type=RSS)
    await scraping.add_feed("wire", WIRE)

    run = await scraping.run_now()

    assert counts(run)["failed_feeds"] == [{"feed": "news", "reason": "blocked"}]
    assert scraping.web.fetched(other) == 0  # the Feed stops at the wall
    assert counts(run)["feeds"] == [
        feed_outcome("news", items=2, unread=2, reason="blocked"),  # none of them read
        feed_outcome("wire"),
    ]


async def test_a_challenge_on_another_sites_document_fails_it_and_the_run_leaves_that_site(
    scraping: Scraping,
) -> None:
    links = "https://links.test/feed.xml"  # an aggregator, like Heizungsforum: it links anywhere
    first, second = "https://walled.test/2026/10/a", "https://www.walled.test/2026/10/b"
    for url in (first, second):
        scraping.web.serve(url, "Forbidden", status=403, headers={"cf-mitigated": "challenge"})
    other = article(scraping, "news/other")
    scraping.web.serve(links, rss_feed(Entry(first), Entry(second), Entry(other)), media_type=RSS)
    await scraping.add_feed("links", links)

    run = await scraping.run_now()

    assert counts(run)["failed_feeds"] == []
    assert (counts(run)["versions_new"], counts(run)["documents_failed"]) == (1, 2)
    assert (scraping.web.fetched(first), scraping.web.fetched(second)) == (1, 0)  # not around it
    assert counts(run)["feeds"] == [
        feed_outcome("links", items=3, new=1, failed=2, walled=["walled.test"])
    ]
    assert (await _feed(scraping, "links")).state == FeedState.OK
    assert scraping.alerts.notices == []


async def test_a_sites_own_feed_is_still_blocked_by_the_wall_another_feed_met(
    scraping: Scraping,
) -> None:
    links, own = "https://links.test/feed.xml", "https://walled.test/feed.xml"
    first, second = "https://walled.test/2026/10/a", "https://walled.test/2026/10/b"
    for url in (first, second):
        scraping.web.serve(url, "Forbidden", status=403, headers={"cf-mitigated": "challenge"})
    scraping.web.serve(links, rss_feed(Entry(first)), media_type=RSS)
    scraping.web.serve(own, rss_feed(Entry(second)), media_type=RSS)
    await scraping.add_feed("links", links)  # read first: the older Feed
    await scraping.add_feed("walled", own)

    run = await scraping.run_now()

    assert counts(run)["failed_feeds"] == [{"feed": "walled", "reason": "blocked"}]
    assert scraping.web.fetched(second) == 1  # its own site is asked: the wall is the Feed's
    assert (await _feed(scraping, "walled")).state == FeedState.BLOCKED
    assert (await _feed(scraping, "links")).state == FeedState.OK
    assert len(scraping.alerts.notices) == 1


@pytest.mark.parametrize(
    "wall",
    [
        "https://unblock.news.test/?blocked=true",  # Förderregister: 200 "Request Access"
        "https://geo.captcha-delivery.com/captcha/?initialCid=x",  # DataDome
        "https://news.test/cdn-cgi/challenge-platform/h/b/orchestrate",  # Cloudflare
    ],
)
async def test_a_redirect_to_an_access_page_is_a_bot_wall_not_a_document(
    scraping: Scraping, wall: str
) -> None:
    story = "https://news.test/2026/10/rule"
    scraping.web.redirect(story, wall)
    scraping.web.serve(wall, article_page("Request Access", *TEXT))
    other = article(scraping, "news/other")
    scraping.web.serve(FEED, rss_feed(Entry(story), Entry(other)), media_type=RSS)
    await scraping.add_feed("news", FEED)
    scraping.web.serve(WIRE, rss_feed(), media_type=RSS)
    await scraping.add_feed("wire", WIRE)

    run = await scraping.run_now()

    assert counts(run)["failed_feeds"] == [{"feed": "news", "reason": "blocked"}]
    assert await versions(scraping.db) == []
    assert scraping.web.fetched(other) == 0  # the Feed stops at the wall


async def test_a_feed_still_blocked_is_not_alerted_again_and_is_ok_once_unblocked(
    scraping: Scraping,
) -> None:
    walled = "https://walled.test/feed/"
    scraping.web.serve(walled, "Forbidden", status=403)
    await scraping.add_feed("walled", walled)
    scraping.web.serve(FEED, rss_feed(Entry(article(scraping, "news/a"))), media_type=RSS)
    await scraping.add_feed("news", FEED)
    await scraping.run_now()

    await scraping.run_now()

    assert len(scraping.alerts.notices) == 1
    scraping.web.serve(walled, rss_feed(), media_type=RSS)
    await scraping.run_now()
    feeds = {feed.slug: feed for feed in await stored_feeds(scraping.db) if feed.enabled}
    assert (feeds["walled"].state, feeds["walled"].last_error) == (FeedState.OK, None)


async def test_a_blocked_feed_whose_alert_failed_is_alerted_again_by_the_next_run(
    scraping: Scraping,
) -> None:
    walled = "https://walled.test/feed/"
    scraping.web.serve(walled, "Forbidden", status=403)
    await scraping.add_feed("walled", walled)
    scraping.web.serve(FEED, rss_feed(), media_type=RSS)
    await scraping.add_feed("news", FEED)
    scraping.alerts.error = ConnectionError("the mail server is down")

    run = await scraping.run_now()

    assert run.status == JobStatus.SUCCEEDED
    walled_feed = await _feed(scraping, "walled")
    assert (walled_feed.state, walled_feed.last_error) == (FeedState.FAILING, "blocked")
    scraping.alerts.error = None
    await scraping.run_now()
    assert [notice.subject() for notice in scraping.alerts.notices] == 2 * [
        "infrasales: the Feed walled is blocked"
    ]
    assert (await _feed(scraping, "walled")).state == FeedState.BLOCKED  # told: news once
    await scraping.run_now()
    assert len(scraping.alerts.notices) == 2


async def test_a_blocked_feed_is_recorded_blocked_when_nobody_is_to_be_told(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    walled = "https://walled.test/feed/"
    scraping.web.serve(walled, "Forbidden", status=403)
    await scraping.add_feed("walled", walled)
    scraping.web.serve(FEED, rss_feed(), media_type=RSS)
    await scraping.add_feed("news", FEED)
    # No alert channel configured: the catalog binds no notifier.
    network = scraping.web.network()
    job = partial(scrape_job, db=scraping.db, sink=scraping.sink, network=network)
    monkeypatch.setattr(scraping, "registry", lambda: {"scrape": ScheduledJob(run=job)})

    run = await scraping.run_now()

    assert run.status == JobStatus.SUCCEEDED
    assert (await _feed(scraping, "walled")).state == FeedState.BLOCKED
    assert scraping.alerts.notices == []


async def _feed(scraping: Scraping, slug: str) -> Feed:
    (feed,) = [feed for feed in await stored_feeds(scraping.db) if feed.slug == slug]
    return feed


async def test_when_every_feed_fails_the_run_fails_and_is_retried(scraping: Scraping) -> None:
    await scraping.add_feed("gone", "https://news.test/gone.xml")  # 404
    await scraping.add_feed("walled", "https://walled.test/feed/")
    scraping.web.serve("https://walled.test/feed/", "Forbidden", status=403)

    run = await scraping.run_now()

    assert (run.status, run.error, run.attempts) == (JobStatus.PENDING, "AllFeedsFailedError", 1)
    assert run.run_after > run.scheduled_for  # retried later, like any failing run
    feeds = {feed.slug: feed for feed in await stored_feeds(scraping.db) if feed.enabled}
    assert {slug: f.last_error for slug, f in feeds.items()} == {
        "gone": "http 404",
        "walled": "blocked",
    }
    (alert,) = scraping.alerts.alerts  # the usual alert policy decides whether it is news yet
    assert (alert.outcome, alert.error) == ("retrying", "AllFeedsFailedError")
    assert scraping.alerts.notices[0].subject() == "infrasales: the Feed walled is blocked"


async def test_a_scrape_that_keeps_failing_is_alerted_by_the_job_alerts(
    scraping: Scraping,
) -> None:
    """US 18's "the scrape job keeps failing" is the scheduler's alert for a failing run.

    No alert of its own: a run fails when every Feed failed, and the job's alerts (policy and
    channels, ADR 01 "Alerting") say it keeps failing, then that it failed for good.
    """
    await scraping.add_feed("gone", "https://news.test/gone.xml")  # 404, every time

    run = await scraping.run_now()
    for _ in range(2):
        scraping.clock.advance(hours=1)
        assert await Worker(scraping.db, scraping.registry(), FAST, scraping.clock).tick()

    run = await stored_run(scraping.db, run.id)
    assert (run.status, run.attempts, run.error) == (JobStatus.FAILED, 3, "AllFeedsFailedError")
    alerts = scraping.alerts.alerts
    assert [(a.job, a.outcome, a.attempt) for a in alerts] == [
        ("scrape", "retrying", 1),
        ("scrape", "retrying", 2),
        ("scrape", "failed", 3),
    ]
    assert [a.subject() for a in alerts[1:]] == [
        "infrasales: scrape keeps failing",
        "infrasales: scrape failed",
    ]


async def test_a_run_without_enabled_feeds_succeeds(scraping: Scraping) -> None:
    run = await scraping.run_now()

    assert (run.status, counts(run)["feeds_read"]) == (JobStatus.SUCCEEDED, 0)


async def test_a_slow_site_gets_its_share_of_the_run_time_and_cannot_starve_the_others(
    scraping: Scraping,
) -> None:
    """A Crawl-delay of 60 s, 300 s for the run, two Feeds: each gets half of what is left."""
    slow = "https://slow.test/feed.xml"
    scraping.web.serve("https://slow.test/robots.txt", "User-agent: *\nCrawl-delay: 60\n")
    stories = [f"https://slow.test/story-{n}" for n in range(3)]
    for story in stories:
        scraping.web.serve(story, article_page("Slow story", *TEXT))
    scraping.web.serve(slow, rss_feed(*map(Entry, stories)), media_type=RSS)
    scraping.web.serve(FEED, rss_feed(Entry(article(scraping, "news/a"))), media_type=RSS)
    await scraping.add_feed("slow", slow)
    await scraping.add_feed("news", FEED)
    scraping.budget = 300

    run = await scraping.run_now()

    assert scraping.web.times("slow.test") == [0, 60, 120]  # robots.txt, feed, first story
    assert scraping.web.fetched(stories[1]) == 0  # at 180 s, after its share (150 s) ended
    assert scraping.web.times("news.test") == [120, 120 + PAUSE_SECONDS, 120 + 2 * PAUSE_SECONDS]
    assert run.status == JobStatus.SUCCEEDED
    assert (counts(run)["versions_new"], counts(run)["failed_feeds"]) == (2, [])
    assert counts(run)["out_of_time"] == [{"feed": "slow", "unread": 2}]  # the next run's
    assert counts(run)["feeds"] == [
        feed_outcome("slow", items=3, new=1, unread=2, out_of_time=True, seconds=120.0),
        feed_outcome("news", items=1, new=1, seconds=2 * PAUSE_SECONDS),
    ]
    feeds = {feed.slug: feed for feed in await stored_feeds(scraping.db) if feed.enabled}
    assert (feeds["slow"].state, feeds["slow"].last_error) == (FeedState.OK, None)
    assert feeds["slow"].last_scraped_at is not None


async def test_a_feed_whose_share_ends_before_it_is_listed_is_left_for_the_next_run(
    scraping: Scraping,
) -> None:
    slow = "https://slow.test/feed.xml"
    scraping.web.serve("https://slow.test/robots.txt", "User-agent: *\nCrawl-delay: 60\n")
    scraping.web.serve(slow, rss_feed(), media_type=RSS)
    await scraping.add_feed("slow", slow)
    scraping.budget = 30

    run = await scraping.run_now()

    assert run.status == JobStatus.SUCCEEDED  # not read is not failed
    assert scraping.web.fetched(slow) == 0
    assert counts(run)["out_of_time"] == [{"feed": "slow", "unread": None}]  # unknown: not listed
    assert counts(run)["feeds"] == [feed_outcome("slow", unread=None, out_of_time=True)]
    (feed,) = [feed for feed in await stored_feeds(scraping.db) if feed.enabled]
    assert (feed.state, feed.last_scraped_at) == (FeedState.OK, None)


PUBLISHED = datetime(2026, 10, 16, 5, 30, tzinfo=UTC)


def paywalled_page(title: str, teaser: str) -> str:
    """A subscriber article as a non-subscriber sees it, marked up as Google asks publishers to."""
    ld = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title,
        "isAccessibleForFree": False,
        "hasPart": {"@type": "WebPageElement", "isAccessibleForFree": False, "cssSelector": ".x"},
    }
    page = article_page(title, teaser, *TEXT[:2], "Subscribe to read the full story.")
    script = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    return page.replace("</head>", f"{script}</head>")


async def test_a_paywalled_article_is_stored_partial_with_what_the_feed_gave(
    scraping: Scraping,
) -> None:
    story = "https://news.test/2026/10/inside-the-tender"
    title, summary = "Inside the tender", "<p>How the <b>pipe tender</b> came together.</p>"
    scraping.web.serve(story, paywalled_page(title, "Exclusive: the tender took two years."))
    entry = Entry(story, title, summary, "Jane Doe", PUBLISHED)
    scraping.web.serve(FEED, rss_feed(entry), media_type=RSS)
    await scraping.add_feed("news", FEED)

    run = await scraping.run_now()

    assert counts(run)["versions_new"] == 1
    (version,) = await versions(scraping.db)
    files = await scraping.files()
    extracted = json.loads(files[f"{version.storage_key}/extracted.json"])
    assert version.partial
    assert {key: extracted[key] for key in ("title", "text", "published_at", "author")} == {
        "title": title,
        "text": "How the pipe tender came together.",  # the Feed's summary, as text
        "published_at": "2026-10-16T05:30:00+00:00",
        "author": "Jane Doe",
    }
    metadata = json.loads(files[f"{version.storage_key}/metadata.json"])
    assert metadata["extraction"]["partial"] is True
    assert metadata["discovery"]["listed"]["url"] == story  # the link
    assert metadata["content"]["text_sha256"] == version.text_sha256


@pytest.mark.parametrize(
    ("page", "partial"),
    [
        (article_page("Heat network approved", *TEXT), False),
        (article_page("Heat network approved", TEXT[0]), True),  # too short to be the whole text
        ("<html><body><p>" + " ".join(TEXT) + "</p></body></html>", True),  # no title
    ],
    ids=["complete", "too short", "no title"],
)
async def test_the_quality_gate_marks_incomplete_texts_partial(
    scraping: Scraping, page: str, *, partial: bool
) -> None:
    story = "https://news.test/2026/10/story"
    scraping.web.serve(story, page)
    scraping.web.serve(FEED, rss_feed(Entry(story)), media_type=RSS)  # no title, no summary
    await scraping.add_feed("news", FEED)

    await scraping.run_now()

    (version,) = await versions(scraping.db)
    extracted = json.loads((await scraping.files())[f"{version.storage_key}/extracted.json"])
    assert version.partial is partial
    assert TEXT[0] in extracted["text"]  # without a summary from the Feed, the text is kept


async def test_a_scanned_pdf_without_text_is_partial(scraping: Scraping) -> None:
    report = "https://news.test/report.pdf"
    scraping.web.serve(report, pdf_document("", title="Annual report"), media_type=PDF)
    entry = Entry(report, "Annual report 2026", "The authority's annual report.")
    scraping.web.serve(FEED, rss_feed(entry), media_type=RSS)
    await scraping.add_feed("news", FEED)

    await scraping.run_now()

    (version,) = await versions(scraping.db)
    extracted = json.loads((await scraping.files())[f"{version.storage_key}/extracted.json"])
    assert (version.partial, version.extractor) == (True, "pdf")
    assert extracted["text"] == "The authority's annual report."


class UpgradedHtml(HtmlExtractor):
    """The HTML extractor after an upgrade: a new version, the same output."""

    version = "3+test"


async def test_after_an_extractor_upgrade_an_unchanged_partial_version_stays_unchanged(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Like is compared with like: the latest raw file read again goes through the gate too."""
    story = "https://news.test/2026/10/inside-the-tender"
    scraping.web.serve(story, paywalled_page("Inside the tender", "Exclusive: two years."))
    entry = Entry(story, "Inside the tender", "How the pipe tender came together.")
    scraping.web.serve(FEED, rss_feed(entry), media_type=RSS)
    await scraping.add_feed("news", FEED)
    await scraping.run_now()
    monkeypatch.setitem(registry.EXTRACTORS, "html", UpgradedHtml())

    run = await scraping.run_now()

    assert (counts(run)["versions_new"], counts(run)["versions_unchanged"]) == (0, 1)
