"""Keeping to a service's rate limit: wait while it is briefly used up, fail once it is for long."""

import asyncio
import contextlib
import http
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import override

import httpx2
import structlog

from infrasales.core.models import utcnow

_log = structlog.stdlib.get_logger(__name__)
_SAME_WINDOW = timedelta(seconds=2)  # resets come in whole seconds, from a request's departure


class QuotaExhaustedError(Exception):
    """The service takes no request before `retry_at`: later than a request may wait."""

    def __init__(self, retry_at: datetime) -> None:
        super().__init__(f"no request to the language model before {retry_at:%Y-%m-%d %H:%M} UTC")
        self.retry_at = retry_at


class RateLimitedTransport(httpx2.AsyncBaseTransport):
    """Sends a request only when the service has room for it, as its last answer said."""

    def __init__(
        self,
        wrapped: httpx2.AsyncBaseTransport,
        *,
        max_wait: float,
        clock: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    ) -> None:
        self._wrapped, self._max_wait = wrapped, timedelta(seconds=max_wait)
        self._clock, self._sleep = clock, sleep
        self._remaining: int | None = None  # requests left until `_reset_at`; None: not known
        self._reset_at = clock()

    @override
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        await self._wait_for_room()
        sent_at = self._clock()
        response = await self._wrapped.handle_async_request(request)
        await self._learn(response, sent_at)
        return response

    @override
    async def aclose(self) -> None:
        await self._wrapped.aclose()

    async def _wait_for_room(self) -> None:
        if self._remaining is None:
            return
        if self._remaining > 0:
            self._remaining -= 1  # counted before the answer comes: requests in parallel
            return
        wait = self._reset_at - self._clock()
        if wait > self._max_wait:
            raise QuotaExhaustedError(self._reset_at)  # nothing sent: it would only be refused
        if wait > timedelta(0):
            _log.info("llm.rate_limited", wait_seconds=round(wait.total_seconds(), 1))
            await self._sleep(wait.total_seconds())
        self._remaining = None  # a new window: its first answer says how much it holds

    async def _learn(self, response: httpx2.Response, sent_at: datetime) -> None:
        now, headers = self._clock(), response.headers
        remaining = _count(headers.get("ratelimit-remaining"))
        reset_at = _after(headers.get("ratelimit-reset"), sent_at)
        if remaining is not None and reset_at and reset_at > now:  # else: its window is over
            self._take(remaining, reset_at)
        if response.status_code != http.HTTPStatus.TOO_MANY_REQUESTS:
            return
        if until := _after(headers.get("retry-after"), now) or reset_at:
            self._remaining, self._reset_at = 0, until
            if until - now > self._max_wait:
                await response.aclose()
                raise QuotaExhaustedError(until)

    def _take(self, remaining: int, reset_at: datetime) -> None:
        """What an answer says is left; within one window, never more than counted since."""
        if self._remaining is not None and reset_at <= self._reset_at + _SAME_WINDOW:
            remaining = min(remaining, self._remaining)  # it misses the requests sent after it
            reset_at = max(reset_at, self._reset_at)
        self._remaining, self._reset_at = remaining, reset_at


def _count(value: str | None) -> int | None:
    if value is not None:
        with contextlib.suppress(ValueError):
            return int(value)
    return None


def _after(value: str | None, now: datetime) -> datetime | None:
    """When a header's delay ends: seconds after `now`, or an HTTP date (`Retry-After` only)."""
    if value is None:
        return None
    with contextlib.suppress(ValueError, OverflowError):
        return now + timedelta(seconds=max(float(value), 0))
    with contextlib.suppress(ValueError):
        when = parsedate_to_datetime(value)
        return when if when.tzinfo else when.replace(tzinfo=UTC)
    return None
