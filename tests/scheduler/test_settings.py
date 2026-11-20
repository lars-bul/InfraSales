import pytest
from pydantic import ValidationError

from infrasales.scheduler.settings import SchedulerSettings


def test_defaults_run_the_worker_in_process_with_three_attempts() -> None:
    settings = SchedulerSettings()

    assert settings.enabled
    assert (settings.max_attempts, settings.poll_seconds, settings.lease_seconds) == (3, 30, 60)


def test_nonsensical_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SchedulerSettings(max_attempts=0)


def test_a_job_is_stopped_a_quarter_lease_before_its_run_can_change_workers() -> None:
    assert SchedulerSettings(lease_seconds=60).stop_margin_seconds == 15
