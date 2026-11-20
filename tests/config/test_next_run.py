"""Each setting tells when its job runs next; the rules themselves are in test_recurrence."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx2
import pytest

from infrasales.core.models import utcnow
from tests.helpers import SAME_ORIGIN, sign_in

pytestmark = pytest.mark.anyio
BERLIN = ZoneInfo("Europe/Berlin")
FIRST = SAME_ORIGIN | {"if-match": '"1"'}  # every setting starts at revision 1
EVERY_DAY = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAILY = {"days": EVERY_DAY, "time": "17:30", "timezone": "Europe/Berlin", "enabled": True}


async def _next_run_as_viewer(client: httpx2.AsyncClient, schedule: Mapping[str, object]) -> object:
    """Save `schedule` as the scrape schedule (as an admin), then read its next run as a viewer."""
    await sign_in(client, "alice")
    saved = await client.put("/api/config/scrape_schedule", json=schedule, headers=FIRST)
    assert saved.status_code == 200
    await sign_in(client, "vera")
    entries = (await client.get("/api/config")).json()
    return next(entry for entry in entries if entry["key"] == "scrape_schedule")["next_run_at"]


async def test_a_daily_schedule_runs_next_at_its_time_within_a_day(
    client: httpx2.AsyncClient,
) -> None:
    before = utcnow()

    next_run = datetime.fromisoformat(str(await _next_run_as_viewer(client, DAILY)))

    assert before < next_run <= utcnow() + timedelta(days=1, hours=1)  # DST: a day may be 25 h
    assert next_run.astimezone(BERLIN).strftime("%H:%M") == "17:30"


async def test_a_repeating_schedule_runs_next_at_its_next_repetition(
    client: httpx2.AsyncClient,
) -> None:
    before = utcnow()
    every_3_hours = DAILY | {"time": "00:00", "every_hours": 3}

    next_run = datetime.fromisoformat(str(await _next_run_as_viewer(client, every_3_hours)))

    assert before < next_run <= utcnow() + timedelta(hours=4)  # DST: a gap may be 4 h
    local = next_run.astimezone(BERLIN)
    assert (local.hour % 3, local.minute) == (0, 0)


async def test_a_disabled_schedule_has_no_next_run(client: httpx2.AsyncClient) -> None:
    assert await _next_run_as_viewer(client, DAILY | {"enabled": False}) is None


async def test_a_changed_setting_comes_back_with_its_next_run(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "alice")

    response = await client.put(
        "/api/config/scrape_schedule", json=DAILY | {"enabled": False}, headers=FIRST
    )

    assert response.json()["next_run_at"] is None
