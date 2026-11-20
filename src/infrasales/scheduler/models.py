"""Job runs: every execution of a job is recorded, which makes the scheduler restart-safe."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Index, UniqueConstraint, text
from sqlmodel import Field

from infrasales.core.models import (
    SUBJECT_LENGTH,
    BaseTable,
    JSONType,
    JSONValue,
    UTCDateTime,
    enum_type,
)


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunTrigger(StrEnum):
    SCHEDULE = "schedule"
    MANUAL = "manual"  # an admin's "Run now"
    FOLLOW_UP = "follow_up"  # queued when a run of another job finished (`ScheduledJob.then`)


ACTIVE_MANUAL = text("trigger = 'manual' AND status IN ('pending', 'running')")
RUNNING = text("status = 'running'")
QUEUED_FOLLOW_UP = text("trigger = 'follow_up' AND status = 'pending'")


class JobRun(BaseTable, table=True):
    """One run of a job for one scheduled time; the unique key makes planning idempotent."""

    __table_args__ = (
        UniqueConstraint("job", "scheduled_for"),
        Index("ix_job_run_status_run_after", "status", "run_after"),
        Index("ix_job_run_status_lease_expires_at", "status", "lease_expires_at"),
        Index("ix_job_run_job_id", "job", "id"),
        Index(
            "uq_job_run_running", "job", unique=True, sqlite_where=RUNNING, postgresql_where=RUNNING
        ),
        Index(
            "uq_job_run_active_manual",
            "job",
            unique=True,
            sqlite_where=ACTIVE_MANUAL,
            postgresql_where=ACTIVE_MANUAL,
        ),
        # One follow-up waiting per job; one running doesn't count, so what its job wrote after
        # that run started is picked up by the next.
        Index(
            "uq_job_run_queued_follow_up",
            "job",
            unique=True,
            sqlite_where=QUEUED_FOLLOW_UP,
            postgresql_where=QUEUED_FOLLOW_UP,
        ),
    )

    job: str = Field(max_length=64)
    scheduled_for: datetime = Field(sa_type=UTCDateTime)
    status: JobStatus = Field(default=JobStatus.PENDING, sa_type=enum_type(JobStatus))
    attempts: int = 0
    run_after: datetime = Field(sa_type=UTCDateTime)
    lease_owner: str | None = Field(default=None, max_length=128)
    lease_expires_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    finished_at: datetime | None = Field(default=None, sa_type=UTCDateTime, index=True)  # retention
    error: str | None = Field(default=None, max_length=255)  # the exception type, never details
    result: JSONValue = Field(default=None, sa_type=JSONType, nullable=True)  # alias hides None
    # How far the latest attempt got, as its job last reported it; cleared while none is underway.
    progress: JSONValue = Field(default=None, sa_type=JSONType, nullable=True)
    trigger: RunTrigger = Field(
        default=RunTrigger.SCHEDULE,
        sa_type=enum_type(RunTrigger),
        sa_column_kwargs={"server_default": RunTrigger.SCHEDULE.value},  # existing rows too
    )
    triggered_by: str | None = Field(default=None, max_length=SUBJECT_LENGTH)  # admin's subject


class JobStep(BaseTable, table=True):
    """Work an attempt of a run completed, with its result: later attempts skip it.

    Steps belong to their run and are deleted with it (retention keeps unfinished runs).
    """

    __table_args__ = (UniqueConstraint("run_id", "name"),)

    run_id: uuid.UUID = Field(foreign_key="job_run.id", ondelete="CASCADE")
    name: str = Field(max_length=255)
    result: JSONValue = Field(default=None, sa_type=JSONType, nullable=True)


class JobTrigger(BaseTable, table=True):
    """A "Run now" request, by the key its client chose: asked again, the same run answers.

    That is the run it was answered with: queued by it, or already in progress. Deleted with it.
    """

    __table_args__ = (UniqueConstraint("job", "key"),)

    job: str = Field(max_length=64)
    key: uuid.UUID  # the request's Idempotency-Key
    run_id: uuid.UUID = Field(foreign_key="job_run.id", ondelete="CASCADE", index=True)
