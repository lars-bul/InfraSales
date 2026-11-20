"""JSON APIs InfraSales calls: a POST that waits out rate limits and server errors."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping

import httpx2

RETRYABLE = frozenset({429, 500, 502, 503, 504})
MAX_WAIT_SECONDS = 60.0

type Sleep = Callable[[float], Awaitable[None]]


async def post(
    client: httpx2.AsyncClient,
    url: str,
    body: Mapping[str, object],
    *,
    retries: int,
    sleep: Sleep = asyncio.sleep,
) -> httpx2.Response:
    """The answer, once it is not a rate limit or server error; raises `httpx2.HTTPError` else."""
    for attempt in range(retries):
        try:
            response = await client.post(url, json=body)
        except httpx2.TransportError:
            await sleep(min(2.0**attempt, MAX_WAIT_SECONDS))
            continue
        if response.status_code not in RETRYABLE:
            return response.raise_for_status()
        await sleep(min(_retry_after(response, attempt), MAX_WAIT_SECONDS))
    return (await client.post(url, json=body)).raise_for_status()


def _retry_after(response: httpx2.Response, attempt: int) -> float:
    try:
        return max(float(response.headers.get("Retry-After", "")), 0.0)
    except ValueError:
        return 2.0**attempt
