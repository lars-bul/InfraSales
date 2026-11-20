"""A job's run summary: how many runs succeeded and failed lately, and per day."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx2
import pytest

from infrasales.core.db import Database
from infrasales.core.models import utcnow
from infrasales.scheduler.models import JobRun, JobStatus
from tests.helpers import sign_in

pytestmark = pytest.mark.anyio
BERLIN = {"timezone": "Europe/Berlin"}


async def _store(database_url: str, job: str, *runs: tuple[JobStatus, datetime | None]) -> None:
    """Runs of `job` with these statuses, finished at these times (None: not finished)."""
    db = Database(database_url)
    async with db.session() as session:
        for status, finished in runs:
            at = (finished or utcnow()) - timedelta(minutes=5)
            session.add(
                JobRun(job=job, scheduled_for=at, run_after=at, status=status, finished_at=finished)
            )
    await db.dispose()


async def test_admins_count_the_runs_that_finished_in_the_last_day_and_week(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    now, minute = utcnow(), timedelta(minutes=1)
    day, week = timedelta(days=1), timedelta(days=7)
    await _store(
        database_url,
        "scrape",
        (JobStatus.SUCCEEDED, now - minute),
        (JobStatus.FAILED, now - day + minute),  # just inside the day
        (JobStatus.SUCCEEDED, now - day - minute),  # just outside the day, inside the week
        (JobStatus.FAILED, now - week + minute),  # just inside the week
        (JobStatus.SUCCEEDED, now - week - minute),  # just outside the week
        (JobStatus.PENDING, None),  # not finished: neither
        (JobStatus.RUNNING, None),
    )
    await _store(database_url, "retired", (JobStatus.FAILED, now - minute))  # another job
    await sign_in(client, "alice")

    response = await client.get("/api/jobs/scrape/runs/summary", params=BERLIN)

    assert response.status_code == 200
    summary = response.json()
    assert summary["last_24h"] == {"succeeded": 1, "failed": 1}
    assert summary["last_7d"] == {"succeeded": 2, "failed": 2}


async def test_a_failure_that_is_retried_does_not_count_as_failed(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    """Only a run's final status counts: a run waiting for its retry is not finished."""
    db = Database(database_url)
    async with db.session() as session:
        at = utcnow() - timedelta(minutes=5)
        retried = JobRun(job="scrape", scheduled_for=at, run_after=at, attempts=1, error="Boom")
        session.add(retried)  # failed once, pending its retry
    await db.dispose()
    await sign_in(client, "alice")

    summary = (await client.get("/api/jobs/scrape/runs/summary", params=BERLIN)).json()

    assert summary["last_24h"] == {"succeeded": 0, "failed": 0}


def _late_evening(days_ago: int) -> datetime:
    """23:30 UTC that many days ago: already the next day in Berlin (00:30 or 01:30)."""
    day = datetime.now(UTC).date() - timedelta(days=days_ago)
    return datetime.combine(day, time(23, 30), tzinfo=UTC)


async def test_daily_buckets_fall_on_the_calendar_days_of_the_time_zone_asked_for(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    finished = _late_evening(3)
    await _store(database_url, "scrape", (JobStatus.SUCCEEDED, finished))
    await _store(database_url, "scrape", (JobStatus.FAILED, finished - timedelta(hours=12)))
    await sign_in(client, "alice")

    in_berlin = (await client.get("/api/jobs/scrape/runs/summary", params=BERLIN)).json()
    in_utc = await client.get("/api/jobs/scrape/runs/summary", params={"timezone": "UTC"})

    berlin_days = {date.fromisoformat(d["day"]): d for d in in_berlin["days"]}
    utc_days = {date.fromisoformat(d["day"]): d for d in in_utc.json()["days"]}
    that_day = finished.date()
    assert utc_days[that_day] | {"day": None} == {"day": None, "succeeded": 1, "failed": 1}
    assert berlin_days[that_day] | {"day": None} == {"day": None, "succeeded": 0, "failed": 1}
    next_day = berlin_days[that_day + timedelta(days=1)]
    assert (next_day["succeeded"], next_day["failed"]) == (1, 0)


async def test_there_are_seven_days_ending_today_oldest_first(client: httpx2.AsyncClient) -> None:
    tokyo = ZoneInfo("Asia/Tokyo")
    await sign_in(client, "alice")
    before = datetime.now(tokyo).date()

    days = await client.get("/api/jobs/scrape/runs/summary", params={"timezone": "Asia/Tokyo"})
    after = datetime.now(tokyo).date()

    dates = [date.fromisoformat(d["day"]) for d in days.json()["days"]]
    assert dates[-1] in {before, after}  # unless midnight passed in between, both are today
    assert dates == [dates[-1] - timedelta(days=n) for n in range(6, -1, -1)]
    assert {(d["succeeded"], d["failed"]) for d in days.json()["days"]} == {(0, 0)}


@pytest.mark.parametrize(("user", "status"), [(None, 401), ("vera", 403)])
async def test_only_admins_read_the_summary(
    client: httpx2.AsyncClient, user: str | None, status: int
) -> None:
    if user:
        await sign_in(client, user)

    response = await client.get("/api/jobs/scrape/runs/summary", params=BERLIN)

    assert response.status_code == status


@pytest.mark.parametrize(
    ("job", "params"),
    [
        ("backup", BERLIN),  # no such job
        ("scrape", {"timezone": "Europe/Atlantis"}),  # no such time zone
        ("scrape", {"timezone": "../etc/passwd"}),
        ("scrape", {}),  # no time zone at all
    ],
)
async def test_an_unknown_job_or_time_zone_is_rejected(
    client: httpx2.AsyncClient, job: str, params: dict[str, str]
) -> None:
    await sign_in(client, "alice")

    response = await client.get(f"/api/jobs/{job}/runs/summary", params=params)

    assert response.status_code == 422
