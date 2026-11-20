"""A run's stored result, typed as the run history shows it."""

import pytest

from infrasales.core.models import JSONValue
from infrasales.jobs import schemas, scrape
from infrasales.jobs.names import JobName
from infrasales.jobs.schemas import SourceCollectionResult, typed_progress, typed_result


def test_a_source_collection_result_reads_as_the_scraper_stores_it() -> None:
    stored = scrape.ScrapeResult(
        4, 42, 7, 1, [scrape.FailedFeed("tiefbau-aktuell", "blocked")]
    ).to_json()

    assert typed_result(JobName.SCRAPE, stored) == SourceCollectionResult(
        feeds_read=4,
        versions_new=42,
        versions_unchanged=7,
        documents_failed=1,
        failed_feeds=[schemas.FailedFeed(feed="tiefbau-aktuell", reason="blocked")],
    )


def test_a_result_stored_before_the_feeds_were_kept_still_reads() -> None:
    stored = scrape.ScrapeResult(4, 42, 7, 1).to_json()
    del stored["feeds"], stored["out_of_time"]  # as runs stored it before

    result = typed_result(JobName.SCRAPE, stored)

    assert result
    assert (result.versions_new, result.feeds) == (42, [])


def test_each_feeds_outcome_reads_as_the_scraper_stores_it() -> None:
    outcome = scrape.FeedOutcome("slow", items=3, new=1, unread=2, out_of_time=True, seconds=150)
    outcome.overlap = scrape.FeedOverlap(own=0, shared=1, listed_with={"news": 1})
    stored = scrape.ScrapeResult(1, 1, 0, 0, feeds=[outcome]).to_json()

    result = typed_result(JobName.SCRAPE, stored)

    assert result
    assert result.feeds == [
        schemas.FeedOutcome(
            feed="slow",
            items=3,
            new=1,
            unchanged=0,
            known=0,
            seen=0,
            failed=0,
            unread=2,
            reason=None,
            out_of_time=True,
            seconds=150,
            overlap=schemas.FeedOverlap(own=0, shared=1, listed_with={"news": 1}, filed_under={}),
        )
    ]


def test_a_feeds_outcome_stored_before_overlap_was_counted_still_reads() -> None:
    stored = scrape.ScrapeResult(1, 1, 0, 0, feeds=[scrape.FeedOutcome("news", items=1)]).to_json()
    assert isinstance(stored["feeds"], list)
    for feed in stored["feeds"]:
        assert isinstance(feed, dict)
        del feed["overlap"]  # as runs stored it before

    result = typed_result(JobName.SCRAPE, stored)

    assert result
    assert [(feed.feed, feed.overlap) for feed in result.feeds] == [("news", None)]


def test_progress_reads_as_the_scraper_reports_it() -> None:
    news, wire = scrape.FeedOutcome("news", items=1, new=1), scrape.FeedOutcome("wire", items=4)
    wire.unread = 1
    result = scrape.ScrapeResult(feeds_read=2, versions_new=1, feeds=[news, wire])
    reading = scrape.Underway(wire, listed=True)

    progress = typed_progress(JobName.SCRAPE, result.progress(3, reading))

    assert progress
    assert (progress.feeds_total, progress.feeds_done) == (3, 1)
    assert progress.current == schemas.FeedUnderway(feed="wire", items=4, done=3, new=0)
    assert progress.latest
    assert (progress.latest.feed, progress.latest.new) == ("news", 1)
    assert typed_progress(JobName.SCRAPE, scrape.ScrapeResult().progress(3)) == (
        schemas.SourceCollectionProgress(
            feeds_total=3, feeds_done=0, versions_new=0, current=None, latest=None
        )
    )
    assert typed_progress("extract", result.progress(3)) is None  # another job reports its own


def test_a_feed_still_listing_has_no_items_yet() -> None:
    news = scrape.FeedOutcome("news")
    reported = scrape.ScrapeResult(feeds_read=1, feeds=[news]).progress(2, scrape.Underway(news))

    progress = typed_progress(JobName.SCRAPE, reported)

    assert progress
    assert (progress.feeds_done, progress.latest) == (0, None)
    assert progress.current == schemas.FeedUnderway(feed="news", items=None, done=0, new=0)


@pytest.mark.parametrize(
    ("job", "stored"),
    [
        (JobName.SCRAPE, None),  # still running
        (JobName.SCRAPE, {"feeds": 3}),  # an older shape
        (JobName.SCRAPE, "done"),
        ("extract", {"claims": 3}),  # another job's result has no type yet
    ],
)
def test_other_results_show_none(job: str, stored: JSONValue) -> None:
    assert typed_result(job, stored) is None
