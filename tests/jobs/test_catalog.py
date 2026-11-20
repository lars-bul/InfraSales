import io
import json
from functools import partial
from typing import cast

import pytest
from pydantic import SecretStr

from infrasales.alerts.notifier import Alerting
from infrasales.alerts.settings import AlertSettings
from infrasales.config.schemas import ConfigKey
from infrasales.core.db import Database
from infrasales.core.logs import configure_logging
from infrasales.core.models import JSONValue
from infrasales.fetch.pacing import run_budget
from infrasales.jobs.catalog import catalog
from infrasales.jobs.forecast import ZONE
from infrasales.jobs.names import JobName
from infrasales.scheduler.models import JobStatus
from infrasales.scheduler.settings import SchedulerSettings
from infrasales.scheduler.worker import Worker
from infrasales.settings import WorkerSettings
from infrasales.sink.settings import SinkSettings
from tests.scheduler.support import FAST, Clock, stored_runs
from tests.scrape.support import disable_all_feeds

IN_MEMORY = SecretStr("sqlite+aiosqlite://")


def test_source_collection_and_the_forecast_run_on_their_schedules() -> None:
    registry = catalog(
        WorkerSettings(database_url=IN_MEMORY), Database(IN_MEMORY.get_secret_value())
    )

    assert {name: (job.schedule, job.then) for name, job in registry.items()} == {
        JobName.SCRAPE: (ConfigKey.SCRAPE_SCHEDULE, ()),
        JobName.FORECAST: (ConfigKey.FORECAST_SCHEDULE, ()),
    }


def test_the_scrape_runs_for_a_time_of_its_own_and_spends_two_thirds_on_requests() -> None:
    """Its pauses between requests to a site take longer than any other job needs."""
    settings = WorkerSettings(database_url=IN_MEMORY)
    registry = catalog(settings, Database(IN_MEMORY.get_secret_value()))
    scrape = registry[JobName.SCRAPE]

    budget = cast("partial[JSONValue]", scrape.run).keywords["budget"]
    assert scrape.timeout_seconds == settings.scheduler.scrape_timeout_seconds
    assert budget == run_budget(settings.scheduler.scrape_timeout_seconds)


def test_by_default_a_scrape_reads_for_half_an_hour_and_ends_before_the_next() -> None:
    """Measured: ~3 s a document, 300 to 600 listed per run; 10 minutes left 400 unread."""
    scheduler = SchedulerSettings()
    every = ConfigKey.SCRAPE_SCHEDULE.default.every_hours

    assert run_budget(scheduler.scrape_timeout_seconds) >= 30 * 60
    assert every is not None
    assert scheduler.scrape_timeout_seconds < every * 3600


def test_every_jobs_failures_are_told_as_configured() -> None:
    webhook = AlertSettings(webhook_url=SecretStr("https://hooks.test/T"))
    db = Database(IN_MEMORY.get_secret_value())

    quiet = catalog(WorkerSettings(database_url=IN_MEMORY), db)
    told = catalog(WorkerSettings(database_url=IN_MEMORY, alerts=webhook), db)

    assert {job.notifier for job in quiet.values()} == {None}  # nobody configured: logs only
    (notifier,) = {job.notifier for job in told.values()}  # one for all jobs
    assert isinstance(notifier, Alerting)


@pytest.mark.anyio
async def test_due_jobs_run_end_to_end(database_url: str) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    db = Database(database_url)
    await disable_all_feeds(db)  # no requests to the real Feeds from tests
    sink = SinkSettings(uri="memory://catalog-test")
    settings = WorkerSettings(database_url=SecretStr(database_url), sink=sink)
    scheduler = Worker(db, catalog(settings, db), FAST, Clock())  # a week on: it is due

    while await scheduler.tick():
        pass

    done = await stored_runs(db)
    results = {run.job: (run.status, run.result) for run in done}
    await db.dispose()
    (forecast,) = [run for run in done if run.job == JobName.FORECAST]
    as_of = forecast.scheduled_for.astimezone(ZONE).date().isoformat()  # the Berlin day
    assert results == {
        "scrape": (
            JobStatus.SUCCEEDED,
            {
                "feeds_read": 0,
                "versions_new": 0,
                "versions_unchanged": 0,
                "documents_failed": 0,
                "failed_feeds": [],
                "out_of_time": [],
                "feeds": [],
            },
        ),
        "forecast": (
            JobStatus.SUCCEEDED,
            {"model": "heuristic-1", "as_of": as_of, "municipalities": 0},
        ),
    }
    events = [json.loads(line)["event"] for line in stream.getvalue().splitlines()]
    assert "job.failed" not in events
