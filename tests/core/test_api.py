import httpx2
import pytest

from infrasales.core.api import post

pytestmark = pytest.mark.anyio
URL = "https://api.test/v1/things"


async def test_rate_limits_and_server_errors_are_waited_out() -> None:
    answers = iter(
        [
            httpx2.Response(429, headers={"Retry-After": "3"}),
            httpx2.Response(503),
            httpx2.Response(200, json={"ok": True}),
        ]
    )
    waited: list[float] = []

    async def wait(seconds: float) -> None:
        waited.append(seconds)

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: next(answers))
    ) as client:
        response = await post(client, URL, {"q": 1}, retries=4, sleep=wait)

    assert response.json() == {"ok": True}
    assert waited == [3.0, 2.0]


async def test_a_lost_connection_is_tried_again() -> None:
    calls: list[int] = []

    def answer(_: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        if len(calls) == 1:
            lost = "lost"
            raise httpx2.ConnectError(lost)
        return httpx2.Response(200, json={})

    async def wait(_: float) -> None:
        pass

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(answer)) as client:
        await post(client, URL, {}, retries=2, sleep=wait)

    assert len(calls) == 2


async def test_a_refusal_or_the_last_failure_raises() -> None:
    async def wait(_: float) -> None:
        pass

    refusing = httpx2.MockTransport(lambda _: httpx2.Response(401))
    failing = httpx2.MockTransport(lambda _: httpx2.Response(503))
    async with httpx2.AsyncClient(transport=refusing) as client:
        with pytest.raises(httpx2.HTTPStatusError):
            await post(client, URL, {}, retries=3, sleep=wait)
    async with httpx2.AsyncClient(transport=failing) as client:
        with pytest.raises(httpx2.HTTPStatusError):
            await post(client, URL, {}, retries=1, sleep=wait)
