import httpx2
import pytest
from sqlmodel import col, delete

from infrasales.config.models import ConfigEntry
from infrasales.core.db import Database
from tests.helpers import SAME_ORIGIN, audit_actions, sign_in

pytestmark = pytest.mark.anyio
WEEKLY = {
    "days": ["fri"],
    "time": "17:30",
    "timezone": "Europe/Berlin",
    "enabled": True,
    "every_hours": None,
}
FIRST = SAME_ORIGIN | {"if-match": '"1"'}  # every setting starts at revision 1


async def test_signed_in_users_read_the_configuration(client: httpx2.AsyncClient) -> None:
    assert (await client.get("/api/config")).status_code == 401
    await sign_in(client, "vera")

    entries = (await client.get("/api/config")).json()

    assert [(entry["key"], entry["revision"]) for entry in entries] == [
        ("forecast_schedule", 1),
        ("scrape_schedule", 1),
    ]


async def test_admins_change_a_schedule_and_the_change_is_audited(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await sign_in(client, "alice")

    response = await client.put("/api/config/scrape_schedule", json=WEEKLY, headers=FIRST)

    assert response.status_code == 200
    assert (response.json()["value"], response.json()["revision"]) == (WEEKLY, 2)
    assert response.headers["etag"] == '"2"'
    assert (await audit_actions(database_url))[-1] == ("basic:alice", "config.updated", "success")


async def test_admins_make_a_schedule_repeat_every_few_hours(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "alice")
    hourly = WEEKLY | {"days": ["mon", "fri"], "time": "07:00", "every_hours": 1}

    response = await client.put("/api/config/scrape_schedule", json=hourly, headers=FIRST)

    assert response.json()["value"] == hourly
    entries = (await client.get("/api/config")).json()
    assert [entry["value"] for entry in entries if entry["key"] == "scrape_schedule"] == [hourly]


async def test_a_schedule_sent_without_a_repetition_runs_once_a_day(
    client: httpx2.AsyncClient,
) -> None:
    """Clients written before repetitions existed keep working."""
    await sign_in(client, "alice")
    once = {key: value for key, value in WEEKLY.items() if key != "every_hours"}

    response = await client.put("/api/config/scrape_schedule", json=once, headers=FIRST)

    assert response.json()["value"] == once | {"every_hours": None}


@pytest.mark.parametrize("if_match", ['"1"', "1", '"one"', '""'])
async def test_a_change_to_another_revision_is_refused(
    client: httpx2.AsyncClient, if_match: str
) -> None:
    await sign_in(client, "alice")
    await client.put("/api/config/scrape_schedule", json=WEEKLY, headers=FIRST)

    stale = SAME_ORIGIN | {"if-match": if_match}
    response = await client.put("/api/config/scrape_schedule", json=WEEKLY, headers=stale)

    assert response.status_code == 412


async def test_a_change_must_name_the_revision_it_edits(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "alice")

    response = await client.put("/api/config/scrape_schedule", json=WEEKLY, headers=SAME_ORIGIN)

    assert response.status_code == 422


async def test_a_setting_without_a_row_is_not_found(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    db = Database(database_url)
    async with db.session() as session:
        await session.exec(delete(ConfigEntry).where(col(ConfigEntry.key) == "scrape_schedule"))
    await db.dispose()
    await sign_in(client, "alice")

    response = await client.put("/api/config/scrape_schedule", json=WEEKLY, headers=FIRST)

    assert response.status_code == 404


async def test_viewers_cannot_change_the_configuration(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "vera")

    response = await client.put("/api/config/scrape_schedule", json=WEEKLY, headers=FIRST)

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("key", "value"),
    [("unknown_setting", WEEKLY), ("scrape_schedule", WEEKLY | {"timezone": "Nowhere"})],
)
async def test_unknown_keys_and_invalid_values_are_rejected(
    client: httpx2.AsyncClient, key: str, value: dict[str, object]
) -> None:
    await sign_in(client, "alice")

    response = await client.put(f"/api/config/{key}", json=value, headers=FIRST)

    assert response.status_code == 422
