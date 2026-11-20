from collections.abc import AsyncIterator

import httpx2
import pytest
from fastapi import FastAPI, Request
from starlette.types import Message, Receive, Scope, Send

from infrasales.core.security import BodyTooLargeError, SecurityMiddleware

pytestmark = pytest.mark.anyio
ORIGIN = "http://testserver/"  # the public URL, as settings give it


def _app() -> FastAPI:
    app = FastAPI()

    @app.post("/api/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    @app.post("/api/json")
    async def parse(body: dict[str, str]) -> dict[str, int]:
        return {"size": len(body)}

    app.add_middleware(SecurityMiddleware, origin=ORIGIN, form_targets="https://idp.example")
    return app


@pytest.fixture
async def client() -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=_app())
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def test_responses_carry_the_security_headers(client: httpx2.AsyncClient) -> None:
    response = await client.post("/api/echo", headers={"sec-fetch-site": "same-origin"})

    assert response.headers["content-security-policy"].endswith(
        "form-action 'self' https://idp.example"
    )
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"sec-fetch-site": "same-origin"}, 200),
        ({"sec-fetch-site": "none"}, 200),  # typed into the address bar
        ({"sec-fetch-site": "cross-site"}, 403),
        ({"origin": "http://testserver"}, 200),
        ({"origin": "http://testserver:80"}, 200),  # the default port, explicit
        ({"origin": "https://testserver"}, 403),  # the same host on another scheme
        ({"origin": "http://testserver:8080"}, 403),
        ({"origin": "http://testserver:x"}, 403),
        ({"origin": "http://["}, 403),  # malformed: rejected, not a failure
        ({"origin": "null"}, 403),  # e.g. a sandboxed frame
        ({"origin": "https://evil.example"}, 403),
        ({}, 200),  # not a browser: no ambient credentials to abuse
    ],
)
async def test_cross_site_writes_are_rejected(
    client: httpx2.AsyncClient, headers: dict[str, str], status: int
) -> None:
    response = await client.post("/api/echo", headers=headers)

    assert response.status_code == status


def test_the_public_origin_must_be_one() -> None:
    with pytest.raises(ValueError, match="is no origin"):
        SecurityMiddleware(_app(), origin="null")


async def test_large_bodies_are_rejected_declared_or_streamed(client: httpx2.AsyncClient) -> None:
    big = b"x" * ((1 << 20) + 1)

    async def chunks() -> AsyncIterator[bytes]:
        yield big

    declared = await client.post("/api/echo", content=big)
    streamed = await client.post("/api/echo", content=chunks())
    parsed = await client.post("/api/json", content=chunks())  # FastAPI parsing the body
    small = await client.post("/api/echo", content=b"ok")

    assert [r.status_code for r in (declared, streamed, parsed)] == [413, 413, 413]
    assert small.json() == {"size": 2}


async def test_an_app_that_does_not_handle_the_limit_still_answers_413() -> None:
    async def read_then_respond(_: Scope, receive: Receive, __: Send) -> None:
        await receive()  # a plain ASGI app: no exception handling of its own

    async def receive() -> Message:
        return {"type": "http.request", "body": b"x" * ((1 << 20) + 1), "more_body": False}

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {"type": "http", "method": "POST", "path": "/api/echo", "headers": []}
    await SecurityMiddleware(read_then_respond, origin=ORIGIN)(scope, receive, send)

    assert sent[0]["status"] == 413


async def test_a_body_limit_hit_after_responding_aborts_the_response() -> None:
    async def respond_then_read(_: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()

    async def receive() -> Message:
        return {"type": "http.request", "body": b"x" * ((1 << 20) + 1), "more_body": False}

    async def send(_: Message) -> None:
        pass

    scope: Scope = {"type": "http", "method": "POST", "path": "/api/echo", "headers": []}
    with pytest.raises(BodyTooLargeError):
        await SecurityMiddleware(respond_then_read, origin=ORIGIN)(scope, receive, send)


@pytest.mark.parametrize(
    ("path", "cache_control"),
    [
        ("/assets/app-1234.js", "public, max-age=31536000, immutable"),
        ("/readyz", "no-store"),
        ("/", "no-cache"),
    ],
)
async def test_caching_depends_on_the_path(
    client: httpx2.AsyncClient, path: str, cache_control: str
) -> None:
    response = await client.get(path)

    assert response.headers["cache-control"] == cache_control


async def test_non_http_scopes_pass_through() -> None:
    reached: list[str] = []

    async def inner(scope: dict[str, object], _: object, __: object) -> None:
        reached.append(str(scope["type"]))

    await SecurityMiddleware(inner, origin=ORIGIN)({"type": "lifespan"}, None, None)  # pyright: ignore[reportArgumentType]

    assert reached == ["lifespan"]
