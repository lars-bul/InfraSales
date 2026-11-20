"""When a weekly schedule fires: pure date arithmetic, aware of time zones and DST."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from infrasales.config.schemas import WEEKDAYS, Schedule


def latest_occurrence(schedule: Schedule, now: datetime) -> datetime:
    """The newest time at or before `now` (UTC) the schedule fires.

    A local time skipped by a DST change (02:30 on the spring change in Europe) fires an hour
    later; a repeated one (autumn) fires the first time.
    """
    today = now.astimezone(ZoneInfo(schedule.timezone)).date()
    for days_back in range(8):  # today and the week before: every weekday occurs in it
        day = today - timedelta(days=days_back)
        if WEEKDAYS[day.weekday()] in schedule.days:
            due = [occurrence for occurrence in _on(day, schedule) if occurrence <= now]
            if due:
                return max(due)
    raise AssertionError  # a schedule has at least one day, so the loop always returns


def next_occurrence(schedule: Schedule, now: datetime) -> datetime:
    """The earliest time after `now` (UTC) the schedule fires, by the same rules as above.

    Around a DST change, one gap of a repeating schedule is an hour shorter or longer.
    """
    today = now.astimezone(ZoneInfo(schedule.timezone)).date()
    for days_ahead in range(8):  # today and the week after: every weekday occurs in it
        day = today + timedelta(days=days_ahead)
        if WEEKDAYS[day.weekday()] in schedule.days:
            upcoming = [occurrence for occurrence in _on(day, schedule) if occurrence > now]
            if upcoming:
                return min(upcoming)
    raise AssertionError  # a schedule has at least one day, so the loop always returns


def _on(day: date, schedule: Schedule) -> Iterator[datetime]:
    """The schedule's times on `day` (one of its days), in UTC."""
    zone = ZoneInfo(schedule.timezone)
    start = time.fromisoformat(schedule.time)
    for hour in range(start.hour, 24, schedule.every_hours or 24):
        local = datetime.combine(day, start.replace(hour=hour), tzinfo=zone)
        yield local.astimezone(UTC)
