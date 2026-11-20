import asyncio
import io
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlmodel import col, delete
from starlette.requests import Request

from infrasales.config import service
from infrasales.config.models import ConfigEntry
from infrasales.config.schemas import ConfigEntryRead, ConfigKey, Schedule, Weekday
from infrasales.core.db import Database
from infrasales.core.logs import configure_logging
from tests.helpers import audit_events

pytestmark = pytest.mark.anyio
KEY = ConfigKey.SCRAPE_SCHEDULE
FRIDAYS = Schedule(days=[Weekday.FRI], time="17:30", timezone="America/New_York", enabled=False)
MONDAYS = Schedule(days=[Weekday.MON], time="07:00", timezone="Europe/Berlin")
REQUEST = Request({"type": "http", "client": ("203.0.113.9", 1)})


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    yield db
    await db.dispose()


async def test_entries_are_validated_and_unknown_keys_skipped(db: Database) -> None:
    async with db.session() as session:
        session.add(ConfigEntry(key="retired_setting", value={"anything": 1}))
    async with db.session() as session:
        entries = await service.entries(session)

    assert [entry.key for entry in entries] == [
        ConfigKey.FORECAST_SCHEDULE,
        ConfigKey.SCRAPE_SCHEDULE,
    ]
    assert entries[1].value.days == list(Weekday)


async def _update(
    db: Database, value: Schedule, revision: int, *, locked: asyncio.Event | None = None
) -> ConfigEntryRead | None:
    """Change the scrape schedule; with `locked`, keep the transaction open until it is set."""
    async with db.session() as session:
        entry = await service.update(
            session, KEY, value, revision=revision, actor="basic:alice", request=REQUEST
        )
        if locked:
            locked.set()
            await asyncio.sleep(0.2)  # hold the row while a concurrent change comes in
    return entry


async def test_updates_change_the_value_and_audit_before_and_after(
    db: Database, database_url: str
) -> None:
    async with db.session() as session:
        before = await service.entry(session, KEY)

    updated = await _update(db, FRIDAYS, revision=1)

    assert before is not None
    assert updated is not None
    assert (updated.value, updated.revision) == (FRIDAYS, 2)
    assert updated.updated_at > before.updated_at
    (audit_event,) = await audit_events(database_url)
    assert (audit_event.actor, audit_event.action, audit_event.target) == (
        "basic:alice",
        "config.updated",
        "scrape_schedule",
    )
    assert audit_event.details["before"] == before.value.model_dump(mode="json")
    assert audit_event.details["after"] == FRIDAYS.model_dump(mode="json")


async def test_an_edit_of_an_older_revision_changes_nothing(
    db: Database, database_url: str
) -> None:
    await _update(db, FRIDAYS, revision=1)

    with pytest.raises(service.StaleRevisionError):
        await _update(db, MONDAYS, revision=1)  # edited the first revision: would lose Friday

    async with db.session() as session:
        current = await service.entry(session, KEY)
    assert current is not None
    assert (current.value, current.revision) == (FRIDAYS, 2)
    assert len(await audit_events(database_url)) == 1


async def test_concurrent_edits_of_one_revision_apply_once(db: Database, database_url: str) -> None:
    """Two admins save at once: one wins, the other is told; the audit trail stays exact."""
    locked = asyncio.Event()
    first = asyncio.create_task(_update(db, FRIDAYS, revision=1, locked=locked))
    await locked.wait()

    with pytest.raises(service.StaleRevisionError):
        await _update(db, MONDAYS, revision=1)  # waits for the first, then sees revision 2

    await first
    (audit_event,) = await audit_events(database_url)
    assert audit_event.details["after"] == FRIDAYS.model_dump(mode="json")


async def test_consecutive_edits_audit_each_exact_transition(
    db: Database, database_url: str
) -> None:
    locked = asyncio.Event()
    first = asyncio.create_task(_update(db, FRIDAYS, revision=1, locked=locked))
    await locked.wait()

    await _update(db, MONDAYS, revision=2)  # based on the first change: applies after it
    await first

    first_event, second_event = await audit_events(database_url)
    assert second_event.details["before"] == first_event.details["after"]
    assert second_event.details["after"] == MONDAYS.model_dump(mode="json")


async def test_a_missing_entry_is_not_created(db: Database) -> None:
    async with db.session() as session:
        await session.exec(delete(ConfigEntry).where(col(ConfigEntry.key) == KEY))

    assert await _update(db, FRIDAYS, revision=1) is None


async def test_startup_stores_each_missing_default_and_keeps_stored_values(db: Database) -> None:
    async with db.session() as session:
        await session.exec(delete(ConfigEntry).where(col(ConfigEntry.key) == KEY))

    stored = await service.store_defaults(db)
    await _update(db, FRIDAYS, 1)  # an admin changed the schedule
    again = await service.store_defaults(db)  # the next start, or another instance

    async with db.session() as session:
        entries = {entry.key: entry.value for entry in await service.entries(session)}
    assert (stored, again) == ([KEY], [])
    assert entries[KEY] == FRIDAYS
    assert entries[ConfigKey.FORECAST_SCHEDULE] == ConfigKey.FORECAST_SCHEDULE.default


async def test_defaults_an_unreachable_database_cannot_take_are_logged(tmp_path: Path) -> None:
    """The app starts all the same; the next start stores what is missing."""
    stream = io.StringIO()
    configure_logging(stream=stream)
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/missing/infrasales.db")  # cannot be opened

    stored = await service.store_defaults(db)
    await db.dispose()

    assert stored == []
    assert "config.defaults_not_stored" in stream.getvalue()
