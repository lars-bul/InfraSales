import uuid
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from infrasales.core.models import JSONValue
from infrasales.scheduler.registry import JobContext, ScheduledJob
from tests.alerts.support import FAILED, RUN
from tests.scheduler.support import context_for


async def _job(_: JobContext) -> JSONValue:
    return None


def test_jobs_are_triggered_only_unless_they_name_a_schedule() -> None:
    assert ScheduledJob(run=_job).schedule is None


def test_the_context_cannot_be_changed_by_a_job() -> None:
    context = context_for()

    with pytest.raises(FrozenInstanceError):
        context.run_id = uuid.uuid7()  # pyright: ignore[reportAttributeAccessIssue]


def test_an_alert_says_what_failed_and_where_to_look_into_it() -> None:
    retry_at = datetime(2026, 10, 3, 18, 5, tzinfo=UTC)
    retrying = replace(FAILED, outcome="retrying", attempt=2, retry_at=retry_at, langfuse_url=None)

    assert FAILED.subject() == "infrasales: report failed"
    assert FAILED.text() == (
        "The job report failed for good: attempt 3 of 3 raised TimeoutError.\n"
        f"Run: {RUN}\n"
        f"Langfuse: https://langfuse.test/project/p1/sessions/{RUN}"
    )
    assert retrying.subject() == "infrasales: report keeps failing"
    assert retrying.text() == (
        "The job report keeps failing: attempt 2 of 3 raised TimeoutError;"
        " it is retried at 2026-10-03 18:05 UTC.\n"
        f"Run: {RUN}"
    )
