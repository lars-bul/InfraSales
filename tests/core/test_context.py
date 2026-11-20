import io
import json
from collections.abc import AsyncIterator

import httpx2
import pytest
from fastapi import FastAPI, Request

from infrasales.core.context import RequestContextMiddleware
from infrasales.core.logs import configure_logging

pytestmark = pytest.mark.anyio


class BoomError(Exception):
    pass


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/ok")
    async def ok(request: Request) -> dict[str, str]:
        return {"request_id": request.state.request_id}

    @app.get("/boom")
    async def boom() -> None:
        raise BoomError

    app.add_middleware(RequestContextMiddleware)
    return app


@pytest.fixture
async def client() -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=_app(), raise_app_exceptions=False)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def test_each_request_gets_an_id_and_one_log_line(client: httpx2.AsyncClient) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)

    response = await client.get("/ok", params={"code": "secret"})

    (line,) = [json.loads(raw) for raw in stream.getvalue().splitlines()]
    assert line["request_id"] == response.headers["x-request-id"] == response.json()["request_id"]
    assert (line["event"], line["path"], line["status"]) == ("request", "/ok", 200)
    assert "secret" not in stream.getvalue()


async def test_a_request_that_fails_without_a_response_is_logged_as_500(
    client: httpx2.AsyncClient,
) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)

    await client.get("/boom")  # answered by the error boundary inside, or the server

    (line,) = [json.loads(raw) for raw in stream.getvalue().splitlines() if '"request"' in raw]
    assert (line["path"], line["status"]) == ("/boom", 500)


async def test_non_http_scopes_pass_through() -> None:
    reached: list[str] = []

    async def inner(scope: dict[str, object], _: object, __: object) -> None:
        reached.append(str(scope["type"]))

    await RequestContextMiddleware(inner)({"type": "lifespan"}, None, None)  # pyright: ignore[reportArgumentType]

    assert reached == ["lifespan"]
