from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import override

import httpx2
import pytest

from infrasales.ai.limits import QuotaExhaustedError, RateLimitedTransport

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
LEFT = {"RateLimit-Remaining": "1", "RateLimit-Reset": "30"}
NONE_LEFT = {"RateLimit-Remaining": "0", "RateLimit-Reset": "30"}

type Answer = tuple[int, dict[str, str]]
PLAIN: Answer = (200, {})


class Clock:
    """Time that passes only while someone sleeps."""

    def __init__(self) -> None:
        self.now, self.slept = NOW, list[float]()

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


class Service:
    """Gives `answers` in turn, then plain 200s, each `latency` seconds after the request came.

    It counts the requests that reach it.
    """

    def __init__(self, *answers: Answer, max_wait: float = 60, latency: float = 0) -> None:
        self.clock, self.requests, self._answers = Clock(), 0, iter(answers)
        self._latency = timedelta(seconds=latency)
        self.transport = RateLimitedTransport(
            httpx2.MockTransport(self._answer),
            max_wait=max_wait,
            clock=self.clock,
            sleep=self.clock.sleep,
        )

    def _answer(self, _: httpx2.Request) -> httpx2.Response:
        self.requests += 1
        self.clock.now += self._latency  # the model thinks; the headers stay as of its arrival
        status, headers = next(self._answers, PLAIN)
        return httpx2.Response(status, headers=headers)

    async def send(self) -> int:
        request = httpx2.Request("POST", "https://llm.test/v1/chat/completions")
        return (await self.transport.handle_async_request(request)).status_code


async def test_requests_go_at_once_while_the_service_has_room() -> None:
    service = Service((200, {"RateLimit-Remaining": "2", "RateLimit-Reset": "30"}), (200, LEFT))

    for _ in range(3):
        await service.send()

    assert service.clock.slept == []


async def test_once_none_are_left_the_next_request_waits_for_the_reset() -> None:
    service = Service((200, NONE_LEFT))

    await service.send()
    await service.send()

    assert (service.clock.slept, service.requests) == ([30], 2)


async def test_the_reset_counts_from_when_the_request_left_not_from_its_answer() -> None:
    service = Service((200, {"RateLimit-Remaining": "0", "RateLimit-Reset": "57"}), latency=50)

    await service.send()
    await service.send()

    assert service.clock.slept == [7]


async def test_an_answer_whose_window_is_over_is_ignored() -> None:
    service = Service((200, NONE_LEFT), latency=40)

    await service.send()
    await service.send()

    assert service.clock.slept == []


async def test_a_late_answer_does_not_raise_what_is_left_in_its_window() -> None:
    stale = {"RateLimit-Remaining": "9", "RateLimit-Reset": "30"}  # its request left earlier
    service = Service((200, LEFT), (200, stale))

    for _ in range(3):
        await service.send()

    assert service.clock.slept == [30]


async def test_an_answer_from_a_later_window_replaces_the_count() -> None:
    later = {"RateLimit-Remaining": "29", "RateLimit-Reset": "60"}
    service = Service((200, {"RateLimit-Remaining": "5", "RateLimit-Reset": "30"}), (200, later))

    for _ in range(8):
        await service.send()

    assert service.clock.slept == []  # 29 left from the second answer on, not 4


async def test_no_wait_once_the_reset_has_passed() -> None:
    service = Service((200, NONE_LEFT))
    await service.send()
    service.clock.now += timedelta(seconds=31)

    await service.send()

    assert service.clock.slept == []


@pytest.mark.parametrize(
    "headers",
    [
        {"Retry-After": "20"},
        {"Retry-After": format_datetime(NOW + timedelta(seconds=20), usegmt=True)},
        {"RateLimit-Remaining": "0", "RateLimit-Reset": "20"},  # no Retry-After: until the reset
    ],
)
async def test_after_a_429_the_next_request_waits_as_long_as_asked(headers: dict[str, str]) -> None:
    service = Service((429, headers))

    statuses = [await service.send(), await service.send()]

    assert statuses == [429, 200]  # the 429 itself goes back: the SDK retries it
    assert service.clock.slept == [20]


async def test_a_429_asking_for_too_long_a_wait_fails_and_is_not_asked_again() -> None:
    service = Service((429, {"Retry-After": "3600"}))

    for _ in range(2):
        with pytest.raises(QuotaExhaustedError, match="2026-10-13 13:00 UTC") as raised:
            await service.send()
        assert raised.value.retry_at == NOW + timedelta(hours=1)

    assert service.requests == 1


async def test_a_quota_known_to_be_used_up_for_long_fails_before_sending() -> None:
    service = Service((200, {"RateLimit-Remaining": "0", "RateLimit-Reset": "3600"}))
    await service.send()

    with pytest.raises(QuotaExhaustedError):
        await service.send()

    assert service.requests == 1


@pytest.mark.parametrize(
    "answer",
    [
        (200, {"RateLimit-Remaining": "some", "RateLimit-Reset": "30"}),
        (200, {"RateLimit-Remaining": "0", "RateLimit-Reset": "soon"}),
        (200, {"RateLimit-Remaining": "0"}),
        (429, {}),
        (429, {"Retry-After": "1e999"}),
    ],
)
async def test_what_the_headers_do_not_say_clearly_is_ignored(answer: Answer) -> None:
    service = Service(answer)

    await service.send()
    await service.send()

    assert (service.clock.slept, service.requests) == ([], 2)


async def test_closing_it_closes_the_transport_it_wraps() -> None:
    closed: list[bool] = []

    class Wrapped(httpx2.AsyncBaseTransport):
        @override
        async def aclose(self) -> None:
            closed.append(True)

    await RateLimitedTransport(Wrapped(), max_wait=0).aclose()

    assert closed == [True]
