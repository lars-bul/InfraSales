"""Shared scheduler test helpers: a settable clock, recording jobs, stored runs."""

import asyncio
import uuid
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import col, select

from infrasales.config.schemas import ConfigKey
from infrasales.core.db import Database
from infrasales.core.models import JSONValue, utcnow
from infrasales.scheduler.models import JobRun
from infrasales.scheduler.registry import (
    UNREPORTED,
    UNTRACED,
    JobContext,
    Progress,
    ScheduledJob,
    Trace,
)
from infrasales.scheduler.settings import SchedulerSettings
from infrasales.scheduler.steps import Steps

FAST = SchedulerSettings(poll_seconds=0.01, lease_seconds=60, retry_seconds=60)


@dataclass
class Clock:
    """A clock tests move by hand; starts a week ahead, so seeded schedules are due."""

    now: datetime = field(default_factory=lambda: utcnow() + timedelta(days=8))

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@dataclass
class Recorder:
    """A job that records its calls, then returns `result` or raises `error`."""

    result: JSONValue = "done"
    error: Exception | None = None
    delay: float = 0
    calls: list[JobContext] = field(default_factory=list[JobContext])
    called: asyncio.Event = field(default_factory=asyncio.Event)  # set by each call

    async def __call__(self, context: JobContext, /) -> JSONValue:
        self.calls.append(context)
        self.called.set()
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result


def scheduled(job: Recorder) -> dict[str, ScheduledJob]:
    return {"scrape": ScheduledJob(run=job, schedule=ConfigKey.SCRAPE_SCHEDULE)}


async def stored_runs(db: Database) -> list[JobRun]:
    async with db.session() as session:
        return list((await session.exec(select(JobRun).order_by(col(JobRun.run_after)))).all())


@dataclass
class RecordedTrace:
    """Stands in for a run's trace: each step, what it was given and what it returned."""

    name: str = "run"
    given: JSONValue = None
    results: list[JSONValue] = field(default_factory=list[JSONValue])  # `finish`ed with
    steps: list[RecordedTrace] = field(default_factory=list["RecordedTrace"])

    def step(self, name: str, given: JSONValue = None) -> AbstractContextManager[RecordedTrace]:
        step = RecordedTrace(name, given)
        self.steps.append(step)
        return nullcontext(step)

    def finish(self, result: JSONValue) -> None:
        self.results.append(result)


def context_for(
    run_id: uuid.UUID | None = None,
    db: Database | None = None,
    trace: Trace = UNTRACED,
    progress: Progress = UNREPORTED,
) -> JobContext:
    """A job's context; its steps need `db`, holding the run, only if the job uses them."""
    run_id = run_id or uuid.uuid7()
    steps = Steps(db or Database("sqlite+aiosqlite://"), run_id)
    return JobContext(run_id, utcnow(), steps, trace, progress)


async def queued_run(db: Database, job: str = "report") -> uuid.UUID:
    """A run of `job` in the database: steps belong to one."""
    async with db.session() as session:
        run = JobRun(job=job, scheduled_for=utcnow(), run_after=utcnow())
        session.add(run)
    return run.id
