from datetime import UTC, datetime

import pytest

from infrasales.config.schemas import Schedule, Weekday
from infrasales.scheduler.recurrence import latest_occurrence, next_occurrence

EVERY_DAY = list(Weekday)
MON_WED_FRI = [Weekday.MON, Weekday.WED, Weekday.FRI]


def _at(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


@pytest.mark.parametrize(
    ("days", "time", "timezone", "now", "expected"),
    [
        # Mondays 08:00 in Berlin (CEST, UTC+2), asked on a Wednesday
        ([Weekday.MON], "08:00", "Europe/Berlin", _at(2026, 9, 30, 10), _at(2026, 9, 28, 6)),
        # exactly at the occurrence, and a minute before it
        ([Weekday.MON], "08:00", "Europe/Berlin", _at(2026, 9, 28, 6), _at(2026, 9, 28, 6)),
        ([Weekday.MON], "08:00", "Europe/Berlin", _at(2026, 9, 28, 5, 59), _at(2026, 9, 21, 6)),
        # daily: today once the time has passed, else yesterday
        (EVERY_DAY, "06:00", "Europe/Berlin", _at(2026, 10, 2, 5), _at(2026, 10, 2, 4)),
        (EVERY_DAY, "06:00", "Europe/Berlin", _at(2026, 10, 2, 3), _at(2026, 10, 1, 4)),
        # 02:30 does not exist on 2026-03-29 (clocks jump to 03:00): it fires at 03:30 CEST
        ([Weekday.SUN], "02:30", "Europe/Berlin", _at(2026, 3, 29, 12), _at(2026, 3, 29, 1, 30)),
        # 02:30 happens twice on 2026-10-25: it fires the first time (CEST)
        ([Weekday.SUN], "02:30", "Europe/Berlin", _at(2026, 10, 25, 12), _at(2026, 10, 25, 0, 30)),
        # another zone: Fridays 17:30 in New York (EDT, UTC-4)
        ([Weekday.FRI], "17:30", "America/New_York", _at(2026, 10, 3), _at(2026, 10, 2, 21, 30)),
    ],
)
def test_the_latest_occurrence(
    days: list[Weekday], time: str, timezone: str, now: datetime, expected: datetime
) -> None:
    schedule = Schedule(days=days, time=time, timezone=timezone)

    assert latest_occurrence(schedule, now) == expected


@pytest.mark.parametrize(
    ("days", "time", "every_hours", "now", "expected"),
    [
        # every 3 hours from midnight in Berlin (CEST, UTC+2): 00:00, 03:00, ..., 21:00
        (EVERY_DAY, "00:00", 3, _at(2026, 10, 2, 8, 30), _at(2026, 10, 2, 7)),  # 10:30: 09:00
        (EVERY_DAY, "00:00", 3, _at(2026, 10, 2, 7), _at(2026, 10, 2, 7)),  # exactly at 09:00
        (EVERY_DAY, "00:00", 3, _at(2026, 10, 1, 23), _at(2026, 10, 1, 22)),  # 01:00: midnight
        (EVERY_DAY, "00:00", 3, _at(2026, 10, 1, 21), _at(2026, 10, 1, 19)),  # 23:00: 21:00
        # the repetition starts at the time and ends with the day: 06:00, 14:00, 22:00
        (EVERY_DAY, "06:00", 8, _at(2026, 10, 2, 3), _at(2026, 10, 1, 20)),  # 05:00: 22:00
        (EVERY_DAY, "06:30", 8, _at(2026, 10, 2, 13), _at(2026, 10, 2, 12, 30)),  # 15:00: 14:30
        # only on the chosen days: on a Tuesday, Monday's last occurrence (22:00 CEST)
        ([Weekday.MON], "10:00", 12, _at(2026, 9, 29, 12), _at(2026, 9, 28, 20)),
        # 02:00 does not exist on 2026-03-29: hourly fires at 03:00 CEST (01:00 UTC), once
        (EVERY_DAY, "00:00", 1, _at(2026, 3, 29, 1, 30), _at(2026, 3, 29, 1)),
        # 02:00 happens twice on 2026-10-25: hourly fires the first time, then at 03:00 CET
        (EVERY_DAY, "00:00", 1, _at(2026, 10, 25, 1, 30), _at(2026, 10, 25, 0)),
        (EVERY_DAY, "00:00", 1, _at(2026, 10, 25, 2), _at(2026, 10, 25, 2)),
    ],
)
def test_the_latest_occurrence_of_a_repeating_schedule(
    days: list[Weekday], time: str, every_hours: int, now: datetime, expected: datetime
) -> None:
    schedule = Schedule.model_validate(
        {"days": days, "time": time, "timezone": "Europe/Berlin", "every_hours": every_hours}
    )

    assert latest_occurrence(schedule, now) == expected


@pytest.mark.parametrize(
    ("days", "time", "now", "expected"),
    [
        # Mondays 08:00 in Berlin (CEST, UTC+2), asked on a Wednesday: next week's Monday
        ([Weekday.MON], "08:00", _at(2026, 9, 30, 10), _at(2026, 10, 5, 6)),
        # exactly at the occurrence: the one a week later; a minute before: this one
        ([Weekday.MON], "08:00", _at(2026, 9, 28, 6), _at(2026, 10, 5, 6)),
        ([Weekday.MON], "08:00", _at(2026, 9, 28, 5, 59), _at(2026, 9, 28, 6)),
        # daily: today until the time has passed, then tomorrow (also after local midnight)
        (EVERY_DAY, "06:00", _at(2026, 10, 2, 3), _at(2026, 10, 2, 4)),
        (EVERY_DAY, "06:00", _at(2026, 10, 2, 5), _at(2026, 10, 3, 4)),
        (EVERY_DAY, "06:00", _at(2026, 10, 2, 22, 30), _at(2026, 10, 3, 4)),  # 00:30 local
        # Mon, Wed and Fri: from Friday evening over the weekend to Monday, then to Wednesday
        (MON_WED_FRI, "07:00", _at(2026, 10, 2, 18), _at(2026, 10, 5, 5)),
        (MON_WED_FRI, "07:00", _at(2026, 10, 5, 6), _at(2026, 10, 7, 5)),
        # 02:30 does not exist on 2026-03-29 (clocks jump to 03:00): it fires at 03:30 CEST
        ([Weekday.SUN], "02:30", _at(2026, 3, 28, 12), _at(2026, 3, 29, 1, 30)),
        # 02:30 happens twice on 2026-10-25: it fires the first time (CEST)
        ([Weekday.SUN], "02:30", _at(2026, 10, 24, 12), _at(2026, 10, 25, 0, 30)),
    ],
)
def test_the_next_occurrence(
    days: list[Weekday], time: str, now: datetime, expected: datetime
) -> None:
    schedule = Schedule(days=days, time=time, timezone="Europe/Berlin")

    assert next_occurrence(schedule, now) == expected


@pytest.mark.parametrize(
    ("days", "time", "every_hours", "now", "expected"),
    [
        # every 3 hours from midnight in Berlin (CEST, UTC+2): 00:00, 03:00, ..., 21:00
        (EVERY_DAY, "00:00", 3, _at(2026, 10, 2, 8, 30), _at(2026, 10, 2, 10)),  # 10:30: 12:00
        (EVERY_DAY, "00:00", 3, _at(2026, 10, 2, 7), _at(2026, 10, 2, 10)),  # exactly at 09:00
        (EVERY_DAY, "00:00", 3, _at(2026, 10, 2, 20), _at(2026, 10, 2, 22)),  # 22:00: midnight
        # the repetition starts at the time and ends with the day: 06:00, 14:00, 22:00
        (EVERY_DAY, "06:00", 8, _at(2026, 10, 2, 20, 30), _at(2026, 10, 3, 4)),  # 22:30: 06:00
        (EVERY_DAY, "06:30", 8, _at(2026, 10, 2, 5), _at(2026, 10, 2, 12, 30)),  # 07:00: 14:30
        # only on the chosen days: at Monday's last run (22:00 CEST), next Monday's first
        ([Weekday.MON], "10:00", 12, _at(2026, 9, 28, 20), _at(2026, 10, 5, 8)),
        ([Weekday.MON, Weekday.FRI], "00:00", 6, _at(2026, 9, 28, 21), _at(2026, 10, 1, 22)),
        # 2026-03-29 (spring): 02:00 does not exist, so 01:00 CET is followed by 03:00 CEST
        (EVERY_DAY, "00:00", 1, _at(2026, 3, 29, 0, 30), _at(2026, 3, 29, 1)),
        # every 4 hours: 00:00 CET, then 04:00 CEST only 3 hours later
        (EVERY_DAY, "00:00", 4, _at(2026, 3, 28, 23, 30), _at(2026, 3, 29, 2)),
        # 2026-10-25 (autumn): 02:00 happens twice; it fires the first time, then at 03:00 CET
        (EVERY_DAY, "00:00", 1, _at(2026, 10, 24, 23, 30), _at(2026, 10, 25, 0)),
        (EVERY_DAY, "00:00", 1, _at(2026, 10, 25, 0), _at(2026, 10, 25, 2)),  # a 2 h gap
        # every 2 hours: 02:00 CEST, then 04:00 CET 3 hours later
        (EVERY_DAY, "00:00", 2, _at(2026, 10, 25, 0), _at(2026, 10, 25, 3)),
    ],
)
def test_the_next_occurrence_of_a_repeating_schedule(
    days: list[Weekday], time: str, every_hours: int, now: datetime, expected: datetime
) -> None:
    schedule = Schedule.model_validate(
        {"days": days, "time": time, "timezone": "Europe/Berlin", "every_hours": every_hours}
    )

    assert next_occurrence(schedule, now) == expected
