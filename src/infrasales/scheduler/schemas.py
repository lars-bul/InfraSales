from datetime import date, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from infrasales.core.zones import TimeZoneName
from infrasales.scheduler.models import JobStatus, RunTrigger


class JobRunRead(BaseModel):
    id: UUID
    job: str
    trigger: RunTrigger
    status: JobStatus
    scheduled_for: datetime
    attempts: int
    finished_at: datetime | None
    error: str | None


class RunFilter(BaseModel):
    """Which runs: of one status or trigger, scheduled from `start` until `end`, if asked."""

    status: JobStatus | None = None
    trigger: RunTrigger | None = None
    start: AwareDatetime | None = None  # scheduled at or after
    end: AwareDatetime | None = None  # scheduled before

    @model_validator(mode="after")
    def _start_before_end(self) -> Self:
        if self.start and self.end and self.start >= self.end:
            msg = "start must be before end"
            raise ValueError(msg)
        return self


class RunQuery(RunFilter):
    """Which runs to read: a page back from `before`, filtered if asked."""

    limit: int = Field(default=20, ge=1, le=50)
    before: UUID | None = None


class ActivityQuery(RunFilter):
    """Which runs to count over time, and whose hours and days to count them in.

    Without `end`, until now; without `start`, the 7 days before the end. The time zone is the
    client's, by IANA name.
    """

    timezone: TimeZoneName


class SummaryQuery(BaseModel):
    """Whose calendar days the summary's daily counts fall on: the client's, by IANA name."""

    timezone: TimeZoneName


class RunCounts(BaseModel):
    """Runs that ended, by how: succeeded, or failed for good (retries used up)."""

    succeeded: int
    failed: int


class DayCounts(RunCounts):
    day: date  # a calendar day in the time zone asked for


class RunSummary(BaseModel):
    """How a job's runs went lately, counted by when they finished."""

    last_24h: RunCounts
    last_7d: RunCounts
    days: list[DayCounts]  # the last 7 calendar days, oldest first, today last


class BucketCounts(RunCounts):
    start: datetime  # the hour or the day's midnight, in the time zone asked for


class RunActivity(BaseModel):
    """How the runs scheduled from `start` until `end` ended, an hour or a day at a time.

    Hours for up to 2 days, else calendar days: oldest first. Runs that have not ended yet
    count in neither.
    """

    start: datetime
    end: datetime
    unit: Literal["hour", "day"]
    buckets: list[BucketCounts]
