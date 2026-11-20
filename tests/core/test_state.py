import httpx2
import pytest
from fastapi import FastAPI, Request

from infrasales.core.state import StateKey

pytestmark = pytest.mark.anyio
GREETING = StateKey[str]("greeting")
MISSING = StateKey[int]("missing")


async def test_values_set_on_the_app_are_read_typed_by_requests() -> None:
    app = FastAPI()
    GREETING.set(app, "hello")

    @app.get("/")
    async def read(request: Request) -> dict[str, object]:
        return {"greeting": GREETING.get(request), "missing": MISSING.find(request)}

    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert response.json() == {"greeting": "hello", "missing": None}
