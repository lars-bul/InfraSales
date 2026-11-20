from pydantic import BaseModel, Field

from infrasales.core.state import StateKey


class SchedulerSettings(BaseModel):
    """The background worker that runs scheduled jobs (`SCHEDULER__*`)."""

    enabled: bool = (
        True  # run inside `infrasales web`; false: run `infrasales worker` on its own instead
    )
    poll_seconds: float = Field(default=30, gt=0)  # how often due runs are looked for
    lease_seconds: float = Field(default=60, gt=0)  # a crashed worker's run is taken over after it
    max_attempts: int = Field(default=3, ge=1)
    retry_seconds: float = Field(default=60, ge=0)  # backoff: doubles with every attempt
    job_timeout_seconds: float = Field(default=900, gt=0)
    # The scrape's own: its pauses between requests to a site make it the longest job. Two
    # thirds go to requests (`infrasales.fetch.pacing.run_budget`); end it before the next run.
    scrape_timeout_seconds: float = Field(default=2700, gt=0)

    @property
    def stop_margin_seconds(self) -> float:
        """How long before its lease could pass to another worker a job is stopped.

        It covers the clock skew between hosts, and work that cannot stop at once (a mail copy
        in flight), which must end within it.
        """
        return self.lease_seconds / 4


# The web app's scheduler settings, also when `infrasales worker` runs on its own (same
# environment): a followed run tells how many attempts it gets.
SCHEDULER = StateKey[SchedulerSettings]("scheduler")
