from infrasales.core.models import utcnow
from infrasales.scheduler.models import JobRun
from infrasales.scheduler.schemas import JobRunRead


def test_runs_are_read_without_their_lease_details_or_who_triggered_them() -> None:
    run = JobRun(
        job="scrape",
        scheduled_for=utcnow(),
        run_after=utcnow(),
        lease_owner="w",
        triggered_by="basic:alice",
    )

    read = JobRunRead.model_validate(run, from_attributes=True)

    assert read.model_dump().keys() == {
        "id",
        "job",
        "trigger",
        "status",
        "scheduled_for",
        "attempts",
        "finished_at",
        "error",
    }
