import asyncio
import contextlib
import io
import json
import signal
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, NoReturn, override

import pytest

from infrasales.config.schemas import ConfigKey
from infrasales.core.db import Database
from infrasales.core.logs import configure_logging
from infrasales.core.models import JSONValue
from infrasales.scheduler import runs, worker
from infrasales.scheduler.models import JobStatus
from infrasales.scheduler.registry import UNTRACED, JobContext, Notice, ScheduledJob
from infrasales.scheduler.settings import SchedulerSettings
from infrasales.scheduler.worker import Worker, serve
from tests.alerts.support import RecordingNotifier
from tests.scheduler.support import (
    FAST,
    Clock,
    RecordedTrace,
    Recorder,
    scheduled,
    stored_runs,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    yield db
    await db.dispose()


def _events(stream: io.StringIO) -> list[str]:
    return [json.loads(line)["event"] for line in stream.getvalue().splitlines()]


async def test_a_due_job_runs_once_and_its_result_is_kept(db: Database) -> None:
    job, clock = Recorder(result=["Hello", "world"]), Clock()
    scheduler = Worker(db, scheduled(job), FAST, clock)

    assert await scheduler.tick()
    assert not await scheduler.tick()  # the occurrence is done: nothing runs twice

    (run,) = await stored_runs(db)
    assert (run.status, run.result, run.attempts) == (JobStatus.SUCCEEDED, ["Hello", "world"], 1)
    (context,) = job.calls
    assert (context.run_id, context.scheduled_for) == (run.id, run.scheduled_for)


def _reporting(db: Database, seen: list[JSONValue]) -> dict[str, ScheduledJob]:
    """A job that reports how far it got, then notes what its run holds by then."""

    async def job(context: JobContext, /) -> JSONValue:
        await context.progress({"feeds_read": 1})
        seen.extend(run.progress for run in await stored_runs(db))
        return "done"

    return {"scrape": ScheduledJob(run=job, schedule=ConfigKey.SCRAPE_SCHEDULE)}


async def test_a_jobs_progress_is_kept_on_its_run_while_it_runs(db: Database) -> None:
    seen: list[JSONValue] = []
    scheduler = Worker(db, _reporting(db, seen), FAST, Clock())

    assert await scheduler.tick()

    assert seen == [{"feeds_read": 1}]  # "Run now" sees it while the run goes on
    (run,) = await stored_runs(db)
    assert (run.status, run.result, run.progress) == (
        JobStatus.SUCCEEDED,
        "done",
        {"feeds_read": 1},
    )


async def test_progress_that_cannot_be_kept_never_fails_the_run(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)

    async def unreachable(*_: object) -> bool:
        msg = "the database is down"
        raise OSError(msg)

    monkeypatch.setattr(runs, "note_progress", unreachable)
    seen: list[JSONValue] = []
    scheduler = Worker(db, _reporting(db, seen), FAST, Clock())

    assert await scheduler.tick()

    (run,) = await stored_runs(db)
    assert (run.status, run.progress, seen) == (JobStatus.SUCCEEDED, None, [None])
    assert "job.progress_failed" in _events(stream)


async def test_failures_are_retried_with_backoff_then_given_up(db: Database) -> None:
    job, clock = Recorder(error=ValueError("boom")), Clock()
    configure_logging(stream=io.StringIO())
    scheduler = Worker(db, scheduled(job), FAST, clock)
    start = clock.now

    await scheduler.tick()
    (first,) = await stored_runs(db)
    assert not await scheduler.tick()  # not before the backoff
    clock.advance(seconds=60)
    await scheduler.tick()
    (second,) = await stored_runs(db)
    clock.advance(seconds=120)
    await scheduler.tick()

    (last,) = await stored_runs(db)
    assert (first.status, first.run_after) == (JobStatus.PENDING, start + timedelta(seconds=60))
    assert second.run_after == start + timedelta(seconds=60 + 120)  # the backoff doubles
    assert (last.status, last.attempts, last.error) == (JobStatus.FAILED, 3, "ValueError")
    assert len(job.calls) == 3


async def test_a_job_running_too_long_is_stopped_and_retried(db: Database) -> None:
    configure_logging(stream=io.StringIO())
    settings = FAST.model_copy(update={"job_timeout_seconds": 0.01})
    scheduler = Worker(db, scheduled(Recorder(delay=1)), settings, Clock())

    await scheduler.tick()

    (run,) = await stored_runs(db)
    assert (run.status, run.error) == (JobStatus.PENDING, "TimeoutError")


@pytest.mark.parametrize(("own", "status"), [(5, JobStatus.SUCCEEDED), (0.01, JobStatus.PENDING)])
async def test_a_job_with_a_timeout_of_its_own_runs_for_that_long(
    db: Database, own: float, status: JobStatus
) -> None:
    configure_logging(stream=io.StringIO())
    settings = FAST.model_copy(update={"job_timeout_seconds": 1})
    job = Recorder(delay=0.1)
    registry = {
        "scrape": ScheduledJob(run=job, schedule=ConfigKey.SCRAPE_SCHEDULE, timeout_seconds=own)
    }
    scheduler = Worker(db, registry, settings, Clock())

    await scheduler.tick()

    (run,) = await stored_runs(db)
    assert run.status == status  # stopped and retried when its own time is up


async def test_a_crashed_workers_run_is_finished_by_another(db: Database) -> None:
    job, clock = Recorder(), Clock()
    await runs.plan(db, scheduled(job), clock())
    lease = timedelta(seconds=60)
    assert await runs.claim(db, ["scrape"], "crashed", now=clock(), lease=lease, attempts=3)
    survivor = Worker(db, scheduled(job), FAST, clock)

    assert not await survivor.tick()  # the lease still holds
    clock.advance(seconds=61)
    assert await survivor.tick()

    (run,) = await stored_runs(db)
    assert (run.status, run.attempts) == (JobStatus.SUCCEEDED, 2)


async def test_shutdown_hands_a_running_job_back(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_logging(stream=io.StringIO())
    monkeypatch.setattr(worker, "_DRAIN_SECONDS", 0.05)
    job = Recorder(delay=10)

    async with Worker(db, scheduled(job), FAST, Clock()).running():
        await job.called.wait()

    (run,) = await stored_runs(db)
    assert (run.status, run.attempts, run.lease_owner) == (JobStatus.PENDING, 0, None)


async def test_a_job_that_will_not_stop_is_left_behind_after_the_stop_margin(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shutdown is bounded: drain, then the stop margin; the run's lease passes it on."""
    stream = io.StringIO()
    configure_logging(stream=stream)
    monkeypatch.setattr(worker, "_DRAIN_SECONDS", 0.05)
    settings = FAST.model_copy(update={"lease_seconds": 0.4})  # stop margin: 0.1 s
    started, done = asyncio.Event(), asyncio.Event()

    async def stubborn(_: JobContext) -> JSONValue:
        started.set()
        while not done.is_set():
            with contextlib.suppress(asyncio.CancelledError):  # ignores being stopped
                await asyncio.sleep(0.01)
        return None

    loop = asyncio.get_running_loop()
    registry = {"scrape": ScheduledJob(stubborn, ConfigKey.SCRAPE_SCHEDULE)}
    async with Worker(db, registry, settings, Clock()).running():
        await started.wait()
        stopping = loop.time()
    took = loop.time() - stopping
    done.set()  # let the abandoned job end before the test does
    await asyncio.sleep(0.1)

    assert took < 0.5  # drain 0.05 s + stop margin 0.1 s, not forever
    assert "worker.stop_timed_out" in _events(stream)


async def test_a_hand_back_the_database_does_not_answer_is_given_up(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    monkeypatch.setattr(worker, "_DRAIN_SECONDS", 0.05)
    monkeypatch.setattr(worker, "_HAND_BACK_SECONDS", 0.05)
    job = Recorder(delay=10)

    async def stalled(*_: object) -> bool:
        await asyncio.Event().wait()  # the database never answers
        return True

    monkeypatch.setattr(runs, "release", stalled)
    async with asyncio.timeout(5), Worker(db, scheduled(job), FAST, Clock()).running():
        await job.called.wait()

    events = _events(stream)
    assert events[-2:] == ["job.hand_back_failed", "job.lease_lost"]
    (run,) = await stored_runs(db)
    assert run.status is JobStatus.RUNNING  # its lease expires; another worker takes it over


async def test_shutdown_lets_a_short_job_finish(db: Database) -> None:
    job = Recorder(delay=0.05)

    async with Worker(db, scheduled(job), FAST, Clock()).running():
        await job.called.wait()

    (run,) = await stored_runs(db)
    assert run.status is JobStatus.SUCCEEDED


async def test_waking_an_idle_worker_skips_the_poll_wait(db: Database) -> None:
    clock = Clock()
    job = Recorder()
    slow_poll = FAST.model_copy(update={"poll_seconds": 3600})

    async with Worker(db, scheduled(job), slow_poll, clock).running() as scheduler:
        await job.called.wait()  # the due run ran; the worker now idles for an hour
        job.called.clear()
        clock.advance(days=1)
        scheduler.wake()
        async with asyncio.timeout(5):
            await job.called.wait()

    assert len(await stored_runs(db)) == 2


async def test_a_failing_tick_is_logged_and_the_worker_keeps_going(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    job = Recorder()
    original, failures = runs.plan, [ConnectionError("database down")]

    async def flaky_plan(*args: object) -> None:
        if failures:
            raise failures.pop()
        await original(*args)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(runs, "plan", flaky_plan)

    async with Worker(db, scheduled(job), FAST, Clock()).running():
        async with asyncio.timeout(5):
            await job.called.wait()

    assert "scheduler.tick_failed" in _events(stream)


async def test_the_lease_is_renewed_while_a_job_runs_past_it(db: Database) -> None:
    clock = Clock()
    # Renewed every 0.2 s, each due within 0.45 s: room for a round trip to a busy database.
    settings = FAST.model_copy(update={"lease_seconds": 0.6})
    scheduler = Worker(db, scheduled(Recorder(delay=1.2)), settings, clock)  # two leases long
    renewed: list[bool] = []
    original = runs.heartbeat

    async def watched(*args: object) -> bool:
        clock.advance(seconds=1)
        renewed.append(await original(*args))  # pyright: ignore[reportArgumentType]
        return renewed[-1]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runs, "heartbeat", watched)
        await scheduler.tick()

    (run,) = await stored_runs(db)
    assert run.status is JobStatus.SUCCEEDED
    assert len(renewed) >= 4
    assert all(renewed)


async def test_a_job_stops_when_another_worker_takes_its_run_over(db: Database) -> None:
    """The guarantee: a run executes on one worker at a time, and only its owner records it."""
    stream = io.StringIO()
    configure_logging(stream=stream)
    settings = FAST.model_copy(update={"lease_seconds": 0.4})
    first_clock = Clock()
    slow, quick = Recorder(delay=5, result="first"), Recorder(result="second")
    first = Worker(db, scheduled(slow), settings, first_clock)
    # The second worker's clock is past the first one's lease, as if the first had stalled.
    second = Worker(db, scheduled(quick), settings, Clock(first_clock.now + timedelta(hours=1)))

    async with asyncio.timeout(3):
        running = asyncio.create_task(first.tick())
        await slow.called.wait()
        assert await second.tick()  # takes the run over and finishes it
        await running  # the first worker's next renewal finds the run gone and stops its job

    taken_over = next(run for run in await stored_runs(db) if run.result is not None)
    assert (taken_over.status, taken_over.result, taken_over.attempts) == (
        JobStatus.SUCCEEDED,
        "second",
        2,
    )
    assert taken_over.id == quick.calls[0].run_id == slow.calls[0].run_id
    assert _events(stream).count("job.succeeded") == 1  # only the owner's outcome
    assert "job.lease_lost" in _events(stream)


async def test_a_job_stops_before_its_lease_expires_when_renewals_fail(db: Database) -> None:
    """A worker cut off from the database stops its job before another worker could claim it."""
    stream = io.StringIO()
    configure_logging(stream=stream)
    lease = 0.4
    settings = FAST.model_copy(update={"lease_seconds": lease})
    scheduler = Worker(db, scheduled(Recorder(delay=5)), settings, Clock())

    async def unreachable(*_: object) -> bool:
        raise ConnectionError

    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runs, "heartbeat", unreachable)
        await scheduler.tick()

    assert loop.time() - started < lease  # stopped within the lease, at three quarters of it
    events = _events(stream)
    assert "job.heartbeat_failed" in events
    assert events[-1] == "job.lease_lost"
    (run,) = await stored_runs(db)
    assert run.status is JobStatus.RUNNING  # not recorded: whoever takes the run over records it


async def test_a_renewal_finishing_after_the_deadline_changes_nothing(db: Database) -> None:
    configure_logging(stream=io.StringIO())
    settings = FAST.model_copy(update={"lease_seconds": 0.2})
    scheduler = Worker(db, scheduled(Recorder(delay=5)), settings, Clock())

    async def stalled(*_: object) -> bool:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(5)  # answers only once the job was stopped
        return True

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runs, "heartbeat", stalled)
        await scheduler.tick()  # the late answer does not revive the stopped job's lease

    (run,) = await stored_runs(db)
    assert run.status is JobStatus.RUNNING


@pytest.mark.parametrize(
    ("job", "record"),
    [(Recorder(), "succeed"), (Recorder(error=ValueError("boom")), "fail")],
)
async def test_an_outcome_the_lease_no_longer_covers_is_not_reported(
    db: Database, job: Recorder, record: str
) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    scheduler = Worker(db, scheduled(job), FAST, Clock())

    async def too_late(*_: object, **__: object) -> bool:
        return False  # the compare-and-set found another owner

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runs, record, too_late)
        await scheduler.tick()

    events = _events(stream)
    assert events[-1] == "job.lease_lost"
    assert not {"job.succeeded", "job.retrying"} & set(events)


async def test_serve_runs_until_terminated(db: Database) -> None:
    job = Recorder()
    task = asyncio.create_task(serve(Worker(db, scheduled(job), FAST, Clock())))
    async with asyncio.timeout(5):
        await job.called.wait()

    signal.raise_signal(signal.SIGTERM)

    async with asyncio.timeout(5):
        await task


@dataclass(frozen=True)
class Attempt:
    name: str
    outcome: str
    duration: float | None
    start_delay: float | None


@dataclass
class RecordedTelemetry:
    """Stands in for the telemetry: records how each run is traced and measured."""

    traces: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    attempts: list[Attempt] = field(default_factory=list[Attempt])
    queue: list[tuple[int, float]] = field(default_factory=list[tuple[int, float]])
    runs: list[RecordedTrace] = field(default_factory=list[RecordedTrace])  # one per run

    def trace_job(  # the telemetry protocol
        self,
        name: str,
        *,
        session_id: str,
        user_id: str | None,
        tags: Sequence[str],
        metadata: Mapping[str, str],
    ) -> AbstractContextManager[RecordedTrace]:
        trace: dict[str, object] = {"name": name, "session_id": session_id, "user_id": user_id}
        self.traces.append(trace | {"tags": tags, "metadata": metadata})
        self.runs.append(RecordedTrace(f"job {name}"))
        return nullcontext(self.runs[-1])

    def session_url(self, session_id: str) -> str:
        return f"https://langfuse.test/sessions/{session_id}"

    def record_job(
        self, name: str, *, outcome: str, duration: float | None, start_delay: float | None
    ) -> None:
        self.attempts.append(Attempt(name, outcome, duration, start_delay))

    def record_queue(self, *, depth: int, wait: float) -> None:
        self.queue.append((depth, wait))


async def test_each_run_is_traced_with_its_session_and_trigger(db: Database) -> None:
    tracing, clock = RecordedTelemetry(), Clock()
    async with db.session() as session:
        manual, _ = await runs.enqueue(session, "scrape", clock(), triggered_by="basic:alice")
    scheduler = Worker(db, scheduled(Recorder()), FAST, clock, telemetry=tracing)

    while await scheduler.tick():
        pass

    scheduled_run = next(run for run in await stored_runs(db) if run.id != manual.id)
    by_user = {trace["user_id"]: trace for trace in tracing.traces}
    assert by_user["basic:alice"] == {  # who pressed "Run now"
        "name": "scrape",
        "session_id": str(manual.id),  # a session per run: its retries group together
        "user_id": "basic:alice",
        "tags": ["scrape", "manual"],
        "metadata": {"attempt": "1", "scheduled_for": manual.scheduled_for.isoformat()},
    }
    assert by_user[None] == {  # scheduled: nobody
        "name": "scrape",
        "session_id": str(scheduled_run.id),
        "user_id": None,
        "tags": ["scrape", "schedule"],
        "metadata": {"attempt": "1", "scheduled_for": scheduled_run.scheduled_for.isoformat()},
    }


async def test_each_attempt_is_measured_with_its_outcome_and_delay(db: Database) -> None:
    configure_logging(stream=io.StringIO())
    measured, clock = RecordedTelemetry(), Clock()
    job = Recorder(error=ValueError("boom"))
    scheduler = Worker(db, scheduled(job), FAST, clock, telemetry=measured)

    await scheduler.tick()
    clock.advance(seconds=90)  # 30 s after the retry was due
    await scheduler.tick()

    (run,) = await stored_runs(db)
    first, second = measured.attempts
    assert [first.outcome, second.outcome] == ["retrying", "retrying"]
    due_since = clock() - timedelta(seconds=90) - run.scheduled_for  # Clock starts a week on
    assert (first.start_delay, second.start_delay) == (due_since.total_seconds(), 30)
    assert all((attempt.duration or -1) >= 0 for attempt in measured.attempts)


async def test_the_queue_is_measured_while_a_job_runs(db: Database) -> None:
    """Every poll interval, not once per job: the gauges are the worker's heartbeat."""
    measured, clock, job = RecordedTelemetry(), Clock(), Recorder(delay=0.3)
    async with db.session() as session:  # older than the scheduled occurrence: runs first
        two_days_ago = clock() - timedelta(days=2)
        await runs.enqueue(session, "scrape", two_days_ago, triggered_by="basic:alice")

    async with Worker(db, scheduled(job), FAST, clock, telemetry=measured).running():
        await asyncio.wait_for(job.called.wait(), 5)
        measured.queue.clear()
        await asyncio.sleep(0.2)  # the job still runs; its scheduled occurrence waits for it
        during = list(measured.queue)

    assert len(during) >= 3  # polls every 0.01 s
    ((depth, wait),) = set(during)  # waiting for its job: congestion all the same
    assert depth == 1
    assert wait > 0


async def test_a_failed_measurement_is_logged_and_tried_again(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream, measured = io.StringIO(), RecordedTelemetry()
    configure_logging(stream=stream)
    backlog, failures = runs.backlog, [ConnectionError()]

    async def flaky(*args: Any) -> tuple[int, float]:  # noqa: ANN401  # passed through
        if failures:
            raise failures.pop()
        return await backlog(*args)

    monkeypatch.setattr(runs, "backlog", flaky)
    async with asyncio.timeout(5), Worker(db, {}, FAST, Clock(), telemetry=measured).running():
        while not measured.queue:  # noqa: ASYNC110  # the telemetry is all there is to watch
            await asyncio.sleep(0.01)

    assert "scheduler.measure_failed" in stream.getvalue()


@dataclass
class CutOff:
    """A query running until cancelled, which then fails as psycopg now and then does."""

    started: asyncio.Event = field(default_factory=asyncio.Event)
    tasks: list[asyncio.Task[Any] | None] = field(default_factory=list[asyncio.Task[Any] | None])

    async def __call__(self, *_: object) -> NoReturn:
        self.tasks.append(asyncio.current_task())
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise ConnectionError from None
        raise AssertionError  # never answers

    def ended(self) -> bool:
        return all(task and task.done() for task in self.tasks)


async def test_a_measurement_cut_off_mid_query_ends_with_the_worker(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its cancellation surfaces as an error, which the loop retries on: it stops all the same."""
    backlog = CutOff()
    monkeypatch.setattr(runs, "backlog", backlog)

    worker = Worker(db, {}, FAST, Clock(), telemetry=RecordedTelemetry())
    async with asyncio.timeout(5), worker.running():
        await backlog.started.wait()

    assert backlog.ended()  # nothing left behind, holding a connection


async def test_a_renewal_cut_off_mid_heartbeat_ends_with_its_job(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The job ends while its lease is being renewed: the renewal stops, the attempt ends."""
    heartbeat = CutOff()
    monkeypatch.setattr(runs, "heartbeat", heartbeat)

    async def job(_: JobContext) -> JSONValue:
        await heartbeat.started.wait()  # a renewal is under way
        return "done"

    renews_soon = SchedulerSettings(poll_seconds=0.01, lease_seconds=0.6)  # every 0.2 s
    registry = {"scrape": ScheduledJob(run=job, schedule=ConfigKey.SCRAPE_SCHEDULE)}
    async with asyncio.timeout(5):
        assert await Worker(db, registry, renews_soon, Clock()).tick()

    (run,) = await stored_runs(db)
    assert (run.status, heartbeat.ended()) == (JobStatus.SUCCEEDED, True)


def _failing_scrape(notifier: RecordingNotifier) -> dict[str, ScheduledJob]:
    job = Recorder(error=TimeoutError())
    return {"scrape": ScheduledJob(run=job, schedule=ConfigKey.SCRAPE_SCHEDULE, notifier=notifier)}


async def test_failures_are_told_to_the_jobs_notifier(db: Database) -> None:
    """Each failed attempt, with the run's trace; the notifier's policy decides what is news."""
    configure_logging(stream=io.StringIO())
    notifier, clock = RecordingNotifier(), Clock()
    twice = FAST.model_copy(update={"max_attempts": 2})
    scheduler = Worker(db, _failing_scrape(notifier), twice, clock, telemetry=RecordedTelemetry())

    failed_at = clock()
    await scheduler.tick()
    clock.advance(seconds=61)  # the retry is due
    await scheduler.tick()

    (run,) = await stored_runs(db)
    retrying, failed = notifier.alerts
    retry_at = failed_at + timedelta(seconds=FAST.retry_seconds)
    assert (retrying.outcome, retrying.attempt, retrying.retry_at) == ("retrying", 1, retry_at)
    assert (failed.outcome, failed.attempt, failed.retry_at) == ("failed", 2, None)
    assert {(a.job, a.run_id, a.max_attempts, a.error) for a in notifier.alerts} == {
        ("scrape", run.id, 2, "TimeoutError")
    }
    assert {a.langfuse_url for a in notifier.alerts} == {f"https://langfuse.test/sessions/{run.id}"}


@pytest.mark.parametrize("traced", [True, False])
async def test_a_dead_workers_last_attempt_is_reported_and_alerted(
    db: Database, *, traced: bool
) -> None:
    """Reaped, not run: the failure is logged, counted and told all the same."""
    stream, clock, measured = io.StringIO(), Clock(), RecordedTelemetry()
    configure_logging(stream=stream)
    notifier = RecordingNotifier()
    once = FAST.model_copy(update={"max_attempts": 1, "lease_seconds": 60})
    registry = _failing_scrape(notifier)
    await runs.plan(db, registry, clock())
    assert await runs.claim(  # by a worker that dies with it
        db, registry, "crashed", now=clock(), lease=timedelta(seconds=60), attempts=1
    )
    clock.advance(minutes=5)  # its lease long expired

    await Worker(db, registry, once, clock, telemetry=measured if traced else None).tick()

    (run,) = await stored_runs(db)
    (alert,) = notifier.alerts
    assert (alert.run_id, alert.outcome, alert.attempt, alert.error) == (
        run.id,
        "failed",
        1,
        "LeaseExpired",
    )
    assert [(a.outcome, a.duration) for a in measured.attempts] == [("failed", None)] * traced
    failed = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [(e["event"], e["error"]) for e in failed if e["event"] == "job.failed"] == [
        ("job.failed", "LeaseExpired")
    ]


async def test_success_and_a_lost_lease_tell_nobody(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lost run is its new worker's to report."""
    configure_logging(stream=io.StringIO())
    notifier, clock = RecordingNotifier(), Clock()
    succeeding = {"scrape": ScheduledJob(run=Recorder(), notifier=notifier)}
    async with db.session() as session:
        await runs.enqueue(session, "scrape", clock(), triggered_by="basic:alice")
    await Worker(db, succeeding, FAST, clock).tick()

    async def lost(*_: object, **__: object) -> bool:
        return False  # another worker took the run over meanwhile

    monkeypatch.setattr(runs, "fail", lost)
    await Worker(db, _failing_scrape(notifier), FAST, clock).tick()

    assert notifier.alerts == []


async def test_a_slow_alert_does_not_shorten_the_next_runs_lease(db: Database) -> None:
    """The lease starts with the claim: the reaped run's alert before it takes none of it."""
    clock, job = Clock(), Recorder(delay=0.3)
    settings = FAST.model_copy(update={"max_attempts": 1, "lease_seconds": 0.6})
    notifier = SlowNotifier(clock=clock, seconds=0.5)  # most of a lease, on both clocks
    registry = {
        "scrape": ScheduledJob(
            run=Recorder(), schedule=ConfigKey.SCRAPE_SCHEDULE, notifier=notifier
        ),
        "report": ScheduledJob(run=job),
    }
    await runs.plan(db, registry, clock())
    assert await runs.claim(  # by a worker that dies with it
        db, ["scrape"], "crashed", now=clock(), lease=timedelta(seconds=0.6), attempts=1
    )
    clock.advance(minutes=5)  # its lease long expired
    async with db.session() as session:
        await runs.enqueue(session, "report", clock(), triggered_by="basic:alice")

    assert await Worker(db, registry, settings, clock).tick()

    assert len(notifier.alerts) == 1
    assert {run.job: run.status for run in await stored_runs(db)} == {
        "scrape": JobStatus.FAILED,
        "report": JobStatus.SUCCEEDED,
    }


@dataclass
class SlowNotifier(RecordingNotifier):
    """Takes `seconds` to tell, by the event loop and by the wall clock alike."""

    clock: Clock = field(default_factory=Clock)
    seconds: float = 0

    @override
    async def notify(self, notice: Notice) -> None:
        await super().notify(notice)
        await asyncio.sleep(self.seconds)
        self.clock.advance(seconds=self.seconds)


@pytest.mark.parametrize("failure", ["raises", "hangs"])
async def test_a_failing_notifier_is_logged_and_the_worker_goes_on(
    db: Database, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    monkeypatch.setattr(worker, "_ALERT_SECONDS", 0.1)
    notifier = RecordingNotifier(error=ConnectionError(), hangs=failure == "hangs")
    once = FAST.model_copy(update={"max_attempts": 1})

    async with asyncio.timeout(5):
        assert await Worker(db, _failing_scrape(notifier), once, Clock()).tick()

    (run,) = await stored_runs(db)
    assert run.status is JobStatus.FAILED  # recorded before anyone was told
    assert "job.alert_failed" in stream.getvalue()


async def test_a_runs_result_goes_to_its_trace(db: Database) -> None:
    """The trace's output: what a run returned; a run that failed returned nothing."""
    configure_logging(stream=io.StringIO())
    traced, clock = RecordedTelemetry(), Clock()
    succeeding, failing = Recorder(result=["Hello", "world"]), Recorder(error=ValueError())
    await Worker(db, scheduled(succeeding), FAST, clock, telemetry=traced).tick()
    clock.advance(days=1)
    await Worker(db, scheduled(failing), FAST, clock, telemetry=traced).tick()

    assert [run.results for run in traced.runs] == [[["Hello", "world"]], []]


async def test_a_job_traces_its_steps_in_its_runs_trace(db: Database) -> None:
    traced = RecordedTelemetry()
    job = Recorder()
    await Worker(db, scheduled(job), FAST, Clock(), telemetry=traced).tick()

    (context,) = job.calls
    (run,) = traced.runs
    assert context.trace is run  # the job's steps nest in its run's trace


async def test_without_telemetry_a_job_traces_nowhere(db: Database) -> None:
    job = Recorder()
    await Worker(db, scheduled(job), FAST, Clock()).tick()

    (context,) = job.calls
    assert context.trace is UNTRACED
