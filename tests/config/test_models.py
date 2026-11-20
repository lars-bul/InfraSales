import pytest
from sqlmodel import col, select

from infrasales.config.models import ConfigEntry
from infrasales.core.db import Database

pytestmark = pytest.mark.anyio


async def test_the_schedule_starts_with_its_default(database_url: str) -> None:
    """Stored on startup (`database_url` stores them as startup does), not by a migration."""
    db = Database(database_url)
    async with db.session() as session:
        rows = (await session.exec(select(ConfigEntry).order_by(col(ConfigEntry.key)))).all()
    await db.dispose()

    assert [
        (row.key, row.value["days"], row.value["time"], row.value["every_hours"], row.revision)
        for row in rows
    ] == [
        ("forecast_schedule", ["mon"], "05:00", None, 1),
        ("scrape_schedule", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "00:00", 3, 1),
    ]
