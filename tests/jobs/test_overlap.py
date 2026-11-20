"""Feed overlap: which Feeds list the same documents, summed over recent Source Collection runs."""

from datetime import timedelta

import httpx2
import pytest

from infrasales.core.db import Database
from infrasales.core.models import JSONValue, utcnow
from infrasales.jobs.scrape import FeedOutcome, FeedOverlap, ScrapeResult
from infrasales.scheduler.models import JobRun, JobStatus
from tests.helpers import sign_in

pytestmark = pytest.mark.anyio


def read(slug: str, own: int = 0, shared: int = 0, **others: dict[str, int]) -> FeedOutcome:
    """A Feed's outcome in a run, with its overlap: `listed_with`, `filed_under` by slug."""
    outcome = FeedOutcome(slug, items=own + shared)
    outcome.overlap = FeedOverlap(own, shared, **others)
    return outcome


def result(*feeds: FeedOutcome) -> JSONValue:
    return ScrapeResult(feeds_read=len(feeds), feeds=list(feeds)).to_json()


async def stored(database_url: str, *runs: tuple[str, JobStatus, JSONValue, timedelta]) -> None:
    """Runs of these jobs, statuses and results, each finished this long ago."""
    db = Database(database_url)
    async with db.session() as session:
        for minute, (job, status, stored_result, ago) in enumerate(runs):
            at = utcnow() - ago - timedelta(minutes=minute)
            session.add(
                JobRun(
                    job=job,
                    status=status,
                    result=stored_result,
                    scheduled_for=at,
                    run_after=at,
                    finished_at=None if status is JobStatus.RUNNING else at,
                )
            )
    await db.dispose()


def without_overlap(stored_result: JSONValue) -> JSONValue:
    """`stored_result` as runs stored it before overlap was counted."""
    assert isinstance(stored_result, dict)
    feeds = stored_result["feeds"]
    assert isinstance(feeds, list)
    for feed in feeds:
        assert isinstance(feed, dict)
        del feed["overlap"]
    return stored_result


HOUR, DAY = timedelta(hours=1), timedelta(days=1)


async def test_an_admin_sees_each_feeds_own_share_and_the_pairs_that_overlap_most(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await stored(
        database_url,
        (
            "scrape",
            JobStatus.SUCCEEDED,
            result(
                read("news", 8, 2, listed_with={"wire": 2}),
                read("wire", 3, 2, listed_with={"news": 2}),
                read("gone"),  # failed: it listed nothing
            ),
            HOUR,
        ),
        (
            "scrape",
            JobStatus.SUCCEEDED,
            result(
                read("news", 8, 2, listed_with={"wire": 1}, filed_under={"archive": 1}),
                read("wire", 4, 1, listed_with={"news": 1}),
            ),
            2 * DAY,
        ),
    )
    await sign_in(client, "alice")

    answer = await client.get("/api/feeds/overlap")

    assert answer.status_code == 200
    assert answer.json() == {
        "days": 14,
        "runs": 2,
        "feeds": [  # the least own share first
            {"feed": "wire", "runs": 2, "own": 7, "shared": 3, "own_share": 0.7},
            {"feed": "news", "runs": 2, "own": 16, "shared": 4, "own_share": 0.8},
            {"feed": "gone", "runs": 1, "own": 0, "shared": 0, "own_share": None},
        ],
        "pairs": [  # listed by both in a run: counted once, not by each of them
            {"feed": "news", "other": "wire", "listings": 3},
            {"feed": "archive", "other": "news", "listings": 1},
        ],
    }


async def test_only_finished_source_collection_runs_in_the_window_with_overlap_count(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    counted = result(
        read("news", 1, 1, listed_with={"wire": 1}), read("wire", 0, 1, listed_with={"news": 1})
    )
    await stored(
        database_url,
        ("scrape", JobStatus.SUCCEEDED, counted, HOUR),
        ("scrape", JobStatus.SUCCEEDED, counted, 20 * DAY),  # before the window
        ("scrape", JobStatus.SUCCEEDED, without_overlap(result(read("news", 5))), HOUR),
        ("scrape", JobStatus.SUCCEEDED, {"feeds_read": 3, "versions_new": 1}, HOUR),  # older
        ("scrape", JobStatus.SUCCEEDED, None, HOUR),
        ("scrape", JobStatus.RUNNING, None, HOUR),
        ("scrape", JobStatus.FAILED, None, HOUR),
        ("retired", JobStatus.SUCCEEDED, "Hello world", HOUR),
    )
    await sign_in(client, "alice")

    recent = (await client.get("/api/feeds/overlap")).json()
    month = (await client.get("/api/feeds/overlap", params={"days": 30})).json()

    assert (recent["days"], recent["runs"], month["runs"]) == (14, 1, 2)
    assert [(f["feed"], f["own"], f["shared"]) for f in recent["feeds"]] == [
        ("wire", 0, 1),
        ("news", 1, 1),
    ]
    assert recent["pairs"] == [{"feed": "news", "other": "wire", "listings": 1}]


async def test_no_run_yet_is_an_empty_report(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "alice")

    answer = await client.get("/api/feeds/overlap", params={"days": 7})

    assert answer.json() == {"days": 7, "runs": 0, "feeds": [], "pairs": []}


@pytest.mark.parametrize("days", [0, 91])
async def test_the_window_is_a_day_to_ninety(client: httpx2.AsyncClient, days: int) -> None:
    await sign_in(client, "alice")

    answer = await client.get("/api/feeds/overlap", params={"days": days})

    assert answer.status_code == 422


@pytest.mark.parametrize(("user", "status"), [(None, 401), ("vera", 403)])
async def test_only_admins_see_the_overlap(
    client: httpx2.AsyncClient, user: str | None, status: int
) -> None:
    if user:
        await sign_in(client, user)

    answer = await client.get("/api/feeds/overlap")

    assert answer.status_code == status
