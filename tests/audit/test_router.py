import httpx2
import pytest

from tests.helpers import audit_actions, audit_events, sign_in

pytestmark = pytest.mark.anyio


async def test_admins_read_the_newest_events_and_the_read_is_audited(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await sign_in(client, "vera")
    await sign_in(client, "alice")

    events = (await client.get("/api/audit-events", params={"limit": 1})).json()

    assert [(e["actor"], e["action"]) for e in events] == [("basic:alice", "auth.login")]
    assert "client_network" not in events[0]
    assert (await audit_actions(database_url))[-1] == ("basic:alice", "audit.read", "success")


async def test_viewers_cannot_read_the_audit_log(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "vera")

    assert (await client.get("/api/audit-events")).status_code == 403


@pytest.mark.parametrize("limit", [0, 201])
async def test_the_page_size_is_bounded(client: httpx2.AsyncClient, limit: int) -> None:
    await sign_in(client, "alice")

    assert (await client.get("/api/audit-events", params={"limit": limit})).status_code == 422


async def test_an_investigation_pages_back_and_filters(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    for user in ("vera", "alice", "vera", "alice"):
        await sign_in(client, user)

    logins = (await client.get("/api/audit-events", params={"action": "auth.login"})).json()
    older = await client.get(
        "/api/audit-events", params={"before": logins[0]["id"], "actor": "basic:vera"}
    )

    assert [event["actor"] for event in logins] == ["basic:alice", "basic:vera"] * 2
    assert [event["actor"] for event in older.json()] == ["basic:vera"] * 2
    read = [event for event in await audit_events(database_url) if event.action == "audit.read"]
    assert [event.details for event in read] == [
        {"action": "auth.login"},
        {"before": logins[0]["id"], "actor": "basic:vera"},  # what was looked for, audited
    ]
