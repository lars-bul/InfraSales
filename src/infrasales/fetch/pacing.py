"""Pauses between requests to one site, and the run's time for requests (ADR 03 §5, R12).

Every request to a host waits until the previous one to that host ended at least the pause ago:
`PAUSE_SECONDS`, or the host's robots.txt `Crawl-delay` when that is longer. Hosts do not wait
for each other. The pause counts from the end of the previous request, as Apache Nutch and
Heritrix count it, so a slow site gets a slower pace.

A run has a time budget below the job timeout: each Feed gets what is left of it divided by the
Feeds left, so one slow or `Crawl-delay`ed site cannot starve the Feeds read after it. A request
whose pause would end after its Feed's share raises `OutOfTimeError`: the Feed stops for this
run, and its unread documents are read by the next run (they are still unknown then).
"""

import asyncio
import math
import time
from typing import Protocol

from infrasales.core.failures import ExpectedError

PAUSE_SECONDS = 3.0  # Heritrix's minimum delay between two requests to one host
BUDGET_SHARE = 2 / 3  # of the job timeout: the rest is margin for the requests in flight


class Clock(Protocol):
    """Monotonic seconds, and a way to let them pass; tests pass a fake one."""

    def monotonic(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class RealTime:
    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


REAL_TIME: Clock = RealTime()


class OutOfTimeError(ExpectedError):
    """The Feed's share of the run's time is used up: the rest waits for the next run."""

    reason = "out of time"


def run_budget(job_timeout_seconds: float) -> float:
    """The seconds a scrape run may spend on requests, given the scheduler's job timeout."""
    return job_timeout_seconds * BUDGET_SHARE


class Budget:
    """A run's time for requests, shared out between its Feeds as they are read."""

    def __init__(self, seconds: float | None, clock: Clock, feeds: int) -> None:
        """`seconds` None: no limit (notebooks, tests); `feeds`: how many shares there are."""
        self._clock = clock
        self._end = None if seconds is None else clock.monotonic() + seconds
        self._left = feeds
        self.deadline: float | None = self._end  # the current Feed's share ends here

    @classmethod
    def unlimited(cls) -> Budget:
        return cls(None, REAL_TIME, 0)

    def next_feed(self) -> None:
        """Start the next Feed's share: what is left, divided by the Feeds left."""
        if self._end is None:
            return
        now = self._clock.monotonic()
        self.deadline = now + max(self._end - now, 0) / max(self._left, 1)
        self._left -= 1


class Pacer:
    """When a request to a host may be sent; it waits until then, or raises `OutOfTimeError`."""

    def __init__(
        self, clock: Clock = REAL_TIME, budget: Budget | None = None, pause: float = PAUSE_SECONDS
    ) -> None:
        self._clock = clock
        self._budget = budget
        self._pause = pause
        self._last: dict[str, float] = {}  # host → when its last request started, or ended

    async def wait(self, host: str, delay: float | None = None) -> None:
        """Wait for `host`'s pause, longer if its Crawl-delay (`delay`) says so; claim the host."""
        now = self._clock.monotonic()
        at = max(now, self._last.get(host, -math.inf) + max(self._pause, delay or 0))
        deadline = self._budget.deadline if self._budget else None
        if deadline is not None and at > deadline:
            raise OutOfTimeError(host)
        self._last[host] = at  # claimed: a request sent meanwhile waits for this one
        if at > now:
            await self._clock.sleep(at - now)

    def done(self, host: str) -> None:
        """A request to `host` was answered: its pause counts from now."""
        self._last[host] = max(self._last.get(host, -math.inf), self._clock.monotonic())
