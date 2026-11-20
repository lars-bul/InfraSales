import asyncio
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, cast

import httpx2
import pytest

from infrasales.app import create_app
from infrasales.core.db import Database
from infrasales.core.models import JSONValue, utcnow
from infrasales.jobs import scrape
from infrasales.observability import TELEMETRY
from infrasales.scheduler.models import JobRun, JobStatus, RunTrigger
from infrasales.scheduler.registry import ScheduledJob
from infrasales.scheduler.settings import SchedulerSettings
from infrasales.scheduler.worker import Worker
from infrasales.settings import Settings
from tests.helpers import SAME_ORIGIN, audit_actions, sign_in
from tests.scheduler.support import FAST, Clock, Recorder, stored_runs
from tests.scrape.support import disable_all_feeds

if TYPE_CHECKING:
    from infrasales.core.telemetry import Telemetry

pytestmark = pytest.mark.anyio


async def test_admins_queue_a_run_and_it_is_audited(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await sign_in(client, "alice")

    response = await client.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)

    assert response.status_code == 202
    run = response.json()
    assert (run["job"], run["trigger"], run["status"], run["attempts"]) == (
        "scrape",
        "manual",
        "pending",
        0,
    )
    assert (await audit_actions(database_url))[-1] == ("basic:alice", "job.triggered", "success")
    assert run["langfuse_url"] is None  # the app does not trace to Langfuse


async def test_a_double_click_queues_one_run(client: httpx2.AsyncClient, database_url: str) -> None:
    await sign_in(client, "alice")

    first = await client.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)
    second = await client.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)

    assert first.json()["id"] == second.json()["id"]
    triggered = [a for a in await audit_actions(database_url) if a[1] == "job.triggered"]
    assert len(triggered) == 1


async def test_a_request_sent_again_gets_its_run_even_once_it_finished(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    """A lost answer, asked for again after the run finished: the same run, no second one.

    Its key identifies the click: no new run is queued, so nothing runs twice.
    """
    await sign_in(client, "alice")
    click = SAME_ORIGIN | {"idempotency-key": str(uuid.uuid4())}
    queued = (await client.post("/api/jobs/scrape/runs", headers=click)).json()
    db = Database(database_url)
    assert await Worker(db, {"scrape": ScheduledJob(run=Recorder())}, FAST, Clock()).tick()

    again = await client.post("/api/jobs/scrape/runs", headers=click)
    next_click = SAME_ORIGIN | {"idempotency-key": str(uuid.uuid4())}
    another = await client.post("/api/jobs/scrape/runs", headers=next_click)

    assert again.status_code == 202
    assert (again.json()["id"], again.json()["status"]) == (queued["id"], "succeeded")
    assert another.json()["id"] != queued["id"]  # a new click: a new run
    assert len(await stored_runs(db)) == 2
    triggered = [a for a in await audit_actions(database_url) if a[1] == "job.triggered"]
    assert len(triggered) == 2  # the repeated request queued nothing
    await db.dispose()


async def test_an_idempotency_key_is_a_uuid(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "alice")

    response = await client.post(
        "/api/jobs/scrape/runs", headers=SAME_ORIGIN | {"idempotency-key": "click-1"}
    )

    assert response.status_code == 422


async def test_admins_follow_a_runs_progress(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "alice")
    run = (await client.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)).json()

    progress = await client.get(f"/api/jobs/scrape/runs/{run['id']}")
    unknown = await client.get(f"/api/jobs/scrape/runs/{uuid.uuid4()}")

    assert progress.json() | {"scheduled_for": None} == run | {"scheduled_for": None}
    assert (progress.json()["finished_at"], progress.json()["error"]) == (None, None)
    assert unknown.status_code == 404


async def test_viewers_cannot_follow_runs(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "vera")

    response = await client.get(f"/api/jobs/scrape/runs/{uuid.uuid4()}")

    assert response.status_code == 403


@pytest.mark.parametrize(("user", "status"), [(None, 401), ("vera", 403)])
async def test_only_admins_trigger_runs(
    client: httpx2.AsyncClient, user: str | None, status: int
) -> None:
    if user:
        await sign_in(client, user)

    assert (await client.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)).status_code == status


async def test_unknown_jobs_are_rejected(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "alice")

    assert (await client.post("/api/jobs/backup/runs", headers=SAME_ORIGIN)).status_code == 422


async def test_the_in_process_worker_runs_a_triggered_job_at_once(
    settings: Settings, database_url: str
) -> None:
    idle_for_an_hour = SchedulerSettings(poll_seconds=3600)
    app = create_app(settings.model_copy(update={"scheduler": idle_for_an_hour}))
    transport = httpx2.ASGITransport(app=app)
    db = Database(database_url)
    await disable_all_feeds(db)  # the app scrapes for real: no Feed to read

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        await sign_in(client, "alice")
        await client.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)
        async with asyncio.timeout(5):
            while not [r for r in await stored_runs(db) if r.status is JobStatus.SUCCEEDED]:  # noqa: ASYNC110  # the database is all there is to watch
                await asyncio.sleep(0.02)

    (run,) = [run for run in await stored_runs(db) if run.job == "scrape"]
    await db.dispose()
    assert run.trigger == RunTrigger.MANUAL
    assert isinstance(run.result, dict)
    assert run.result["feeds_read"] == 0  # the scrape job ran
    assert run.triggered_by == "basic:alice"


class Links:
    """The app's telemetry as far as links go: Langfuse on, its project known."""

    def session_url(self, session_id: str) -> str:
        return f"https://langfuse.test/project/p1/sessions/{session_id}"


async def test_a_followed_run_links_to_its_langfuse_session(settings: Settings) -> None:
    app = create_app(settings)
    TELEMETRY.set(app, cast("Telemetry", Links()))
    transport = httpx2.ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        await sign_in(client, "alice")
        queued = (await client.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)).json()
        progress = (await client.get(f"/api/jobs/scrape/runs/{queued['id']}")).json()
        active = (await client.get("/api/jobs/scrape/runs/active")).json()

    session = f"https://langfuse.test/project/p1/sessions/{queued['id']}"
    assert [run["langfuse_url"] for run in (queued, progress, active)] == [session] * 3


async def test_a_followed_run_tells_how_many_attempts_it_gets(settings: Settings) -> None:
    """Run now shows "Attempt 2 of 5": the limit is the scheduler's, as configured."""
    scheduler = SchedulerSettings(enabled=False, max_attempts=5)
    app = create_app(settings.model_copy(update={"scheduler": scheduler}))
    transport = httpx2.ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        await sign_in(client, "alice")
        queued = (await client.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)).json()
        progress = (await client.get(f"/api/jobs/scrape/runs/{queued['id']}")).json()
        active = (await client.get("/api/jobs/scrape/runs/active")).json()

    assert [run["max_attempts"] for run in (queued, progress, active)] == [5, 5, 5]


async def test_the_active_run_can_be_found_again(client: httpx2.AsyncClient) -> None:
    """After a reload, the UI finds the run it was following."""
    await sign_in(client, "alice")
    before = await client.get("/api/jobs/scrape/runs/active")
    queued = (await client.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)).json()

    after = await client.get("/api/jobs/scrape/runs/active")

    assert (before.status_code, before.json()) == (200, None)
    assert after.json()["id"] == queued["id"]


async def _report(database_url: str, run_id: str, progress: JSONValue) -> None:
    """The run running, with `progress` reported by its job."""
    db = Database(database_url)
    async with db.session() as session:
        run = await session.get_one(JobRun, uuid.UUID(run_id))
        run.status, run.progress = JobStatus.RUNNING, progress
    await db.dispose()


async def test_a_running_source_collection_tells_how_far_it_got(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await sign_in(client, "alice")
    queued = (await client.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)).json()
    heizwerk = scrape.FeedOutcome("heizwerk-journal-test", items=20, new=14, known=6, seconds=12.5)
    kommunal = scrape.FeedOutcome("netzbau-de", items=40, new=3, unread=28)
    done = [*(scrape.FeedOutcome(f"feed-{n}") for n in range(5)), heizwerk]
    result = scrape.ScrapeResult(feeds_read=7, versions_new=40, feeds=[*done, kommunal])
    reported = result.progress(23, scrape.Underway(kommunal, listed=True))
    await _report(database_url, queued["id"], reported)

    progress = (await client.get(f"/api/jobs/scrape/runs/{queued['id']}")).json()
    active = (await client.get("/api/jobs/scrape/runs/active")).json()

    assert queued["progress"] is None  # nothing reported yet
    assert progress["progress"] == active["progress"]
    assert progress["progress"] == {
        "feeds_total": 23,
        "feeds_done": 6,
        "versions_new": 40,
        "current": {"feed": "netzbau-de", "items": 40, "done": 12, "new": 3},  # "Feed 7 of 23"
        "latest": {
            "feed": "heizwerk-journal-test",
            "items": 20,
            "new": 14,
            "unchanged": 0,
            "known": 6,
            "seen": 0,
            "failed": 0,
            "unread": 0,
            "reason": None,
            "out_of_time": False,
            "seconds": 12.5,
            "overlap": {"own": 0, "shared": 0, "listed_with": {}, "filed_under": {}},
            "walled": [],
        },
    }


async def test_progress_in_a_shape_this_version_cannot_read_is_left_out(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await sign_in(client, "alice")
    queued = (await client.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)).json()
    await _report(database_url, queued["id"], {"feed": 7})

    response = await client.get(f"/api/jobs/scrape/runs/{queued['id']}")

    assert (response.status_code, response.json()["progress"]) == (200, None)


async def test_admins_browse_a_jobs_recent_runs(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    db = Database(database_url)
    async with db.session() as session:
        for minutes in (30, 20, 10):  # three runs, the newest last
            at = utcnow() - timedelta(minutes=minutes)
            session.add(JobRun(job="scrape", scheduled_for=at, run_after=at, created_at=at))
        session.add(JobRun(job="retired", scheduled_for=utcnow(), run_after=utcnow()))  # another
    await db.dispose()
    await sign_in(client, "alice")

    two = (await client.get("/api/jobs/scrape/runs", params={"limit": 2})).json()
    everything = (await client.get("/api/jobs/scrape/runs")).json()

    older = await client.get(
        "/api/jobs/scrape/runs", params={"before": two[-1]["id"], "status": "pending"}
    )

    assert [run["job"] for run in everything] == ["scrape"] * 3
    assert two == everything[:2]  # newest first
    assert everything[0]["scheduled_for"] > everything[1]["scheduled_for"]
    assert older.json() == everything[2:]  # the page after, of pending runs


async def test_admins_browse_every_jobs_runs_by_job_status_and_trigger(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    db = Database(database_url)
    async with db.session() as session:
        for minutes, job in ((30, "scrape"), (20, "retired"), (10, "scrape")):
            at = utcnow() - timedelta(minutes=minutes)
            session.add(JobRun(job=job, scheduled_for=at, run_after=at, created_at=at))
    await db.dispose()
    await sign_in(client, "alice")
    await client.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)  # manual, the newest

    every = (await client.get("/api/jobs/runs")).json()
    scrape = (await client.get("/api/jobs/runs", params={"job": "scrape"})).json()
    manual = (await client.get("/api/jobs/runs", params={"trigger": "manual"})).json()
    older = await client.get(
        "/api/jobs/runs", params={"before": every[1]["id"], "status": "pending", "limit": 1}
    )

    assert [run["job"] for run in every] == ["scrape", "scrape", "retired", "scrape"]
    assert [run["id"] for run in scrape] == [every[0]["id"], every[1]["id"], every[3]["id"]]
    assert [(run["job"], run["triggered_by"]) for run in manual] == [("scrape", "basic:alice")]
    assert older.json() == every[2:3]  # the page after, of pending runs


async def test_admins_browse_the_runs_scheduled_in_a_time_range(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    now = utcnow()
    db = Database(database_url)
    async with db.session() as session:
        for hours in (30, 20, 10):
            at = now - timedelta(hours=hours)
            session.add(JobRun(job="scrape", scheduled_for=at, run_after=at, created_at=at))
    await db.dispose()
    await sign_in(client, "alice")
    start, end = (now - timedelta(hours=20)).isoformat(), (now - timedelta(hours=10)).isoformat()

    between = (await client.get("/api/jobs/runs", params={"start": start, "end": end})).json()
    since = (await client.get("/api/jobs/scrape/runs", params={"start": start})).json()
    until = (await client.get("/api/jobs/runs", params={"end": end})).json()

    assert _hours_ago(now, between) == [20]  # from the start, until (not at) the end
    assert _hours_ago(now, since) == [10, 20]
    assert _hours_ago(now, until) == [20, 30]


def _hours_ago(now: datetime, runs: list[dict[str, str]]) -> list[int]:
    """How many hours before `now` each run was scheduled."""
    return [
        round((now - datetime.fromisoformat(run["scheduled_for"])) / timedelta(hours=1))
        for run in runs
    ]


@pytest.mark.parametrize(
    ("user", "params", "status"),
    [
        ("vera", {}, 403),
        ("alice", {"limit": 51}, 422),
        ("alice", {"job": "weather"}, 422),
        ("alice", {"start": "2026-10-17T10:00:00Z", "end": "2026-10-17T10:00:00Z"}, 422),
        ("alice", {"start": "2026-10-17T10:00:00"}, 422),  # no time zone: whose 10 o'clock?
    ],
)
async def test_every_jobs_runs_are_for_admins_and_known_jobs(
    client: httpx2.AsyncClient, user: str, params: dict[str, str | int], status: int
) -> None:
    await sign_in(client, user)

    response = await client.get("/api/jobs/runs", params=params)

    assert response.status_code == status


@pytest.mark.parametrize(("user", "limit", "status"), [("vera", 20, 403), ("alice", 51, 422)])
async def test_run_history_is_for_admins_and_bounded(
    client: httpx2.AsyncClient, user: str, limit: int, status: int
) -> None:
    await sign_in(client, user)

    response = await client.get("/api/jobs/scrape/runs", params={"limit": limit})

    assert response.status_code == status
