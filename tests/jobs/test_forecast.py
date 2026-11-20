from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
from sqlmodel import select

from infrasales.core.db import Database
from infrasales.forecast import heuristic
from infrasales.forecast.features import History
from infrasales.forecast.models import Prediction
from infrasales.jobs.forecast import forecast_job
from infrasales.projects.models import SignalKind
from infrasales.scheduler.registry import JobContext
from infrasales.scheduler.steps import Steps
from tests.forecast.support import HEIDELBERG, ULM, signal, store
from tests.scheduler.support import RecordedTrace, queued_run

pytestmark = pytest.mark.anyio

# Late on Sunday in UTC is Monday in Berlin: the day the scores are for.
SCHEDULED = datetime(2026, 1, 4, 23, 30, tzinfo=UTC)


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    funding = signal(SignalKind.FUNDING_GRANTED, date(2025, 9, 1))
    await store(db, History.of([HEIDELBERG, ULM], signals=[(HEIDELBERG.ags, funding)]))
    yield db
    await db.dispose()


async def test_the_job_scores_every_municipality_for_the_berlin_day(db: Database) -> None:
    run_id = await queued_run(db, "forecast")
    trace = RecordedTrace()
    context = JobContext(run_id, SCHEDULED, Steps(db, run_id), trace)

    result = await forecast_job(context, db=db)

    async with db.session() as session:
        stored = (await session.exec(select(Prediction))).all()
    assert result == {"model": heuristic.VERSION, "as_of": "2026-01-05", "municipalities": 2}
    assert {(p.municipality_ags, p.as_of, p.run_id) for p in stored} == {
        (HEIDELBERG.ags, date(2026, 1, 5), run_id),
        (ULM.ags, date(2026, 1, 5), run_id),
    }
    assert [step.name for step in trace.steps] == ["history", "predict"]
    assert trace.steps[1].results == [2]


async def test_running_again_on_the_same_day_replaces_the_scores(db: Database) -> None:
    first, second = await queued_run(db, "forecast"), await queued_run(db, "forecast")

    await forecast_job(JobContext(first, SCHEDULED, Steps(db, first)), db=db)
    await forecast_job(JobContext(second, SCHEDULED, Steps(db, second)), db=db)

    async with db.session() as session:
        stored = (await session.exec(select(Prediction))).all()
    assert {p.run_id for p in stored} == {second}
