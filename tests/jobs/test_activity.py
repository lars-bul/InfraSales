"""The run activity: how the runs listed ended over time, per hour or per calendar day."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx2
import pytest

from infrasales.core.db import Database
from infrasales.core.models import utcnow
from infrasales.scheduler.models import JobRun, JobStatus, RunTrigger
from tests.helpers import sign_in

pytestmark = pytest.mark.anyio
ACTIVITY = "/api/jobs/runs/activity"
BERLIN = ZoneInfo("Europe/Berlin")


async def _store(database_url: str, *runs: tuple[str, JobStatus, datetime]) -> None:
    """Runs of these jobs with these statuses, scheduled at these times, by the schedule."""
    db = Database(database_url)
    async with db.session() as session:
        for job, status, at in runs:
            finished = at if status in {JobStatus.SUCCEEDED, JobStatus.FAILED} else None
            session.add(
                JobRun(job=job, scheduled_for=at, run_after=at, status=status, finished_at=finished)
            )
    await db.dispose()


def _counts(activity: dict[str, list[dict[str, int | str]]]) -> list[tuple[int, int]]:
    return [(int(b["succeeded"]), int(b["failed"])) for b in activity["buckets"]]


async def test_up_to_two_days_are_counted_per_hour(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    start = datetime(2026, 7, 20, 10, tzinfo=BERLIN)
    await _store(
        database_url,
        ("scrape", JobStatus.SUCCEEDED, start),  # at the start: in the first hour
        ("scrape", JobStatus.FAILED, start + timedelta(minutes=59)),
        ("retired", JobStatus.SUCCEEDED, start + timedelta(hours=2, minutes=30)),
        ("scrape", JobStatus.RUNNING, start + timedelta(hours=2)),  # not ended: neither
        ("scrape", JobStatus.SUCCEEDED, start + timedelta(hours=3)),  # at the end: outside
        ("scrape", JobStatus.SUCCEEDED, start - timedelta(seconds=1)),  # before the start
    )
    await sign_in(client, "alice")
    params = {
        "start": start.isoformat(),
        "end": (start + timedelta(hours=3)).isoformat(),
        "timezone": "Europe/Berlin",
    }

    activity = (await client.get(ACTIVITY, params=params)).json()

    assert activity["unit"] == "hour"
    starts = [datetime.fromisoformat(b["start"]) for b in activity["buckets"]]
    assert starts == [start + timedelta(hours=n) for n in range(3)]
    assert _counts(activity) == [(1, 1), (0, 0), (1, 0)]


async def test_longer_is_counted_per_calendar_day_of_the_time_zone(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    start = datetime(2026, 7, 20, 12, tzinfo=BERLIN)
    late = datetime(2026, 7, 21, 23, 30, tzinfo=UTC)  # already the 22nd in Berlin
    await _store(database_url, ("scrape", JobStatus.FAILED, late))
    await sign_in(client, "alice")
    params = {
        "start": start.isoformat(),
        "end": datetime(2026, 7, 23, 12, tzinfo=BERLIN).isoformat(),
        "timezone": "Europe/Berlin",
    }

    activity = (await client.get(ACTIVITY, params=params)).json()

    assert activity["unit"] == "day"
    starts = [datetime.fromisoformat(b["start"]) for b in activity["buckets"]]
    assert starts == [
        datetime.combine(date(2026, 7, d), time(), tzinfo=BERLIN) for d in (20, 21, 22, 23)
    ]
    assert _counts(activity) == [(0, 0), (0, 0), (0, 1), (0, 0)]


async def test_without_a_range_the_last_seven_calendar_days_are_counted(
    client: httpx2.AsyncClient,
) -> None:
    tokyo = ZoneInfo("Asia/Tokyo")
    await sign_in(client, "alice")
    before = datetime.now(tokyo).date()

    activity = (await client.get(ACTIVITY, params={"timezone": "Asia/Tokyo"})).json()

    days = [
        datetime.fromisoformat(b["start"]).astimezone(tokyo).date() for b in activity["buckets"]
    ]
    assert days[-1] in {before, before + timedelta(days=1)}  # unless midnight passed in between
    assert days == [days[-1] - timedelta(days=n) for n in range(6, -1, -1)]
    assert datetime.fromisoformat(activity["start"]) == datetime.combine(
        days[0], time(), tzinfo=tokyo
    )


async def test_the_filters_of_the_list_narrow_the_activity(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    at = utcnow() - timedelta(hours=1)
    await _store(
        database_url,
        ("scrape", JobStatus.SUCCEEDED, at),
        ("scrape", JobStatus.FAILED, at - timedelta(minutes=1)),
        ("retired", JobStatus.FAILED, at - timedelta(minutes=2)),
    )
    await sign_in(client, "alice")
    utc = {"timezone": "UTC"}

    def total(activity: dict[str, list[dict[str, int | str]]]) -> tuple[int, int]:
        counts = _counts(activity)
        return sum(s for s, _ in counts), sum(f for _, f in counts)

    every = (await client.get(ACTIVITY, params=utc)).json()
    scrape = (await client.get(ACTIVITY, params=utc | {"job": "scrape"})).json()
    failed = (await client.get(ACTIVITY, params=utc | {"status": "failed"})).json()
    manual = (await client.get(ACTIVITY, params=utc | {"trigger": RunTrigger.MANUAL})).json()

    assert (total(every), total(scrape)) == ((1, 2), (1, 1))
    assert (total(failed), total(manual)) == ((0, 2), (0, 0))


@pytest.mark.parametrize(
    ("user", "params", "status"),
    [
        (None, {"timezone": "UTC"}, 401),
        ("vera", {"timezone": "UTC"}, 403),
        ("alice", {}, 422),  # no time zone
        ("alice", {"timezone": "UTC", "job": "weather"}, 422),
        (
            "alice",
            {"timezone": "UTC", "start": "2026-07-22T10:00Z", "end": "2026-07-20T10:00Z"},
            422,
        ),
        (
            "alice",
            {"timezone": "UTC", "start": "2025-01-01T00:00Z", "end": "2026-07-20T00:00Z"},
            422,
        ),
        ("alice", {"timezone": "UTC", "start": "2999-01-01T00:00Z"}, 422),  # after now
    ],
)
async def test_the_activity_is_for_admins_over_a_year_at_most(
    client: httpx2.AsyncClient, user: str | None, params: dict[str, str], status: int
) -> None:
    if user:
        await sign_in(client, user)

    response = await client.get(ACTIVITY, params=params)

    assert response.status_code == status
