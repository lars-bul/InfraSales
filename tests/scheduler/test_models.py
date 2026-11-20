import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from infrasales.core.db import Database
from infrasales.core.models import utcnow
from infrasales.scheduler.models import JobRun, JobStatus, JobStep
from infrasales.scheduler.steps import Steps
from tests.scheduler.support import queued_run

pytestmark = pytest.mark.anyio


async def _add_twice(db: Database) -> None:
    due = utcnow()
    async with db.session() as session:
        session.add(JobRun(job="scrape", scheduled_for=due, run_after=due))
        session.add(JobRun(job="scrape", scheduled_for=due, run_after=due))


async def test_a_job_runs_once_per_scheduled_time(database_url: str) -> None:
    db = Database(database_url)
    try:
        with pytest.raises(IntegrityError, match=r"(?i)unique"):  # SQLite and PostgreSQL
            await _add_twice(db)
    finally:
        await db.dispose()


def test_new_runs_are_pending_without_attempts() -> None:
    run = JobRun(job="scrape", scheduled_for=utcnow(), run_after=utcnow())

    assert (run.status, run.attempts, run.result) == (JobStatus.PENDING, 0, None)


async def test_a_runs_steps_are_deleted_with_it(database_url: str) -> None:
    db = Database(database_url)
    run_id = await queued_run(db)
    await Steps(db, run_id).record("write", "Hello world")

    async with db.session() as session:
        await session.delete(await session.get_one(JobRun, run_id))
    async with db.session() as session:
        steps = (await session.exec(select(JobStep))).all()
    await db.dispose()

    assert steps == []
