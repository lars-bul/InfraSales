"""The scheduler worker: plans due runs, then claims and runs them one at a time under a lease.

Restart-safe by construction: runs live in the database, a crashed worker's lease expires and
another worker takes the run over, and a worker shutting down hands its run back.

A run executes on one worker at a time: a worker renews its lease while the job runs and stops
the job as soon as the lease is lost, or could not be renewed in time, before any other worker
may take the run over (self-fencing; hosts' clocks must agree within a quarter of the lease).
"""

import asyncio
import contextlib
import logging
import os
import random
import socket
import uuid
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import AbstractContextManager, asynccontextmanager, nullcontext
from datetime import datetime, timedelta
from functools import partial
from typing import Literal, Protocol, Self

import structlog
from sqlalchemy.exc import SQLAlchemyError
from structlog.stdlib import BoundLogger

from infrasales.core.db import Database
from infrasales.core.models import JSONValue, utcnow
from infrasales.core.signals import stop_requested
from infrasales.core.state import StateKey
from infrasales.core.tasks import raise_if_cancelled
from infrasales.scheduler import runs
from infrasales.scheduler.models import JobRun
from infrasales.scheduler.registry import UNTRACED, Alert, JobContext, Registry, Trace
from infrasales.scheduler.settings import SchedulerSettings
from infrasales.scheduler.steps import Steps

_log = structlog.stdlib.get_logger(__name__)
_DRAIN_SECONDS = 10
_HAND_BACK_SECONDS = 5
_ALERT_SECONDS = 30
_PROGRESS_SECONDS = 5  # keeping a run's progress may not hold up the job
_RENEWALS_PER_LEASE = 4

type Outcome = Literal["succeeded", "retrying", "failed", "released", "lease_lost"]
_EVENTS: dict[Outcome, tuple[int, str]] = {
    "succeeded": (logging.INFO, "job.succeeded"),
    "released": (logging.INFO, "job.released"),
    "retrying": (logging.WARNING, "job.retrying"),
    "failed": (logging.ERROR, "job.failed"),
    "lease_lost": (logging.WARNING, "job.lease_lost"),
}


class LeaseLostError(Exception):
    """The run's lease was lost or could not be renewed in time: another worker may own it."""


class JobTelemetry(Protocol):
    """Traces and metrics of job runs (implemented by `infrasales.core.telemetry`)."""

    def trace_job(
        self,
        name: str,
        *,
        session_id: str,
        user_id: str | None,
        tags: Sequence[str],
        metadata: Mapping[str, str],
    ) -> AbstractContextManager[Trace]:
        """Trace one run of the job `name`."""
        ...

    def session_url(self, session_id: str) -> str | None:
        """Where a run's trace can be looked into (Langfuse), if anywhere."""
        ...

    def record_job(
        self, name: str, *, outcome: str, duration: float | None, start_delay: float | None
    ) -> None:
        """Measure one finished attempt: its outcome, how long it ran, how late it started."""
        ...

    def record_queue(self, *, depth: int, wait: float) -> None:
        """The queue, each poll interval: runs due, and how long the oldest has waited (s)."""
        ...


class Worker:
    def __init__(
        self,
        db: Database,
        registry: Registry,
        settings: SchedulerSettings,
        clock: Callable[[], datetime] = utcnow,
        telemetry: JobTelemetry | None = None,
    ) -> None:
        self.id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._db = db
        self._registry = registry
        self._settings = settings
        self._clock = clock
        self._telemetry = telemetry
        self._lease = timedelta(seconds=settings.lease_seconds)
        self._fence = settings.lease_seconds - settings.stop_margin_seconds
        self._wake = asyncio.Event()
        self._stopping = False

    def wake(self) -> None:
        """Look for due runs now instead of at the next poll (after a manual trigger)."""
        self._wake.set()

    async def tick(self) -> bool:
        """Plan, reap, then claim and run one due job; whether one ran."""
        now, attempts = self._clock(), self._settings.max_attempts
        await runs.plan(self._db, self._registry, now)
        for run in await runs.reap(self._db, now, attempts):
            await self._report_reaped(run)
        now, leased_at = self._clock(), asyncio.get_running_loop().time()
        run = await runs.claim(
            self._db, self._registry, self.id, now=now, lease=self._lease, attempts=attempts
        )
        if run is None:
            return False
        await self._execute(run, leased_at)
        return True

    async def _execute(self, run: JobRun, leased_at: float) -> None:
        log = _log.bind(job=run.job, run_id=str(run.id), attempt=run.attempts)
        log.info("job.started")
        loop = asyncio.get_running_loop()
        started = loop.time()
        start_delay = max((self._clock() - run.run_after).total_seconds(), 0)
        job = self._registry[run.job]
        timeout = job.timeout_seconds or self._settings.job_timeout_seconds

        def report(outcome: Outcome, **fields: object) -> None:
            level, event = _EVENTS[outcome]
            log.log(level, event, **fields)
            if self._telemetry:
                duration = loop.time() - started
                self._telemetry.record_job(
                    run.job, outcome=outcome, duration=duration, start_delay=start_delay
                )

        try:
            async with (
                self._leased(run, leased_at, log),
                asyncio.timeout(timeout),
            ):
                with self._trace(run) as trace:
                    steps, progress = Steps(self._db, run.id), partial(self._note, run, log)
                    context = JobContext(run.id, run.scheduled_for, steps, trace, progress)
                    result = await job.run(context)
                    trace.finish(result)
        except LeaseLostError:
            report("lease_lost")
        except asyncio.CancelledError:  # shutting down: another worker continues
            report("released" if await self._hand_back(run, log) else "lease_lost")
            raise
        except Exception as error:  # noqa: BLE001
            retry_at = self._retry_at(run)
            error_type, now = type(error).__name__, self._clock()
            recorded = await runs.fail(
                self._db, run, self.id, now, error=error_type, retry_at=retry_at
            )
            outcome = ("retrying" if retry_at else "failed") if recorded else "lease_lost"
            report(outcome, error=error_type, retry_at=retry_at, exc_info=True)
            if outcome != "lease_lost":  # lost: the run's new worker decides about it
                await self._alert(run, outcome, error_type, retry_at)
        else:
            recorded = await runs.succeed(self._db, run, self.id, self._clock(), result)
            report("succeeded" if recorded else "lease_lost")
            if recorded:
                await self._follow_up(run, log)

    async def _follow_up(self, run: JobRun, log: BoundLogger) -> None:
        """Queue the jobs that follow a succeeded run: never the finished run's failure."""
        for job in self._registry[run.job].then:
            try:
                async with asyncio.timeout(_HAND_BACK_SECONDS), self._db.session() as session:
                    _, queued = await runs.follow_up(session, job, self._clock())
            except Exception:  # the run succeeded; the next one queues it again
                log.warning("job.follow_up_failed", follow_up=job, exc_info=True)
                continue
            log.info("job.follow_up", follow_up=job, queued=queued)
            if queued:
                self.wake()

    async def _note(self, run: JobRun, log: BoundLogger, progress: JSONValue) -> None:
        """Keep how far `run` got, for "Run now" to show: bounded, never the job's failure.

        Only while this worker holds the run's lease; a lost lease is the renewal's to notice.
        """
        try:
            async with asyncio.timeout(_PROGRESS_SECONDS):
                await runs.note_progress(self._db, run, self.id, progress)
        except Exception:  # e.g. the database is briefly down: the next report may get through
            raise_if_cancelled()
            log.warning("job.progress_failed", exc_info=True)

    async def _report_reaped(self, run: JobRun) -> None:
        """A run reaping failed, like any failure: logged, measured, alerted; best effort.

        Its outcome is committed already: should this process die before telling anyone, the
        run stays failed and visible in its history, only the alert is lost.
        """
        error = run.error or "LeaseExpired"
        _log.error("job.failed", job=run.job, run_id=str(run.id), attempt=run.attempts, error=error)
        if self._telemetry:
            self._telemetry.record_job(run.job, outcome="failed", duration=None, start_delay=None)
        await self._alert(run, "failed", error, None)

    async def _alert(
        self,
        run: JobRun,
        outcome: Literal["failed", "retrying"],
        error: str,
        retry_at: datetime | None,
    ) -> None:
        """Tell the job's notifier about the failure: bounded, and never the worker's failure."""
        notifier = self._registry[run.job].notifier
        if notifier is None:
            return
        alert = Alert(
            job=run.job,
            run_id=run.id,
            outcome=outcome,
            attempt=run.attempts,
            max_attempts=self._settings.max_attempts,
            error=error,
            retry_at=retry_at,
            langfuse_url=self._telemetry.session_url(str(run.id)) if self._telemetry else None,
        )
        try:
            async with asyncio.timeout(_ALERT_SECONDS):
                await notifier.notify(alert)
        except Exception:  # noqa: BLE001  # best effort: the outcome is recorded and logged
            raise_if_cancelled()
            _log.exception("job.alert_failed", job=run.job, run_id=str(run.id))

    async def _hand_back(self, run: JobRun, log: BoundLogger) -> bool:
        """Return `run` to the queue, briefly: if the database does not answer, its lease ends."""
        try:
            async with asyncio.timeout(_HAND_BACK_SECONDS):
                return await runs.release(self._db, run, self.id, self._clock())
        except TimeoutError, SQLAlchemyError, OSError:
            log.warning("job.hand_back_failed", exc_info=True)  # another worker takes it over
            return False

    def _trace(self, run: JobRun) -> AbstractContextManager[Trace]:
        """One trace per run: a session per run (its retries), the admin who triggered it."""
        if self._telemetry is None:
            return nullcontext(UNTRACED)
        return self._telemetry.trace_job(
            run.job,
            session_id=str(run.id),
            user_id=run.triggered_by,
            tags=[run.job, run.trigger.value],
            metadata={"attempt": str(run.attempts), "scheduled_for": run.scheduled_for.isoformat()},
        )

    def _retry_at(self, run: JobRun) -> datetime | None:
        if run.attempts >= self._settings.max_attempts:
            return None
        delay = self._settings.retry_seconds * 2 ** (run.attempts - 1)  # 1, 2, 4, ... intervals
        return self._clock() + timedelta(seconds=delay)

    @asynccontextmanager
    async def _leased(
        self, run: JobRun, leased_at: float, log: BoundLogger
    ) -> AsyncGenerator[None]:
        """Hold the run's lease while the block runs, and stop the block before it runs out.

        `leased_at` is when the claim began (event loop time). Each renewal moves the deadline;
        when another worker took the run over, or no renewal succeeded in time, the block is
        cancelled and `LeaseLostError` raised.
        """
        deadline = asyncio.timeout_at(leased_at + self._fence)
        try:
            async with deadline:
                renewal = asyncio.create_task(self._renew(run, deadline, log))
                try:
                    yield
                finally:  # no renewal may overlap writing the outcome
                    renewal.cancel()
                    await asyncio.wait([renewal])
        except TimeoutError as error:  # the job's own timeout passes through
            if deadline.expired():
                raise LeaseLostError from error
            raise

    async def _renew(self, run: JobRun, deadline: asyncio.Timeout, log: BoundLogger) -> None:
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(self._settings.lease_seconds / _RENEWALS_PER_LEASE)
            renewing_at = loop.time()
            try:
                held = await runs.heartbeat(self._db, run, self.id, self._clock() + self._lease)
            except Exception:  # the database may be briefly unreachable: retry until the deadline
                raise_if_cancelled()
                log.exception("job.heartbeat_failed")
                continue
            if deadline.expired():  # the job is being stopped already
                return
            if not held:  # another worker took the run over: stop at once
                deadline.reschedule(loop.time())
                return
            deadline.reschedule(renewing_at + self._fence)

    async def run(self) -> None:
        """Work until stopped; with telemetry, measure the queue alongside.

        Measured every poll interval, also while a job runs: the gauges are the worker's
        heartbeat, silent only when no worker runs.
        """
        measuring = asyncio.create_task(self._measure(self._telemetry)) if self._telemetry else None
        try:
            await self._work()
        finally:
            if measuring:
                measuring.cancel()
                await asyncio.wait([measuring])  # its connection back before the worker stops

    async def _work(self) -> None:
        """Tick, and when idle sleep a poll interval (±20 % jitter)."""
        while not self._stopping:
            self._wake.clear()
            try:
                ran = await self.tick()
            except Exception:  # noqa: BLE001  # e.g. the database is down: retry at the next poll
                _log.exception("scheduler.tick_failed")
                ran = False
            if not ran and not self._stopping:
                jitter = random.uniform(0.8, 1.2)  # noqa: S311  # spreads replicas, not security
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self._settings.poll_seconds * jitter)

    async def _measure(self, telemetry: JobTelemetry) -> None:
        attempts = self._settings.max_attempts
        while True:
            try:
                depth, wait = await runs.backlog(self._db, self._registry, self._clock(), attempts)
                telemetry.record_queue(depth=depth, wait=wait)
            except Exception:  # noqa: BLE001  # e.g. the database is down: again at the next poll
                raise_if_cancelled()
                _log.exception("scheduler.measure_failed")
            await asyncio.sleep(self._settings.poll_seconds)

    @asynccontextmanager
    async def running(self) -> AsyncGenerator[Self]:
        """Run in the background for the block; then let a running job finish, or hand it back.

        Bounded: the drain, then the stop margin for a cancelled job to end. A job that has not
        ended by then is left behind, so the process can exit; its run's lease passes it on.
        """
        task = asyncio.create_task(self.run())
        try:
            yield self
        finally:
            self._stopping = True
            self._wake.set()
            done, _ = await asyncio.wait({task}, timeout=_DRAIN_SECONDS)
            if not done:
                task.cancel()
                done, _ = await asyncio.wait({task}, timeout=self._settings.stop_margin_seconds)
            if done:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            else:
                _log.error("worker.stop_timed_out")


WORKER = StateKey[Worker]("worker")  # set while the web app runs the worker in-process


async def serve(worker: Worker) -> None:
    """Run `worker` until SIGINT or SIGTERM (`infrasales worker`)."""
    async with worker.running():
        await stop_requested()
