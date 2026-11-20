import httpx2
import pytest

from tests.helpers import PASSWORD, audit_actions, sign_in

pytestmark = pytest.mark.anyio


async def test_signing_in_starts_a_session_and_returns_to_the_app(
    client: httpx2.AsyncClient,
) -> None:
    response = await sign_in(client, "vera")

    assert (response.status_code, response.headers["location"]) == (303, "/")
    assert "HttpOnly" in response.headers["set-cookie"]
    assert (await client.get("/api/auth/session")).json()["user"]["role"] == "viewer"


@pytest.mark.parametrize(
    ("username", "password"),
    [("vera", "wrong-password"), ("mallory", PASSWORD), ("", "")],
)
async def test_failed_sign_ins_return_to_the_form_without_a_session(
    client: httpx2.AsyncClient, username: str, password: str
) -> None:
    response = await sign_in(client, username, password)

    assert (response.status_code, response.headers["location"]) == (303, "/?signin=failed")
    assert "set-cookie" not in response.headers


async def test_signing_in_again_replaces_the_previous_session(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "vera")
    previous = client.cookies["infrasales_session"]

    await sign_in(client, "alice")
    client.cookies.set("infrasales_session", previous)

    assert (await client.get("/api/auth/session")).json()["user"] is None


async def test_sign_ins_are_audited_without_recording_unknown_names(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await sign_in(client, "vera")
    await sign_in(client, "vera", "wrong-password")
    await sign_in(client, "my-password-typed-as-name")

    assert await audit_actions(database_url) == [
        ("basic:vera", "auth.login", "success"),
        ("basic:vera", "auth.login", "failure"),
        (None, "auth.login", "failure"),
    ]
