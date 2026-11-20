import io
import json
from collections.abc import AsyncIterator

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.responses import StreamingResponse

from infrasales.core.context import RequestContextMiddleware
from infrasales.core.errors import ErrorMiddleware
from infrasales.core.logs import configure_logging

pytestmark = pytest.mark.anyio


class BoomError(Exception):
    pass


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/boom")
    async def boom() -> None:
        raise BoomError

    @app.get("/database-down")
    async def database_down() -> None:
        statement = "SELECT 1"
        raise OperationalError(statement, {}, ConnectionError())

    @app.get("/pool-exhausted")
    async def pool_exhausted() -> None:
        raise PoolTimeoutError

    @app.get("/late-boom")
    async def late_boom() -> StreamingResponse:
        async def chunks() -> AsyncIterator[bytes]:
            yield b"partial"
            raise BoomError

        return StreamingResponse(chunks())

    app.add_middleware(ErrorMiddleware)
    app.add_middleware(RequestContextMiddleware)
    return app


@pytest.fixture
async def client() -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=_app(), raise_app_exceptions=False)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def test_unexpected_errors_answer_a_safe_500_and_are_logged(
    client: httpx2.AsyncClient,
) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)

    response = await client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal Server Error",
        "request_id": response.headers["x-request-id"],
    }
    error = json.loads(stream.getvalue().splitlines()[0])
    assert (error["event"], error["request_id"]) == (
        "unhandled_error",
        response.headers["x-request-id"],
    )
    assert error["exception"][0]["exc_type"] == "BoomError"  # the traceback, in the log only


@pytest.mark.parametrize("path", ["/database-down", "/pool-exhausted"])
async def test_an_unavailable_database_answers_503_to_retry(
    client: httpx2.AsyncClient, path: str
) -> None:
    configure_logging(stream=io.StringIO())

    response = await client.get(path)

    assert (response.status_code, response.headers["retry-after"]) == (503, "5")
    assert response.json() == {
        "detail": "Service Unavailable",
        "request_id": response.headers["x-request-id"],
    }


async def test_errors_after_the_response_started_abort_it(client: httpx2.AsyncClient) -> None:
    configure_logging(stream=io.StringIO())

    response = await client.get("/late-boom")

    assert response.status_code == 200  # headers were sent; the body is cut short


async def test_without_a_request_context_the_answer_has_no_id() -> None:
    configure_logging(stream=io.StringIO())
    app = FastAPI()

    @app.get("/boom")
    async def boom() -> None:
        raise BoomError

    app.add_middleware(ErrorMiddleware)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/boom")

    assert response.json() == {"detail": "Internal Server Error", "request_id": None}


async def test_non_http_scopes_pass_through() -> None:
    reached: list[str] = []

    async def inner(scope: dict[str, object], _: object, __: object) -> None:
        reached.append(str(scope["type"]))

    await ErrorMiddleware(inner)({"type": "lifespan"}, None, None)  # pyright: ignore[reportArgumentType]

    assert reached == ["lifespan"]
