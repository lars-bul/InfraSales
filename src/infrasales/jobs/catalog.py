"""Every job the scheduler knows, with its dependencies bound.

To add a job: a module in `infrasales/jobs/`, its name in `names.py`, a line here, and (if
scheduled) a `ConfigKey` with a default schedule (`infrasales/config/schemas.py`); a job without
one runs when triggered: "Run now", or after another job's run (`then`). The jobs that read what
Source Collection stores (ADR 06 §5) follow it with `then`.
"""

from functools import partial

from infrasales.alerts.notifier import build_notifier
from infrasales.config.schemas import ConfigKey
from infrasales.core.db import Database
from infrasales.fetch.pacing import run_budget
from infrasales.fetch.robots import RobotsCache
from infrasales.jobs.forecast import forecast_job
from infrasales.jobs.names import JobName
from infrasales.jobs.scrape import scrape_job
from infrasales.scheduler.registry import Registry, ScheduledJob
from infrasales.settings import WorkerSettings
from infrasales.sink.store import Sink


def catalog(settings: WorkerSettings, db: Database) -> Registry:
    """The jobs, with what they need: settings, and the database the worker uses."""
    alerts = build_notifier(settings.alerts, settings.smtp)  # told when a run fails
    sink = Sink(settings.sink.uri)
    scrape_timeout = settings.scheduler.scrape_timeout_seconds  # its pauses take the longest
    return {
        JobName.SCRAPE: ScheduledJob(
            run=partial(
                scrape_job,
                db=db,
                sink=sink,
                notifier=alerts,  # told about blocked Feeds too
                budget=run_budget(scrape_timeout),  # pauses stay in time
                robots=RobotsCache(),  # a day, across runs
            ),
            schedule=ConfigKey.SCRAPE_SCHEDULE,
            notifier=alerts,
            timeout_seconds=scrape_timeout,
        ),
        JobName.FORECAST: ScheduledJob(
            run=partial(forecast_job, db=db),
            schedule=ConfigKey.FORECAST_SCHEDULE,
            notifier=alerts,
        ),
    }
