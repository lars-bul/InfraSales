import pytest
from pydantic import ValidationError

from infrasales.config.schemas import Schedule, Weekday


def test_days_are_deduplicated_into_week_order() -> None:
    schedule = Schedule(
        days=[Weekday.SUN, Weekday.MON, Weekday.SUN], time="08:00", timezone="Europe/Berlin"
    )

    assert schedule.days == [Weekday.MON, Weekday.SUN]
    assert schedule.enabled


@pytest.mark.parametrize(
    "invalid",
    [
        {"days": []},
        {"time": "24:00"},
        {"time": "8:00"},
        {"timezone": "Mars/Olympus_Mons"},
        {"timezone": "../etc/passwd"},
        {"every_hours": 0},
        {"every_hours": 5},  # does not divide a day: the pace would break at midnight
        {"every_hours": 24},
        {"every_hours": "3h"},
    ],
)
def test_invalid_schedules_are_rejected(invalid: dict[str, object]) -> None:
    valid: dict[str, object] = {"days": ["mon"], "time": "08:00", "timezone": "Europe/Berlin"}

    with pytest.raises(ValidationError):
        Schedule.model_validate(valid | invalid)


def test_a_schedule_stored_before_repetitions_existed_runs_once_a_day() -> None:
    stored = {"days": ["mon"], "time": "08:00", "timezone": "Europe/Berlin", "enabled": True}

    assert Schedule.model_validate(stored).every_hours is None
