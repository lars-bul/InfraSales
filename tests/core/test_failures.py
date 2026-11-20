from infrasales.core.failures import ExpectedError
from infrasales.extract.extractor import ExtractionError
from infrasales.feeds.kinds import NoListerError
from infrasales.feeds.lister import UnreadableFeedError
from infrasales.fetch.fetcher import BlockedError, FetchError
from infrasales.fetch.pacing import OutOfTimeError


def test_a_failure_without_its_own_reason_says_failed() -> None:
    assert ExpectedError("details stay in the message").reason == "failed"


def test_every_failure_the_scrape_records_is_one_with_a_fixed_reason() -> None:
    failures = [
        FetchError("x"),
        BlockedError("https://example.com/", 403),
        OutOfTimeError("example.com"),
        UnreadableFeedError("x"),
        NoListerError("x"),
        ExtractionError("encrypted PDF"),
    ]
    assert all(isinstance(failure, ExpectedError) for failure in failures)
    assert [failure.reason for failure in failures] == [
        "fetch failed",
        "blocked",
        "out of time",
        "unreadable",
        "no lister",
        "encrypted PDF",
    ]
