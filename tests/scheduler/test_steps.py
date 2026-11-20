from collections.abc import AsyncIterator

import pytest

from infrasales.core.db import Database
from infrasales.scheduler.steps import StepResultError, Steps
from tests.scheduler.support import queued_run

pytestmark = pytest.mark.anyio


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    yield db
    await db.dispose()


async def test_a_step_runs_once_and_later_attempts_reuse_its_result(db: Database) -> None:
    run_id, calls = await queued_run(db), list[str]()

    async def write() -> str:
        calls.append("write")
        return "Hello world"

    first = await Steps(db, run_id).once("write", write, returns=str)
    retry = await Steps(db, run_id).once("write", write, returns=str)  # the run's next attempt

    assert (first, retry, calls) == ("Hello world", "Hello world", ["write"])


async def test_overlapping_attempts_keep_the_first_result(db: Database) -> None:
    steps = Steps(db, await queued_run(db))

    first = await steps.record("write", {"text": "first"})
    second = await steps.record("write", {"text": "second"})

    assert first == second == {"text": "first"}


async def test_recorded_steps_are_found_by_prefix_literally(db: Database) -> None:
    steps = Steps(db, await queued_run(db))
    for name in ("mail a_1", "mail ab1", "write"):
        await steps.record(name)

    assert await steps.recorded("mail a_") == {"mail a_1"}  # "_" is no wildcard
    assert await steps.recorded("mail ") == {"mail a_1", "mail ab1"}


async def test_steps_belong_to_their_run(db: Database) -> None:
    mine, other = Steps(db, await queued_run(db)), Steps(db, await queued_run(db))
    await other.record("write", "theirs")

    assert await mine.recorded("") == frozenset()
    assert await mine.once("write", _mine, returns=str) == "mine"


async def _mine() -> str:
    return "mine"


async def test_results_come_back_as_the_type_they_were(db: Database) -> None:
    steps = Steps(db, await queued_run(db))

    async def scraped() -> tuple[str, ...]:
        return ("Hello", "world")

    first = await steps.once("scrape", scraped, returns=tuple[str, ...])
    again = await steps.once("scrape", scraped, returns=tuple[str, ...])

    assert first == again == ("Hello", "world")  # a tuple again, not JSON's list


async def test_a_result_of_another_shape_is_refused_clearly(db: Database) -> None:
    """A job changed what a step returns while a run was pending: the step needs a new name."""
    steps = Steps(db, await queued_run(db))
    await steps.record("write", {"text": "written by the previous version"})

    with pytest.raises(StepResultError, match="'write' holds a result that is no <class 'str'>"):
        await steps.once("write", _mine, returns=str)
