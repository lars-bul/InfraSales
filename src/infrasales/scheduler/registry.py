"""What the scheduler runs: jobs by name, each with the config entry holding its schedule."""

from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from infrasales.config.schemas import ConfigKey
from infrasales.core.models import JSONValue
from infrasales.scheduler.steps import Steps


class Trace(Protocol):
    """A run's trace, or a step's within it: what went in, and what came out."""

    def step(self, name: str, given: JSONValue = None) -> AbstractContextManager[Trace]:
        """Trace a step of the run (scraping, writing, mailing) inside this one, given `given`."""
        ...

    def finish(self, result: JSONValue) -> None:
        """Record what the run or step returned."""
        ...


class _Untraced:
    """No telemetry configured: steps and results are not recorded anywhere."""

    def step(self, name: str, given: JSONValue = None) -> AbstractContextManager[Trace]:  # noqa: ARG002  # nothing to trace
        return nullcontext(self)

    def finish(self, result: JSONValue) -> None:
        """Nothing to record."""


UNTRACED: Trace = _Untraced()

# How far the attempt got, as "Run now" shows it while it runs: replaced on each report, never
# a step done (`Steps`). Reporting never raises: a progress lost is no failure of the run.
type Progress = Callable[[JSONValue], Awaitable[None]]


async def _unreported(progress: JSONValue) -> None:
    """Nobody follows the run (a notebook, a test): its progress is not kept."""


UNREPORTED: Progress = _unreported


@dataclass(frozen=True, slots=True)
class JobContext:
    run_id: UUID  # stable across retries: the idempotency key for effects outside the database
    scheduled_for: datetime
    steps: Steps  # what earlier attempts of this run already did
    trace: Trace = UNTRACED  # the run's trace: jobs trace their steps in it
    progress: Progress = UNREPORTED  # where the job reports how far it got


@dataclass(frozen=True, slots=True)
class Alert:
    """A run that needs a person: it failed for good, or failed again and will be retried.

    What it says is operational only: the job, the run, its attempts, the error's type.
    """

    job: str
    run_id: UUID
    outcome: Literal["failed", "retrying"]
    attempt: int
    max_attempts: int
    error: str  # the exception type, never details
    retry_at: datetime | None = None  # when it is retried
    langfuse_url: str | None = None  # the run's session, when known

    @property
    def key(self) -> str:
        return f"alert-{self.run_id}-{self.attempt}"

    def subject(self) -> str:
        return f"infrasales: {self.job} {'failed' if self.outcome == 'failed' else 'keeps failing'}"

    def text(self) -> str:
        attempt = f"attempt {self.attempt} of {self.max_attempts} raised {self.error}"
        if self.outcome == "failed":
            happened = f"failed for good: {attempt}."
        else:
            happened = (
                f"keeps failing: {attempt}; it is retried at {self.retry_at:%Y-%m-%d %H:%M} UTC."
            )
        text = f"The job {self.job} {happened}\nRun: {self.run_id}"
        return f"{text}\nLangfuse: {self.langfuse_url}" if self.langfuse_url else text


class Notice(Protocol):
    """What a person must hear about: a failing run (`Alert`), or what a job found.

    A job's finding: a Feed blocking InfraSales' bot. Operational only, like an `Alert`.
    """

    @property
    def key(self) -> str:
        """Unique per notice: an alert mail's Message-ID."""
        ...

    def subject(self) -> str: ...

    def text(self) -> str: ...


class Notifier(Protocol):
    async def notify(self, notice: Notice, /) -> None:
        """Tell someone about `notice`. Raising is fine: the worker logs it and goes on."""
        ...


class Job(Protocol):
    async def __call__(self, context: JobContext, /) -> JSONValue:
        """Do the work; the return value is stored as the run's result."""
        ...


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    run: Job
    schedule: ConfigKey | None = None  # None: runs only when triggered
    notifier: Notifier | None = None  # told when a run fails, or keeps failing
    then: tuple[str, ...] = ()  # jobs queued when a run succeeds (`RunTrigger.FOLLOW_UP`)
    timeout_seconds: float | None = None  # how long a run may take; None: the scheduler's


type Registry = Mapping[str, ScheduledJob]
