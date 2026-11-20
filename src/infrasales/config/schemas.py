"""Global configuration values, validated by their schema."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from infrasales.core.zones import known_timezone


class ConfigKey(StrEnum):
    SCRAPE_SCHEDULE = "scrape_schedule"
    FORECAST_SCHEDULE = "forecast_schedule"

    @property
    def default(self) -> Schedule:
        """The value the setting starts with: stored on startup wherever none is stored yet."""
        return _DEFAULTS[self]


class Weekday(StrEnum):  # in `date.weekday()` order
    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"


WEEKDAYS = list(Weekday)

# Hours a schedule can repeat after: those dividing a day, so that a repetition starting before
# the first interval ends (e.g. at 00:00) keeps the same pace across midnight.
type EveryHours = Literal[1, 2, 3, 4, 6, 8, 12]


class Schedule(BaseModel):
    """When a job runs: on these weekdays, at this local time (daily means all seven days).

    With `every_hours`, it also runs every that many hours after the time, until the day ends:
    `00:00` every 3 hours is 00:00, 03:00, ..., 21:00 (like systemd's `00/3` or cron's `0 */3`).
    """

    days: list[Weekday] = Field(min_length=1)
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", examples=["08:00"])  # HH:MM
    timezone: str = Field(examples=["Europe/Berlin"])  # IANA name; DST is handled
    enabled: bool = True
    every_hours: EveryHours | None = None  # None: once a day, at the time

    @field_validator("days")
    @classmethod
    def _week_order(cls, days: list[Weekday]) -> list[Weekday]:
        return sorted(set(days), key=WEEKDAYS.index)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, timezone: str) -> str:
        return known_timezone(timezone)


_DEFAULTS: dict[ConfigKey, Schedule] = {
    ConfigKey.SCRAPE_SCHEDULE: Schedule(  # feeds forget within a day (ADR 03 §7)
        days=WEEKDAYS, time="00:00", every_hours=3, timezone="Europe/Berlin"
    ),
    ConfigKey.FORECAST_SCHEDULE: Schedule(  # a fresh list before the sales week starts
        days=[Weekday.MON], time="05:00", timezone="Europe/Berlin"
    ),
}


class ConfigEntryRead(BaseModel):
    key: ConfigKey
    value: Schedule
    revision: int  # send it back as `If-Match: "<revision>"` to change the setting
    updated_at: datetime
    next_run_at: datetime | None  # when the schedule fires next; None while it is disabled
