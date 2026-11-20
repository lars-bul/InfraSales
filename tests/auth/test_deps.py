from collections.abc import AsyncIterator

import httpx2
import pytest

from infrasales.app import create_app
from infrasales.auth.deps import AdminUser, CurrentUser
from infrasales.auth.models import User
from infrasales.settings import Settings
from tests.helpers import sign_in

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx2.AsyncClient]:
    app = create_app(settings)

    @app.get("/api/test/user")
    async def any_user(user: CurrentUser) -> User:
        return user

    @app.get("/api/test/admin")
    async def admin_only(user: AdminUser) -> User:
        return user

    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        yield client


async def test_anonymous_requests_are_refused(client: httpx2.AsyncClient) -> None:
    assert (await client.get("/api/test/user")).status_code == 401
    assert (await client.get("/api/test/admin")).status_code == 401


async def test_viewers_are_signed_in_but_not_admins(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "vera")

    assert (await client.get("/api/test/user")).json()["subject"] == "basic:vera"
    assert (await client.get("/api/test/admin")).status_code == 403


async def test_admins_pass_both_checks(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "alice")

    assert (await client.get("/api/test/admin")).json()["role"] == "admin"


async def test_an_invalid_cookie_is_anonymous(client: httpx2.AsyncClient) -> None:
    client.cookies.set("infrasales_session", "forged")

    assert (await client.get("/api/test/user")).status_code == 401
