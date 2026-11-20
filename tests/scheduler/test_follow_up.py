"""Follow-up runs: a job queued when a run of another job succeeds (`ScheduledJob.then`)."""

from collections.abc import AsyncIterator

import pytest

from infrasales.config.schemas import ConfigKey
from infrasales.core.db import Database
from infrasales.scheduler import runs
from infrasales.scheduler.models import JobStatus, RunTrigger
from infrasales.scheduler.registry import ScheduledJob
from infrasales.scheduler.worker import Worker
from tests.scheduler.support import FAST, Clock, Recorder, stored_runs

pytestmark = pytest.mark.anyio


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    yield db
    await db.dispose()


def chained(scrape: Recorder, gate: Recorder) -> dict[str, ScheduledJob]:
    return {
        "scrape": ScheduledJob(run=scrape, schedule=ConfigKey.SCRAPE_SCHEDULE, then=("gate",)),
        "gate": ScheduledJob(run=gate),
    }


async def test_a_succeeded_run_queues_its_follow_up_which_then_runs(db: Database) -> None:
    scrape, gate, clock = Recorder(), Recorder(result={"gated": 2}), Clock()
    worker = Worker(db, chained(scrape, gate), FAST, clock)

    assert await worker.tick()  # the scheduled scrape
    queued = [r for r in await stored_runs(db) if r.job == "gate"]
    assert [(r.status, r.trigger, r.triggered_by) for r in queued] == [
        (JobStatus.PENDING, RunTrigger.FOLLOW_UP, None)
    ]

    assert await worker.tick()  # the gate
    assert len(gate.calls) == 1
    assert [r.status for r in await stored_runs(db) if r.job == "gate"] == [JobStatus.SUCCEEDED]


async def test_one_follow_up_waits_at_a_time(db: Database) -> None:
    async with db.session() as session:
        first, new = await runs.follow_up(session, "gate", Clock()())
    async with db.session() as session:
        again, again_new = await runs.follow_up(session, "gate", Clock()())

    assert new
    assert not again_new
    assert first is not None
    assert again is not None
    assert again.id == first.id
    assert len(await stored_runs(db)) == 1


async def test_a_waiting_follow_up_is_shown_as_under_way(db: Database) -> None:
    async with db.session() as session:
        queued, _ = await runs.follow_up(session, "gate", Clock()())
    async with db.session() as session:
        underway = await runs.active(session, "gate")

    assert queued is not None
    assert underway is not None
    assert underway.id == queued.id


async def test_the_jobs_under_way_are_those_running_or_queued_to_run(db: Database) -> None:
    clock = Clock()
    async with db.session() as session:
        await runs.follow_up(session, "gate", clock())
        await runs.enqueue(session, "scrape", clock(), triggered_by="basic:alice")
    async with db.session() as session:
        under_way = await runs.under_way(session)

    assert under_way == ["gate", "scrape"]


async def test_a_failed_run_queues_nothing(db: Database) -> None:
    scrape, gate = Recorder(error=RuntimeError("all Feeds failed")), Recorder()
    worker = Worker(db, chained(scrape, gate), FAST, Clock())

    assert await worker.tick()

    assert [r.job for r in await stored_runs(db)] == ["scrape"]


async def test_failing_to_queue_never_fails_the_finished_run(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_: object, **__: object) -> None:
        msg = "database gone"
        raise OSError(msg)

    monkeypatch.setattr(runs, "follow_up", broken)
    worker = Worker(db, chained(Recorder(), Recorder()), FAST, Clock())

    assert await worker.tick()

    assert [(r.job, r.status) for r in await stored_runs(db)] == [("scrape", JobStatus.SUCCEEDED)]
