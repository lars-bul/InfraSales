import asyncio
import uuid
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from datetime import UTC, datetime, time, timedelta
from functools import partial
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import ColumnElement, TextClause, and_
from sqlalchemy.orm.attributes import instance_state
from sqlmodel import SQLModel, col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.config.models import ConfigEntry
from infrasales.config.schemas import ConfigKey
from infrasales.core.db import Database
from infrasales.core.models import JSONValue
from infrasales.scheduler import runs
from infrasales.scheduler.models import JobRun, JobStatus, RunTrigger
from infrasales.scheduler.registry import ScheduledJob
from infrasales.scheduler.schemas import RunQuery
from tests.helpers import fill, postgres_only, query_plan
from tests.scheduler.support import Clock, Recorder, scheduled, stored_runs

pytestmark = pytest.mark.anyio
LEASE = timedelta(minutes=1)


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    yield db
    await db.dispose()


async def _claim(db: Database, owner: str, now: datetime, attempts: int = 3) -> JobRun | None:
    return await runs.claim(db, ["scrape"], owner, now=now, lease=LEASE, attempts=attempts)


async def _due_run(db: Database, clock: Clock) -> JobRun:
    await runs.plan(db, scheduled(Recorder()), clock())
    (run,) = await stored_runs(db)
    return run


async def test_planning_records_each_occurrence_once(db: Database) -> None:
    clock = Clock()

    await runs.plan(db, scheduled(Recorder()), clock())
    await runs.plan(db, scheduled(Recorder()), clock())

    (run,) = await stored_runs(db)
    assert (run.job, run.status, run.attempts) == ("scrape", JobStatus.PENDING, 0)
    assert run.scheduled_for == run.run_after <= clock()
    assert run.result is None


async def test_the_default_scrape_schedule_plans_a_run_every_3_hours(db: Database) -> None:
    """Feeds forget within a day, so the seeded scrape schedule repeats through the day."""
    midday = datetime.combine(Clock()().date(), time(12, 15), tzinfo=UTC)  # no DST change near
    clock = Clock(midday)

    await runs.plan(db, scheduled(Recorder()), clock())
    clock.advance(hours=3)
    await runs.plan(db, scheduled(Recorder()), clock())

    first, second = await stored_runs(db)
    assert second.scheduled_for - first.scheduled_for == timedelta(hours=3)
    local = first.scheduled_for.astimezone(ZoneInfo("Europe/Berlin"))
    assert (local.hour % 3, local.minute) == (0, 0)  # 00:00, 03:00, ... in Berlin


async def _edit_schedule(
    db: Database, key: str, updated_at: datetime | None = None, **changes: JSONValue
) -> None:
    """Change a schedule row directly (the service would also audit the change)."""
    async with db.session() as session:
        row = (await session.exec(select(ConfigEntry).where(col(ConfigEntry.key) == key))).one()
        row.value = row.value | changes
        if updated_at:
            row.updated_at = updated_at


async def test_planning_skips_unscheduled_disabled_and_missing_schedules(db: Database) -> None:
    registry = {
        "scrape": ScheduledJob(run=Recorder(), schedule=ConfigKey.SCRAPE_SCHEDULE),
        "manual": ScheduledJob(run=Recorder()),
    }
    await _edit_schedule(db, "scrape_schedule", enabled=False)

    await runs.plan(db, registry, Clock()())  # disabled
    async with db.session() as session:
        await session.exec(delete(ConfigEntry).where(col(ConfigEntry.key) == "scrape_schedule"))
    await runs.plan(db, registry, Clock()())  # missing

    assert await stored_runs(db) == []


async def test_a_schedule_change_never_fires_the_current_occurrence(db: Database) -> None:
    clock = Clock()
    await _edit_schedule(db, "scrape_schedule", updated_at=clock())  # after today's occurrence

    await runs.plan(db, scheduled(Recorder()), clock())

    assert await stored_runs(db) == []


async def test_a_due_run_is_leased_to_exactly_one_worker(db: Database) -> None:
    clock = Clock()
    await _due_run(db, clock)

    claims = await asyncio.gather(*(_claim(db, f"worker-{n}", clock()) for n in range(3)))

    (run,) = [claim for claim in claims if claim]
    assert (run.status, run.attempts) == (JobStatus.RUNNING, 1)
    assert run.lease_expires_at == clock() + LEASE
    assert await _claim(db, "late", clock()) is None


JOBS = [f"job-{n}" for n in range(5)]


async def test_concurrent_claims_each_get_a_different_run(db: Database) -> None:
    """Workers sharing a backlog never wait for each other's run (SKIP LOCKED on PostgreSQL)."""
    clock = Clock()
    async with db.session() as session:
        session.add_all(JobRun(job=job, scheduled_for=clock(), run_after=clock()) for job in JOBS)

    claims = await asyncio.gather(
        *(runs.claim(db, JOBS, f"w{n}", now=clock(), lease=LEASE, attempts=3) for n in range(5))
    )

    assert len({claim.id for claim in claims if claim}) == 5


async def test_one_run_of_a_job_executes_at_a_time(db: Database) -> None:
    """A manual and a scheduled run, or a backlog: run one after another, never side by side.

    On PostgreSQL concurrent claims race: the database's index lets one through.
    """
    clock = Clock()
    due = [clock() - timedelta(minutes=n) for n in range(5)]
    async with db.session() as session:
        session.add_all(JobRun(job="scrape", scheduled_for=at, run_after=at) for at in due)

    claims = await asyncio.gather(*(_claim(db, f"worker-{n}", clock()) for n in range(5)))
    (running,) = [claim for claim in claims if claim]
    later = await _claim(db, "late", clock())  # still running: the others wait
    await runs.succeed(db, running, running.lease_owner or "", clock(), None)
    after = await _claim(db, "next", clock())  # finished: the next one starts

    assert later is None
    assert after
    assert after.id != running.id


@postgres_only
async def test_claiming_uses_the_queue_indexes_however_long_the_history(db: Database) -> None:
    await fill(  # a long history: 100,000 finished runs
        db,
        "INSERT INTO job_run (id, created_at, updated_at, job, scheduled_for, status, attempts,"
        " run_after, finished_at, trigger)"
        " SELECT gen_random_uuid(), now(), now(), 'scrape', now() - g * interval '1 min',"
        " 'succeeded', 1, now() - g * interval '1 min', now(), 'schedule'"
        " FROM generate_series(1, 100000) AS g",
    )

    plan = await query_plan(db, lambda: _claim(db, "w", Clock()()), "UPDATE job_run")

    assert "Seq Scan on job_run" not in plan, plan


async def test_a_jobs_history_reads_newest_first_with_what_each_run_did(db: Database) -> None:
    """A page at a time, the run history shows each run's result: it is read for it."""
    clock = Clock()
    due = [clock() - timedelta(days=days) for days in range(3)]
    async with db.session() as session:
        for at in due:  # created in this order
            session.add(JobRun(job="scrape", scheduled_for=at, run_after=at, result=["x" * 1000]))
            session.add(JobRun(job="report", scheduled_for=at, run_after=at))

    async with db.session() as session:
        history = await runs.recent(session, "scrape", RunQuery(limit=2))

        assert [(run.job, run.scheduled_for) for run in history] == [
            ("scrape", due[2]),
            ("scrape", due[1]),
        ]
        assert [run.result for run in history] == [["x" * 1000]] * 2


async def test_a_runs_progress_reads_what_it_shows(db: Database) -> None:
    """Polled every few seconds: the run's result, possibly large, is never read for it."""
    clock = Clock()
    manual = JobRun(
        job="scrape",
        scheduled_for=clock(),
        run_after=clock(),
        trigger=RunTrigger.MANUAL,
        result=["x" * 1000],
        progress={"feeds_read": 7},
    )
    async with db.session() as session:
        session.add(manual)

    async with db.session() as session:
        found = await runs.find(session, "scrape", manual.id)
    async with db.session() as session:
        in_progress = await runs.active(session, "scrape")

    assert found
    assert in_progress
    assert found.id == in_progress.id == manual.id
    assert all("result" in instance_state(run).unloaded for run in (found, in_progress))
    assert found.progress == in_progress.progress == {"feeds_read": 7}  # how far it got: shown


async def test_the_run_under_way_is_found_scheduled_or_manual(db: Database) -> None:
    """The job's page follows a scheduled run too, not only one an admin started."""
    clock = Clock()

    def run(minutes: int, status: JobStatus, trigger: RunTrigger, attempts: int = 0) -> JobRun:
        at = clock() + timedelta(minutes=minutes)
        return JobRun(
            job="scrape",
            scheduled_for=at,
            run_after=at,
            status=status,
            trigger=trigger,
            attempts=attempts,
        )

    next_run = run(180, JobStatus.PENDING, RunTrigger.SCHEDULE)  # planned: not under way
    retrying = run(-180, JobStatus.PENDING, RunTrigger.SCHEDULE, attempts=1)
    running = run(0, JobStatus.RUNNING, RunTrigger.SCHEDULE, attempts=1)
    queued = run(1, JobStatus.PENDING, RunTrigger.MANUAL)

    async def under_way(*added: JobRun) -> uuid.UUID | None:
        async with db.session() as session:
            session.add_all(added)
        async with db.session() as session:
            found = await runs.active(session, "scrape")
        return None if found is None else found.id

    assert await under_way(next_run) is None
    assert await under_way(retrying) == retrying.id
    async with db.session() as session:  # one run at a time: the retried one is done
        (await session.get_one(JobRun, retrying.id)).status = JobStatus.SUCCEEDED
    assert await under_way(running, queued) == running.id  # it runs: first


@postgres_only
async def test_a_jobs_history_is_read_from_its_index_however_long(db: Database) -> None:
    await fill(  # a long history: 100,000 finished runs of two jobs
        db,
        "INSERT INTO job_run (id, created_at, updated_at, job, scheduled_for, status, attempts,"
        " run_after, finished_at, trigger)"
        " SELECT gen_random_uuid(), now() - g * interval '1 min', now(),"
        " CASE WHEN g % 2 = 0 THEN 'scrape' ELSE 'report' END, now() - g * interval '1 min',"
        " 'succeeded', 1, now() - g * interval '1 min', now(), 'schedule'"
        " FROM generate_series(1, 100000) AS g",
    )

    async with db.session() as session:
        (newest,) = await runs.recent(session, "scrape", RunQuery(limit=1))

    async def page(before: uuid.UUID | None) -> None:
        async with db.session() as session:
            await runs.recent(session, "scrape", RunQuery(before=before))

    plans = [
        await query_plan(db, partial(page, before), "SELECT job_run.id")
        for before in (None, newest.id)  # the newest page, and one further back
    ]

    for plan in plans:
        assert "Seq Scan" not in plan, plan
        assert "Sort" not in plan, plan  # read in order: 20 rows, not the whole history


async def test_a_jobs_history_pages_back_and_filters(db: Database) -> None:
    clock = Clock()
    async with db.session() as session:  # created in this order: IDs are time-ordered
        for n, status in enumerate([JobStatus.FAILED, JobStatus.SUCCEEDED, JobStatus.FAILED]):
            at = clock() + timedelta(minutes=n)
            session.add(JobRun(job="scrape", scheduled_for=at, run_after=at, status=status))

    async with db.session() as session:
        newest, middle, oldest = await runs.recent(session, "scrape", RunQuery())
        back = await runs.recent(session, "scrape", RunQuery(before=newest.id, limit=1))
        failed = await runs.recent(session, "scrape", RunQuery(status=JobStatus.FAILED))

    assert [run.id for run in back] == [middle.id]
    assert [run.id for run in failed] == [newest.id, oldest.id]


async def test_every_jobs_history_reads_newest_first_and_filters_by_trigger(db: Database) -> None:
    clock = Clock()
    async with db.session() as session:  # created in this order: IDs are time-ordered
        for n, (job, trigger) in enumerate(
            [("scrape", RunTrigger.SCHEDULE), ("report", RunTrigger.MANUAL)]
        ):
            at = clock() + timedelta(minutes=n)
            session.add(JobRun(job=job, scheduled_for=at, run_after=at, trigger=trigger))

    async with db.session() as session:
        every = await runs.recent(session, None, RunQuery())
        manual = await runs.recent(session, None, RunQuery(trigger=RunTrigger.MANUAL))

    assert [run.job for run in every] == ["report", "scrape"]
    assert [run.job for run in manual] == ["report"]


async def test_the_backlog_counts_due_runs_and_the_oldest_wait(db: Database) -> None:
    clock = Clock()
    assert await runs.backlog(db, ["scrape"], clock(), 3) == (0, 0.0)
    async with db.session() as session:
        for minutes in (1.5, 0.5, -1):  # two due, one not yet
            at = clock() - timedelta(minutes=minutes)
            session.add(JobRun(job="scrape", scheduled_for=at, run_after=at))

    assert await runs.backlog(db, ["scrape"], clock(), 3) == (2, 90.0)


async def test_the_backlog_counts_runs_waiting_for_their_jobs_running_one(db: Database) -> None:
    """Not claimable while their job runs, yet waiting: a job slower than its schedule shows."""
    clock = Clock()
    for minutes in (2, 1):
        at = clock() - timedelta(minutes=minutes)
        async with db.session() as session:
            session.add(JobRun(job="scrape", scheduled_for=at, run_after=at))
    assert await _claim(db, "w", clock())  # the older one runs; the newer one waits for it

    assert await _claim(db, "other", clock()) is None
    assert await runs.backlog(db, ["scrape"], clock(), 3) == (1, 60.0)


async def test_runs_wait_for_their_time_and_unknown_jobs_are_left_alone(db: Database) -> None:
    clock = Clock()
    run = await _due_run(db, clock)

    assert await _claim(db, "w", run.run_after - timedelta(seconds=1)) is None
    assert await runs.claim(db, ["other"], "w", now=clock(), lease=LEASE, attempts=3) is None


async def test_a_dead_workers_run_is_taken_over_after_its_lease(db: Database) -> None:
    clock = Clock()
    await _due_run(db, clock)
    crashed = await _claim(db, "crashed", clock())
    assert crashed

    assert await _claim(db, "other", clock() + LEASE / 2) is None
    taken = await _claim(db, "other", clock() + LEASE * 2)

    assert taken
    assert (taken.lease_owner, taken.attempts) == ("other", 2)
    assert not await runs.heartbeat(db, crashed, "crashed", clock() + LEASE)  # lease lost


async def test_a_dead_workers_last_attempt_is_reaped(db: Database) -> None:
    clock = Clock()
    await _due_run(db, clock)
    assert await _claim(db, "crashed", clock(), attempts=1)

    reaped = await runs.reap(db, clock() + LEASE * 2, 1)

    (run,) = await stored_runs(db)
    assert (run.status, run.error, run.lease_owner) == (JobStatus.FAILED, "LeaseExpired", None)
    assert [(r.id, r.status) for r in reaped] == [(run.id, JobStatus.FAILED)]  # to report


async def test_a_pending_run_a_lowered_retry_limit_strands_is_failed(db: Database) -> None:
    """Retried once under three attempts, then deployed with one: failed, not stuck forever."""
    clock = Clock()
    async with db.session() as session:
        stranded, _ = await runs.enqueue(session, "scrape", clock(), triggered_by="basic:alice")
    claimed = await _claim(db, "w", clock())
    assert claimed
    await runs.fail(db, claimed, "w", clock(), error="TimeoutError", retry_at=clock())

    assert await _claim(db, "w", clock(), attempts=1) is None  # it can no longer run
    (reaped,) = await runs.reap(db, clock(), max_attempts=1)
    assert (reaped.id, reaped.error) == (stranded.id, "TimeoutError")
    reaped_at = clock()
    clock.advance(seconds=1)
    async with db.session() as session:
        fresh, queued = await runs.enqueue(session, "scrape", clock(), triggered_by="basic:alice")

    failed = next(run for run in await stored_runs(db) if run.id == stranded.id)
    assert (failed.status, failed.error, failed.finished_at) == (
        JobStatus.FAILED,
        "TimeoutError",  # its last error is kept
        reaped_at,
    )
    assert queued  # "Run now" queues a new run instead of returning the stuck one
    assert fresh.id != stranded.id


async def test_outcomes_are_recorded_only_by_the_lease_holder(db: Database) -> None:
    clock = Clock()
    await _due_run(db, clock)
    run = await _claim(db, "holder", clock())
    assert run

    assert not await runs.succeed(db, run, "intruder", clock(), "stolen")
    assert await runs.heartbeat(db, run, "holder", clock() + LEASE * 2)
    assert await runs.succeed(db, run, "holder", clock(), ["Hello", "world"])

    (stored,) = await stored_runs(db)
    assert (stored.status, stored.result) == (JobStatus.SUCCEEDED, ["Hello", "world"])
    assert stored.finished_at == clock()


async def test_progress_is_kept_only_by_the_lease_holder_and_each_attempt_starts_without(
    db: Database,
) -> None:
    clock = Clock()
    await _due_run(db, clock)
    run = await _claim(db, "holder", clock())
    assert run

    assert await runs.note_progress(db, run, "holder", {"feeds_read": 1})
    assert not await runs.note_progress(db, run, "intruder", {"feeds_read": 99})
    (noted,) = await stored_runs(db)
    await runs.fail(db, run, "holder", clock(), error="ValueError", retry_at=clock())
    retried = await _claim(db, "holder", clock())

    assert noted.progress == {"feeds_read": 1}
    assert retried
    assert (retried.attempts, retried.progress) == (2, None)  # from the top again
    assert not await runs.note_progress(db, run, "holder", {"feeds_read": 2})  # the last attempt's


@pytest.mark.parametrize("outcome", ["retrying", "released", "failed"])
async def test_a_run_waiting_for_its_next_attempt_shows_no_progress(
    db: Database, outcome: str
) -> None:
    clock = Clock()
    await _due_run(db, clock)
    run = await _claim(db, "w", clock())
    assert run
    assert await runs.note_progress(db, run, "w", {"feeds_read": 1, "current": "news"})

    if outcome == "released":
        assert await runs.release(db, run, "w", clock())
    else:
        retry_at = clock() + LEASE if outcome == "retrying" else None
        assert await runs.fail(db, run, "w", clock(), error="ValueError", retry_at=retry_at)

    (stored,) = await stored_runs(db)
    # Failed for good, it keeps how far its last attempt got; pending, nothing is underway.
    kept = {"feeds_read": 1, "current": "news"} if outcome == "failed" else None
    assert stored.progress == kept


async def test_failures_are_retried_later_or_failed_for_good(db: Database) -> None:
    clock = Clock()
    await _due_run(db, clock)
    run = await _claim(db, "w", clock())
    assert run

    assert await runs.fail(db, run, "w", clock(), error="ValueError", retry_at=clock() + LEASE)
    (retrying,) = await stored_runs(db)
    run = await _claim(db, "w", clock() + LEASE)
    assert run
    assert await runs.fail(db, run, "w", clock(), error="ValueError", retry_at=None)

    (failed,) = await stored_runs(db)
    assert (retrying.status, retrying.run_after) == (JobStatus.PENDING, clock() + LEASE)
    assert (failed.status, failed.error, failed.attempts) == (JobStatus.FAILED, "ValueError", 2)


async def test_released_runs_are_due_at_once_without_using_an_attempt(db: Database) -> None:
    clock = Clock()
    await _due_run(db, clock)
    run = await _claim(db, "w", clock())
    assert run

    assert await runs.release(db, run, "w", clock())

    (released,) = await stored_runs(db)
    assert (released.status, released.attempts, released.lease_owner) == (
        JobStatus.PENDING,
        0,
        None,
    )


async def test_a_claim_that_loses_the_race_for_a_job_gets_nothing(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two claims saw the job idle at once: the database lets one run start, the other waits."""
    clock = Clock()
    due = [clock() - timedelta(minutes=n) for n in range(2)]
    async with db.session() as session:
        session.add_all(JobRun(job="scrape", scheduled_for=at, run_after=at) for at in due)
    assert await _claim(db, "first", clock())

    def racing(jobs: Iterable[str], now: datetime, _: int) -> ColumnElement[bool]:
        """What the second claim saw: its run due, the job not yet running."""
        due = and_(col(JobRun.status) == JobStatus.PENDING, col(JobRun.run_after) <= now)
        return and_(col(JobRun.job).in_(list(jobs)), due)

    monkeypatch.setattr(runs, "_claimable", racing)

    assert await _claim(db, "second", clock()) is None
    assert [run.status for run in await stored_runs(db)].count(JobStatus.RUNNING) == 1


async def test_a_manual_run_is_due_at_once_and_claimed_like_any_other(db: Database) -> None:
    clock = Clock()
    async with db.session() as session:
        queued, _ = await runs.enqueue(session, "scrape", clock(), triggered_by="basic:alice")

    claimed = await _claim(db, "w", clock())

    assert claimed
    assert (claimed.id, claimed.trigger) == (queued.id, RunTrigger.MANUAL)
    assert claimed.triggered_by == "basic:alice"


async def test_one_manual_run_per_job_at_a_time(db: Database) -> None:
    clock = Clock()

    async def run_now() -> tuple[JobRun, bool]:
        clock.advance(seconds=1)
        async with db.session() as session:
            return await runs.enqueue(session, "scrape", clock(), triggered_by="basic:alice")

    first, first_new = await run_now()
    waiting, waiting_new = await run_now()  # a double click
    claimed = await _claim(db, "w", clock())
    running, running_new = await run_now()  # a second admin, while it runs
    assert claimed
    await runs.succeed(db, claimed, "w", clock(), None)
    later, later_new = await run_now()  # finished: a new run

    assert (first_new, waiting_new, running_new, later_new) == (True, False, False, True)
    assert first.id == waiting.id == running.id != later.id


async def test_a_repeated_request_gets_the_run_it_was_answered_with(db: Database) -> None:
    """Its answer lost, a request is sent again with its key, perhaps after the run finished."""
    clock, alices, bobs = Clock(), uuid.uuid4(), uuid.uuid4()

    async def run_now(key: uuid.UUID, job: str = "scrape") -> tuple[JobRun, bool]:
        clock.advance(seconds=1)
        async with db.session() as session:
            return await runs.enqueue(session, job, clock(), triggered_by="basic:x", key=key)

    queued, _ = await run_now(alices)
    in_progress, _ = await run_now(bobs)  # Bob's click: answered with Alice's run
    claimed = await _claim(db, "w", clock())
    assert claimed
    await runs.succeed(db, claimed, "w", clock(), None)

    answers = [await run_now(alices), await run_now(bobs)]  # both again, after it finished
    other_job, other_job_new = await run_now(alices, "report")  # keys are per job

    assert queued.id == in_progress.id
    assert [(run.id, run.status, new) for run, new in answers] == [
        (queued.id, JobStatus.SUCCEEDED, False)
    ] * 2
    assert (other_job.id != queued.id, other_job_new) == (True, True)
    assert len(await stored_runs(db)) == 2


@postgres_only
async def test_a_request_racing_its_repeat_ends_on_the_same_run(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two requests with one key, the second queuing a run that finishes before the first ends.

    A looks its key up first; B queues a run, which finishes; then A goes on. A discards the
    run it allocates and gets B's: the key's owner answers both.
    """
    clock, key = Clock(), uuid.uuid4()
    looked_up, resume, insert = asyncio.Event(), asyncio.Event(), runs.insert_if_absent

    async def pausing_before_a_run(  # insert_if_absent, holding A back before its run
        session: AsyncSession,
        table: type[SQLModel],
        values: Mapping[str, object],
        unique: Sequence[str],
        where: TextClause | None = None,
    ) -> bool:
        if table is JobRun and not looked_up.is_set():  # A, its key looked up
            looked_up.set()
            await resume.wait()
        return await insert(session, table, values, unique, where)

    async def run_now() -> tuple[JobRun, bool]:
        clock.advance(seconds=1)  # each request at its own time
        async with db.session() as session:
            return await runs.enqueue(
                session, "scrape", clock(), triggered_by="basic:alice", key=key
            )

    monkeypatch.setattr(runs, "insert_if_absent", pausing_before_a_run)
    first = asyncio.create_task(run_now())
    async with asyncio.timeout(5):
        await looked_up.wait()
    second, second_new = await run_now()
    claimed = await _claim(db, "w", clock())
    assert claimed
    await runs.succeed(db, claimed, "w", clock(), None)
    resume.set()
    first_run, first_new = await first

    assert (second_new, first_new) == (True, False)
    assert first_run.id == second.id
    assert len(await stored_runs(db)) == 1


@pytest.mark.parametrize("key", [None, uuid.uuid4()], ids=["no key", "one key"])
async def test_concurrent_run_now_requests_share_one_run(
    db: Database, key: uuid.UUID | None
) -> None:
    """Two admins at once, or one request sent twice: the second gets the first's run.

    It waits for the first request's transaction, then conflicts with its run.
    """
    clock, inserted = Clock(), asyncio.Event()

    async def first_request() -> tuple[JobRun, bool]:
        async with db.session() as session:
            queued = await runs.enqueue(
                session, "scrape", clock(), triggered_by="basic:alice", key=key
            )
            inserted.set()
            await asyncio.sleep(0.2)  # not committed yet when the second request comes in
            return queued

    first = asyncio.create_task(first_request())
    async with asyncio.timeout(5):
        await inserted.wait()
    clock.advance(seconds=1)  # a moment later: another scheduled time, no help from that key
    async with db.session() as session:
        second, second_new = await runs.enqueue(
            session, "scrape", clock(), triggered_by="basic:bob", key=key
        )
    first_run, first_new = await first

    assert (first_new, second_new) == (True, False)
    assert second.id == first_run.id
    assert len(await stored_runs(db)) == 1


async def test_a_run_is_found_only_under_its_job(db: Database) -> None:
    clock = Clock()
    async with db.session() as session:
        run, _ = await runs.enqueue(session, "scrape", clock(), triggered_by="basic:alice")

        found = await runs.find(session, "scrape", run.id)
        other_job = await runs.find(session, "report", run.id)

    assert (found, other_job) == (run, None)
