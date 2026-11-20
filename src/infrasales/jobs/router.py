from datetime import timedelta
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request, status

from infrasales.audit import service as audit
from infrasales.auth.deps import AdminUser
from infrasales.core.db import Session
from infrasales.core.models import utcnow
from infrasales.jobs import overlap
from infrasales.jobs.names import JobName
from infrasales.jobs.overlap import FeedOverlapReport, OverlapQuery
from infrasales.jobs.schemas import (
    JobRunsQuery,
    JobsActivityQuery,
    RunHistoryEntry,
    RunProgress,
    typed_progress,
    typed_result,
)
from infrasales.observability import TELEMETRY
from infrasales.scheduler import runs
from infrasales.scheduler.models import JobRun
from infrasales.scheduler.schemas import (
    JobRunRead,
    RunActivity,
    RunQuery,
    RunSummary,
    SummaryQuery,
)
from infrasales.scheduler.settings import SCHEDULER
from infrasales.scheduler.worker import WORKER

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
# What the Source Collection runs tell about the Feeds: read from runs, so it is the jobs' to say.
feeds_router = APIRouter(prefix="/api/feeds", tags=["feeds"])

# The longest time the run activity is counted over: a year of days, a bar each.
_ACTIVITY_SPAN = timedelta(days=366)


@router.get("/runs")
async def list_job_runs(
    query: Annotated[JobRunsQuery, Query()], _: AdminUser, session: Session, request: Request
) -> list[RunHistoryEntry]:
    """Every job's runs, newest first (admins only): of one job, status or trigger if asked.

    A full page means older runs may follow: ask again with `before` the last one's ID.
    """
    page = await runs.recent(session, query.job, query)
    return [_entry(run.job, run, request) for run in page]


@router.get(
    "/runs/activity",
    responses={422: {"description": "A start after the end, or more than a year between"}},
)
async def read_run_activity(
    query: Annotated[JobsActivityQuery, Query()], _: AdminUser, session: Session
) -> RunActivity:
    """How the runs listed ended over time (admins only): for the Job runs chart.

    The runs the same filters list, scheduled from `start` until `end` (default: the last 7
    calendar days, today included), counted per hour for up to 2 days, else per calendar day,
    in `timezone` (the client's, an IANA name). Only runs that ended count; "failed" means
    failed for good.
    """
    zone = ZoneInfo(query.timezone)
    start, end = runs.activity_window(query, utcnow(), zone)
    if not start < end <= start + _ACTIVITY_SPAN:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The start must be before the end, at most a year",
        )
    return await runs.activity(session, query.job, query, start=start, end=end, zone=zone)


@router.post("/{job}/runs", status_code=status.HTTP_202_ACCEPTED)
async def run_now(  # noqa: PLR0913  # the job, who asks, and how the request is repeated
    job: JobName,
    *,
    idempotency_key: Annotated[UUID | None, Header(description="A UUID per click")] = None,
    admin: AdminUser,
    session: Session,
    request: Request,
    tasks: BackgroundTasks,
) -> RunProgress:
    """Queue a run of `job` now (admins only). It runs like a scheduled one: leased, retried.

    One manual run per job at a time: while one is queued or running, it is returned. Sent
    with an `Idempotency-Key` (a UUID per click), the request can be repeated, e.g. after its
    answer was lost: it gets the same run, even once that run has finished.
    """
    run, queued = await runs.enqueue(
        session, job, utcnow(), triggered_by=admin.subject, key=idempotency_key
    )
    if queued:
        audit.record(
            session, actor=admin.subject, action="job.triggered", target=job, request=request
        )
        if worker := WORKER.find(request):
            tasks.add_task(worker.wake)  # after the commit, so the worker finds the run
    return _progress(run, request)


@router.get("/{job}/runs")
async def list_runs(
    job: JobName,
    query: Annotated[RunQuery, Query()],
    _: AdminUser,
    session: Session,
    request: Request,
) -> list[RunHistoryEntry]:
    """The job's runs, newest first (admins only): failures, retries, who ran when.

    A full page means older runs may follow: ask again with `before` the last one's ID.
    """
    page = await runs.recent(session, job, query)
    return [_entry(job, run, request) for run in page]


@router.get("/{job}/runs/active")  # before /{run_id}: "active" is no run ID
async def read_active_run(
    job: JobName, _: AdminUser, session: Session, request: Request
) -> RunProgress | None:
    """The job's run under way, scheduled or manual, if any: the job's page follows it."""
    run = await runs.active(session, job)
    return None if run is None else _progress(run, request)


@router.get("/{job}/runs/summary")  # before /{run_id}: "summary" is no run ID
async def read_run_summary(
    job: JobName, query: Annotated[SummaryQuery, Query()], _: AdminUser, session: Session
) -> RunSummary:
    """How the job's runs ended lately (admins only): for the run health tiles and overview.

    Counts for the last 24 hours, the last 7 days, and each of the last 7 calendar days in
    `timezone` (the client's, an IANA name).

    Runs count by when they finished. "Failed" means failed for good: a run waiting for its
    retry has not finished yet.
    """
    return await runs.summary(session, job, utcnow(), ZoneInfo(query.timezone))


@router.get("/{job}/runs/{run_id}", responses={404: {"description": "No such run"}})
async def read_run(
    job: JobName, run_id: UUID, _: AdminUser, session: Session, request: Request
) -> RunProgress:
    """A run's progress (admins only), e.g. of one they queued."""
    run = await runs.find(session, job, run_id)
    if run is None:
        raise HTTPException(404, "No such run")
    return _progress(run, request)


def _progress(run: JobRun, request: Request) -> RunProgress:
    """The run and how far it got, linked to its session in Langfuse when the app traces there."""
    telemetry = TELEMETRY.find(request)
    url = telemetry.session_url(str(run.id)) if telemetry else None
    read = JobRunRead.model_validate(run, from_attributes=True)
    limit = SCHEDULER.get(request).max_attempts
    return RunProgress(
        **read.model_dump(),
        langfuse_url=url,
        max_attempts=limit,
        progress=typed_progress(run.job, run.progress),
    )


def _entry(job: str, run: JobRun, request: Request) -> RunHistoryEntry:
    """The run as the run history lists it, linked to Langfuse like its progress."""
    return RunHistoryEntry.model_validate(
        _progress(run, request).model_dump()
        | {"triggered_by": run.triggered_by, "result": typed_result(job, run.result)}
    )


@feeds_router.get("/overlap")
async def read_feed_overlap(
    query: Annotated[OverlapQuery, Query()], _: AdminUser, session: Session
) -> FeedOverlapReport:
    """Which Feeds list the same documents (admins only): each Feed's own share, the top pairs.

    Summed over the Source Collection runs that finished in the last `days` days (at most the
    newest 1000), in listings: an address counts once in each run that lists it.
    """
    return await overlap.report(session, utcnow(), query.days)
