"""Job runs in the database: planning, claiming under a lease, and recording outcomes."""

import uuid
from bisect import bisect_right
from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta
from typing import Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, exists, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased, load_only
from sqlmodel import col, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.config import service as config
from infrasales.core.db import Database, insert_if_absent
from infrasales.core.models import JSONValue
from infrasales.scheduler.models import (
    ACTIVE_MANUAL,
    QUEUED_FOLLOW_UP,
    JobRun,
    JobStatus,
    JobTrigger,
    RunTrigger,
)
from infrasales.scheduler.recurrence import latest_occurrence
from infrasales.scheduler.registry import Registry
from infrasales.scheduler.schemas import (
    ActivityQuery,
    BucketCounts,
    DayCounts,
    JobRunRead,
    RunActivity,
    RunCounts,
    RunFilter,
    RunQuery,
    RunSummary,
)

# What the API shows of a run, polled every few seconds: how far it got, but results, possibly
# large, stay unread.
_SHOWN = load_only(*(getattr(JobRun, field) for field in [*JobRunRead.model_fields, "progress"]))
# The run history also shows who started each run and what it did, a page of runs at a time.
_LISTED = load_only(
    *(
        getattr(JobRun, field)
        for field in [*JobRunRead.model_fields, "progress", "triggered_by", "result"]
    )
)


async def plan(db: Database, registry: Registry, now: datetime) -> None:
    """Record the latest due occurrence of every enabled schedule, once.

    Occurrences before the schedule's last change are skipped, so an edit never fires at once;
    after downtime, missed occurrences collapse into one catch-up run.
    """
    async with db.session() as session:
        for name, job in registry.items():
            entry = await config.entry(session, job.schedule) if job.schedule else None
            if entry is None or not entry.value.enabled:
                continue
            due = latest_occurrence(entry.value, now)
            if due > entry.updated_at:
                values = {"job": name, "scheduled_for": due, "run_after": due, "attempts": 0}
                await insert_if_absent(
                    session,
                    JobRun,
                    values | {"status": JobStatus.PENDING},
                    unique=["job", "scheduled_for"],
                )


async def enqueue(
    session: AsyncSession, job: str, now: datetime, *, triggered_by: str, key: UUID | None = None
) -> tuple[JobRun, bool]:
    """A run of `job` due at once, in the caller's transaction (an admin's "Run now").

    Returns the run and whether it is new. One manual run per job at a time, enforced by the
    database: while one is queued or running, it is returned instead, even to a concurrent
    request, so a double click (or a second admin) does not send the report twice.
    `triggered_by` is the admin's pseudonymous subject: traces attribute the run to them.

    `key`, the request's Idempotency-Key, makes the request repeatable: asked again with it,
    e.g. after its answer was lost, it gets the same run, even once that run has finished.
    Owning the key and allocating the run are one step: a request that finds the key taken,
    by an earlier request or a concurrent one, discards what it allocated and gets that run.
    """
    if key is None:
        return await _manual_run(session, job, now, triggered_by)
    allocation = await session.begin_nested()  # undone if the key is taken
    run, queued = await _manual_run(session, job, now, triggered_by)
    trigger = {"job": job, "key": key, "run_id": run.id}
    if await insert_if_absent(session, JobTrigger, trigger, unique=["job", "key"]):
        await allocation.commit()
        return run, queued
    await allocation.rollback()  # a run queued here is discarded: the key's run answers
    answered = select(JobRun).join(JobTrigger).where(JobTrigger.job == job, JobTrigger.key == key)
    return (await session.exec(answered)).one(), False


async def _manual_run(
    session: AsyncSession, job: str, now: datetime, triggered_by: str
) -> tuple[JobRun, bool]:
    run_id = uuid.uuid7()
    values = {
        "id": run_id,
        "job": job,
        "scheduled_for": now,
        "run_after": now,
        "attempts": 0,
        "status": JobStatus.PENDING,
        "trigger": RunTrigger.MANUAL,
        "triggered_by": triggered_by,
    }
    if await insert_if_absent(session, JobRun, values, unique=["job"], where=ACTIVE_MANUAL):
        return await session.get_one(JobRun, run_id), True
    # The active run: still queued or running, or finished in the instant since the conflict.
    manual = select(JobRun).where(col(JobRun.job) == job, col(JobRun.trigger) == RunTrigger.MANUAL)
    latest = manual.order_by(col(JobRun.created_at).desc()).limit(1)
    return (await session.exec(latest)).one(), False


async def follow_up(session: AsyncSession, job: str, now: datetime) -> tuple[JobRun | None, bool]:
    """A run of `job` due at once because a run of another job finished, in the caller's session.

    Returns the run and whether it is new.

    One waits at a time, enforced by the database: while one is waiting, it is returned instead
    (None if it started in the instant since). A running one doesn't count: the new one gates
    what the other job wrote after it started.
    """
    run_id = uuid.uuid7()
    values = {
        "id": run_id,
        "job": job,
        "scheduled_for": now,
        "run_after": now,
        "attempts": 0,
        "status": JobStatus.PENDING,
        "trigger": RunTrigger.FOLLOW_UP,
    }
    if await insert_if_absent(session, JobRun, values, unique=["job"], where=QUEUED_FOLLOW_UP):
        return await session.get_one(JobRun, run_id), True
    waiting = select(JobRun).where(
        col(JobRun.job) == job,
        col(JobRun.trigger) == RunTrigger.FOLLOW_UP,
        col(JobRun.status) == JobStatus.PENDING,
    )
    return (await session.exec(waiting)).first(), False


async def active(session: AsyncSession, job: str) -> JobRun | None:
    """The run of `job` under way, if any (as the API shows it): scheduled or manual.

    The one running, else one waiting: a manual run queued, or a run waiting to be tried again.
    A scheduled run not yet tried is no run under way: it is the next run.
    """
    of_job = select(JobRun).options(_SHOWN).where(col(JobRun.job) == job)
    running = of_job.where(col(JobRun.status) == JobStatus.RUNNING)
    waiting = of_job.where(_waiting()).order_by(col(JobRun.id))
    return (await session.exec(running)).first() or (await session.exec(waiting)).first()


async def under_way(session: AsyncSession) -> list[str]:
    """The jobs with a run under way, as `active` tells it of each."""
    query = select(JobRun.job).where(or_(col(JobRun.status) == JobStatus.RUNNING, _waiting()))
    return sorted(set((await session.exec(query)).all()))


def _waiting() -> ColumnElement[bool]:
    """A run waiting to start that counts as under way: queued by hand or a job, or retried."""
    return and_(
        col(JobRun.status) == JobStatus.PENDING,
        or_(
            col(JobRun.trigger).in_([RunTrigger.MANUAL, RunTrigger.FOLLOW_UP]),
            col(JobRun.attempts) > 0,
        ),
    )


async def recent(session: AsyncSession, job: str | None, query: RunQuery) -> list[JobRun]:
    """The runs of `job` (None: of every job), newest first: scheduled and manual, finished or not.

    `before` pages back from a run: IDs are time-ordered (UUIDv7).
    """
    statement = select(JobRun).options(_LISTED).where(*_filters(job, query))
    if query.before:
        statement = statement.where(col(JobRun.id) < query.before)
    # the (job, id) index read backwards; every job's runs, the primary key's
    newest = statement.order_by(col(JobRun.id).desc())
    return list(await session.exec(newest.limit(query.limit)))


def _filters(job: str | None, query: RunFilter) -> list[ColumnElement[bool]]:
    """What the runs of `job` (None: of every job) that `query` asks for have in common."""
    return [
        *([col(JobRun.job) == job] if job is not None else []),
        *([col(JobRun.status) == query.status] if query.status else []),
        *([col(JobRun.trigger) == query.trigger] if query.trigger else []),
        *([col(JobRun.scheduled_for) >= query.start] if query.start else []),
        *([col(JobRun.scheduled_for) < query.end] if query.end else []),
    ]


HOURLY_UP_TO = timedelta(days=2)  # longer: a bucket per day


def activity_window(
    query: ActivityQuery, now: datetime, zone: ZoneInfo
) -> tuple[datetime, datetime]:
    """From when until when `query` counts runs, unless it says: until now, from 6 days before.

    The days are calendar days in `zone`: the 7 of them end with the end's.
    """
    end = query.end or now
    week = end.astimezone(zone).date() - timedelta(days=6)
    return query.start or datetime.combine(week, time(), tzinfo=zone), end


def _buckets(
    start: datetime, end: datetime, zone: ZoneInfo
) -> tuple[Literal["hour", "day"], list[datetime]]:
    """Where each bucket from `start` until `end` begins: whole hours or midnights in `zone`."""
    local = start.astimezone(zone)
    if end - start <= HOURLY_UP_TO:
        hour = local.replace(minute=0, second=0, microsecond=0).astimezone(UTC)
        hours: list[datetime] = []
        while hour < end:  # in UTC: a DST change adds or drops an hour, not a bucket's length
            hours.append(hour)
            hour += timedelta(hours=1)
        return "hour", hours
    first, last = local.date(), (end - timedelta(microseconds=1)).astimezone(zone).date()
    days = [first + timedelta(n) for n in range((last - first).days + 1)]
    return "day", [datetime.combine(day, time(), tzinfo=zone) for day in days]


async def activity(  # noqa: PLR0913  # the runs asked for, over which time, counted where
    session: AsyncSession,
    job: str | None,
    query: RunFilter,
    *,
    start: datetime,
    end: datetime,
    zone: ZoneInfo,
) -> RunActivity:
    """How the runs of `job` (None: of every job) that `query` asks for ended, per hour or day.

    Runs count by when they were scheduled, as the run history lists them, from `start` until
    `end`; only runs that ended count, a final failure as failed.
    """
    unit, starts = _buckets(start, end, zone)
    buckets = [BucketCounts(start=at, succeeded=0, failed=0) for at in starts]
    window = query.model_copy(update={"start": start, "end": end})
    ended = select(JobRun.status, JobRun.scheduled_for).where(
        *_filters(job, window), col(JobRun.status).in_([JobStatus.SUCCEEDED, JobStatus.FAILED])
    )
    for status, scheduled_for in await session.exec(ended):
        counts = buckets[bisect_right(starts, scheduled_for) - 1]
        if status is JobStatus.SUCCEEDED:
            counts.succeeded += 1
        else:
            counts.failed += 1
    return RunActivity(start=start, end=end, unit=unit, buckets=buckets)


async def summary(session: AsyncSession, job: str, now: datetime, zone: ZoneInfo) -> RunSummary:
    """How the runs of `job` ended: in the last 24 hours, 7 days, and 7 calendar days in `zone`.

    Runs count by when they finished. A run waiting for its retry has not ended: only a final
    failure counts as failed.
    """
    today = now.astimezone(zone).date()
    first_day = today - timedelta(days=6)
    week_ago, day_ago = now - timedelta(days=7), now - timedelta(days=1)
    since = min(week_ago, datetime.combine(first_day, time(), tzinfo=zone))  # DST: a 25 h day
    ended = select(JobRun.status, JobRun.finished_at).where(
        col(JobRun.job) == job,
        col(JobRun.status).in_([JobStatus.SUCCEEDED, JobStatus.FAILED]),
        col(JobRun.finished_at) >= since,
    )
    last_24h, last_7d = RunCounts(succeeded=0, failed=0), RunCounts(succeeded=0, failed=0)
    days = [DayCounts(day=first_day + timedelta(n), succeeded=0, failed=0) for n in range(7)]
    for status, finished in await session.exec(ended):
        finished_at = cast("datetime", finished)  # a run that ended has finished, typed or not
        local_day = finished_at.astimezone(zone).date()
        windows = [
            *([last_24h] if finished_at > day_ago else []),
            *([last_7d] if finished_at > week_ago else []),
            *([days[(local_day - first_day).days]] if local_day >= first_day else []),
        ]
        for counts in windows:
            if status is JobStatus.SUCCEEDED:
                counts.succeeded += 1
            else:
                counts.failed += 1
    return RunSummary(last_24h=last_24h, last_7d=last_7d, days=days)


async def find(session: AsyncSession, job: str, run_id: UUID) -> JobRun | None:
    """The run `run_id` of `job`, if there is one (as the API shows it)."""
    run = await session.get(JobRun, run_id, options=[_SHOWN])
    return run if run and run.job == job else None


def _claimable(
    jobs: Iterable[str], now: datetime, max_attempts: int, *, blocked: bool = False
) -> ColumnElement[bool]:
    """Due runs of `jobs`: pending ones whose job is not running, and abandoned running ones.

    `blocked`: also the pending ones waiting for a run of their job to end.
    """
    other = aliased(JobRun)
    job_running = exists().where(
        col(other.job) == col(JobRun.job), col(other.status) == JobStatus.RUNNING
    )
    pending = and_(col(JobRun.status) == JobStatus.PENDING, col(JobRun.run_after) <= now)
    if not blocked:
        pending = and_(pending, ~job_running)
    abandoned = and_(col(JobRun.status) == JobStatus.RUNNING, col(JobRun.lease_expires_at) < now)
    return and_(
        col(JobRun.job).in_(list(jobs)),
        col(JobRun.attempts) < max_attempts,
        or_(pending, abandoned),
    )


async def backlog(
    db: Database, jobs: Iterable[str], now: datetime, max_attempts: int
) -> tuple[int, float]:
    """How many runs are due and waiting, and how long the oldest has waited (s).

    Including those waiting for a run of their job to end: a job slower than its schedule is
    congestion too.
    """
    due = select(func.count(), func.min(col(JobRun.run_after)))
    waiting_runs = _claimable(jobs, now, max_attempts, blocked=True)
    async with db.session() as session:
        waiting, oldest = (await session.exec(due.where(waiting_runs))).one()
    oldest_due = cast("datetime | None", oldest)  # MIN over no rows is NULL, typed or not
    return waiting, 0.0 if oldest_due is None else (now - oldest_due).total_seconds()


async def claim(  # noqa: PLR0913  # the lease's terms, keyword-only
    db: Database, jobs: Iterable[str], owner: str, *, now: datetime, lease: timedelta, attempts: int
) -> JobRun | None:
    """Lease the oldest due run to `owner`: pending runs, and running ones whose worker died.

    One statement. On PostgreSQL, concurrent claims skip runs another claim has locked, so
    each worker gets a different run instead of waiting for the same one (`SKIP LOCKED`), and
    the conditions are checked again on the locked row. SQLite serializes writers (and ignores
    `FOR UPDATE`). A run is never leased twice.
    """
    claimable = _claimable(jobs, now, attempts)
    oldest = (
        select(JobRun.id)
        .where(claimable)
        .order_by(col(JobRun.run_after))
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    statement = (
        update(JobRun)
        .where(col(JobRun.id) == oldest.scalar_subquery(), claimable)
        .values(
            status=JobStatus.RUNNING,
            attempts=col(JobRun.attempts) + 1,
            lease_owner=owner,
            lease_expires_at=now + lease,
            progress=None,  # the attempt starts from the top: so does its progress
        )
        .returning(JobRun)
    )
    try:
        async with db.session() as session:
            return (await session.exec(statement)).scalars().first()
    except IntegrityError:  # PostgreSQL: another worker just started this job: ours waits
        return None


async def reap(db: Database, now: datetime, max_attempts: int) -> list[JobRun]:
    """Fail the runs that can never run again, so that nothing waits on them forever.

    A dead worker's last attempt (lease expired, no attempts left); and a pending run whose
    attempts already reach the retry limit, which was lowered since: it keeps its last error.
    Returns them, committed, for their outcome to be reported.
    """
    exhausted = col(JobRun.attempts) >= max_attempts
    abandoned = and_(col(JobRun.status) == JobStatus.RUNNING, col(JobRun.lease_expires_at) < now)
    failed = {"status": JobStatus.FAILED, "finished_at": now}
    async with db.session() as session:
        dead = await session.exec(
            update(JobRun)
            .where(abandoned, exhausted)
            .values(failed | {"error": "LeaseExpired", "lease_owner": None})
            .returning(JobRun)
        )
        reaped = list(dead.scalars())
        stranded = await session.exec(
            update(JobRun)
            .where(col(JobRun.status) == JobStatus.PENDING, exhausted)
            .values(failed)
            .returning(JobRun)
        )
        reaped += stranded.scalars()
    return reaped


async def _update_held(db: Database, run: JobRun, owner: str, **values: object) -> bool:
    """Update `run` only while `owner` still holds this attempt's lease."""
    async with db.session() as session:
        result = await session.exec(
            update(JobRun)
            .where(
                col(JobRun.id) == run.id,
                col(JobRun.status) == JobStatus.RUNNING,
                col(JobRun.lease_owner) == owner,
                col(JobRun.attempts) == run.attempts,
            )
            .values(**values)
        )
        return result.rowcount == 1


async def heartbeat(db: Database, run: JobRun, owner: str, until: datetime) -> bool:
    """Extend the lease; False if it was lost (another worker took the run over)."""
    return await _update_held(db, run, owner, lease_expires_at=until)


async def note_progress(db: Database, run: JobRun, owner: str, progress: JSONValue) -> bool:
    """Keep how far the attempt got, while `owner` holds its lease; False if it was lost."""
    return await _update_held(db, run, owner, progress=progress)


async def succeed(db: Database, run: JobRun, owner: str, now: datetime, result: JSONValue) -> bool:
    return await _update_held(
        db, run, owner, status=JobStatus.SUCCEEDED, result=result, finished_at=now, lease_owner=None
    )


async def fail(  # noqa: PLR0913  # what happened, and what happens next
    db: Database, run: JobRun, owner: str, now: datetime, *, error: str, retry_at: datetime | None
) -> bool:
    """Record a failed attempt: retried at `retry_at`, or failed for good without one.

    A run failed for good keeps how far its last attempt got; one waiting for a retry does not.
    """
    outcome: dict[str, object] = (
        {"status": JobStatus.PENDING, "run_after": retry_at, "progress": None}
        if retry_at
        else {"status": JobStatus.FAILED, "finished_at": now}
    )
    return await _update_held(db, run, owner, error=error, lease_owner=None, **outcome)


async def release(db: Database, run: JobRun, owner: str, now: datetime) -> bool:
    """Hand an interrupted run back (shutdown): due at once, and the attempt does not count."""
    return await _update_held(
        db,
        run,
        owner,
        status=JobStatus.PENDING,
        run_after=now,
        attempts=run.attempts - 1,
        lease_owner=None,
        lease_expires_at=None,
        progress=None,  # nothing underway until the next attempt
    )
