"""The run list as the run history reads it: who started each run, what it did, its trace."""

from datetime import timedelta
from typing import TYPE_CHECKING, cast

import httpx2
import pytest

from infrasales.app import create_app
from infrasales.core.db import Database
from infrasales.core.models import JSONValue, utcnow
from infrasales.jobs.scrape import FailedFeed, FeedOutcome, ScrapeResult
from infrasales.observability import TELEMETRY
from infrasales.scheduler.models import JobRun, JobStatus
from infrasales.settings import Settings
from tests.helpers import SAME_ORIGIN, sign_in
from tests.jobs.test_router import Links

if TYPE_CHECKING:
    from infrasales.core.telemetry import Telemetry

pytestmark = pytest.mark.anyio


async def test_a_run_tells_who_started_it(client: httpx2.AsyncClient, database_url: str) -> None:
    db = Database(database_url)
    async with db.session() as session:
        session.add(JobRun(job="scrape", scheduled_for=utcnow(), run_after=utcnow()))
    await db.dispose()
    await sign_in(client, "alice")
    await client.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)

    manual, scheduled = (await client.get("/api/jobs/scrape/runs")).json()

    assert (manual["trigger"], manual["triggered_by"]) == ("manual", "basic:alice")
    assert (scheduled["trigger"], scheduled["triggered_by"]) == ("schedule", None)


async def test_a_run_links_to_its_langfuse_session_when_traced(
    client: httpx2.AsyncClient, settings: Settings
) -> None:
    await sign_in(client, "alice")
    await client.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)
    (untraced,) = (await client.get("/api/jobs/scrape/runs")).json()
    app = create_app(settings)
    TELEMETRY.set(app, cast("Telemetry", Links()))

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as traced_client,
    ):
        await sign_in(traced_client, "alice")
        (traced,) = (await traced_client.get("/api/jobs/scrape/runs")).json()

    assert untraced["langfuse_url"] is None  # the app does not trace to Langfuse
    assert traced["langfuse_url"] == f"https://langfuse.test/project/p1/sessions/{traced['id']}"


async def stored(database_url: str, job: str, *runs: tuple[JobStatus, JSONValue]) -> None:
    """Runs of `job` with these statuses and results, the last one newest (IDs are in order)."""
    db = Database(database_url)
    async with db.session() as session:
        for age, (status, result) in zip(range(len(runs), 0, -1), runs, strict=True):
            at = utcnow() - timedelta(minutes=age)
            session.add(
                JobRun(
                    job=job,
                    status=status,
                    result=result,
                    scheduled_for=at,
                    run_after=at,
                    finished_at=None if status is JobStatus.RUNNING else at,
                )
            )
    await db.dispose()


async def test_a_finished_source_collection_run_tells_what_it_did(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    blocked = FailedFeed("tiefbau-aktuell", "blocked")
    collected = ScrapeResult(4, 42, 7, 1, [blocked, FailedFeed("trassenbau-report", "http 404")])
    await stored(
        database_url,
        "scrape",
        (JobStatus.SUCCEEDED, collected.to_json()),
        (JobStatus.RUNNING, None),
    )
    await sign_in(client, "alice")

    running, finished = (await client.get("/api/jobs/scrape/runs")).json()

    assert running["result"] is None
    assert finished["result"] == {
        "feeds_read": 4,
        "versions_new": 42,
        "versions_unchanged": 7,
        "documents_failed": 1,
        "failed_feeds": [
            {"feed": "tiefbau-aktuell", "reason": "blocked"},
            {"feed": "trassenbau-report", "reason": "http 404"},
        ],
        "feeds": [],  # each Feed's outcome: none given here
    }


async def test_a_finished_source_collection_run_tells_what_each_feed_did(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    news = FeedOutcome("news", items=3, new=1, unchanged=1, seen=1, seconds=9)
    walled = FeedOutcome("walled", reason="blocked", seconds=0.5)
    collected = ScrapeResult(2, 1, 1, 0, [FailedFeed("walled", "blocked")], feeds=[news, walled])
    await stored(database_url, "scrape", (JobStatus.SUCCEEDED, collected.to_json()))
    await sign_in(client, "alice")

    (run,) = (await client.get("/api/jobs/scrape/runs")).json()

    assert [(f["feed"], f["new"], f["seen"], f["reason"]) for f in run["result"]["feeds"]] == [
        ("news", 1, 1, None),
        ("walled", 0, 0, "blocked"),
    ]
    assert run["result"]["feeds"][0]["seconds"] == 9


async def test_a_run_of_a_job_without_a_typed_result_shows_none(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    """A job removed since (an older release's) keeps its runs: their results are not shown."""
    await stored(database_url, "retired", (JobStatus.SUCCEEDED, "Hello world"))
    await sign_in(client, "alice")

    (run,) = (await client.get("/api/jobs/runs")).json()

    assert (run["job"], run["status"], run["result"]) == ("retired", "succeeded", None)


async def test_a_result_stored_in_an_older_shape_is_left_out(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    """A result this version cannot read shows no summary, and the history still loads."""
    await stored(database_url, "scrape", (JobStatus.SUCCEEDED, {"feeds": 3}))
    await sign_in(client, "alice")

    response = await client.get("/api/jobs/scrape/runs")

    assert response.status_code == 200
    assert response.json()[0]["result"] is None
