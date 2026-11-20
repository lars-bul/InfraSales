import httpx2
import pytest

from tests.helpers import SAME_ORIGIN, audit_actions, sign_in

pytestmark = pytest.mark.anyio


async def test_the_session_says_who_is_signed_in_and_how_to_sign_in(
    client: httpx2.AsyncClient,
) -> None:
    anonymous = (await client.get("/api/auth/session")).json()
    await sign_in(client, "alice")
    signed_in = (await client.get("/api/auth/session")).json()

    assert anonymous == {"user": None, "provider": "basic"}
    assert signed_in == {
        "user": {"subject": "basic:alice", "name": "alice", "role": "admin"},
        "provider": "basic",
    }


async def test_logout_ends_the_session_and_returns_to_the_app(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await sign_in(client, "alice")
    token = client.cookies["infrasales_session"]

    response = await client.post("/api/auth/logout", headers=SAME_ORIGIN)
    client.cookies.set("infrasales_session", token)  # replaying the old cookie does not work

    assert (response.status_code, response.headers["location"]) == (303, "/")
    assert (await client.get("/api/auth/session")).json()["user"] is None
    assert (await audit_actions(database_url))[-1] == ("basic:alice", "auth.logout", "success")


async def test_logout_without_a_session_is_harmless(client: httpx2.AsyncClient) -> None:
    response = await client.post("/api/auth/logout", headers=SAME_ORIGIN)

    assert response.status_code == 303


async def test_logout_with_an_unknown_session_records_nothing(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    client.cookies.set("infrasales_session", "forged")

    response = await client.post("/api/auth/logout", headers=SAME_ORIGIN)

    assert response.status_code == 303
    assert await audit_actions(database_url) == []
