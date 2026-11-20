import pytest

from infrasales.core.db import Database
from infrasales.mail.ledger import Ledger
from infrasales.scheduler.steps import Steps
from tests.scheduler.support import queued_run

pytestmark = pytest.mark.anyio


async def test_a_runs_steps_keep_the_mailers_notes(database_url: str) -> None:
    db = Database(database_url)
    ledger: Ledger = Steps(db, await queued_run(db))  # what jobs hand the mailer

    await ledger.record("report-1 3f2a")
    noted = await ledger.recorded("report-1 ")
    await db.dispose()

    assert noted == {"report-1 3f2a"}
