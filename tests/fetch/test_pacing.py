"""The pacer's own contract; pauses and the run's budget are tested through the scrape job."""

import pytest

from infrasales.fetch.pacing import REAL_TIME, Budget, Pacer, run_budget

pytestmark = pytest.mark.anyio


def test_a_run_may_spend_two_thirds_of_the_job_timeout_on_requests() -> None:
    assert run_budget(900) == 600


async def test_without_a_budget_nothing_runs_out_of_time() -> None:
    budget = Budget.unlimited()
    budget.next_feed()
    pacer = Pacer(REAL_TIME, budget, pause=0)

    await pacer.wait("news.test", delay=None)
    pacer.done("news.test")
    await pacer.wait("news.test", delay=0.001)  # real time: a millisecond

    assert budget.deadline is None
