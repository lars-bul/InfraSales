"""Reading and changing the global configuration; every change is audited."""

import structlog
from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.audit import service as audit
from infrasales.config.models import ConfigEntry
from infrasales.config.schemas import ConfigEntryRead, ConfigKey, Schedule
from infrasales.core.db import Database, insert_if_absent
from infrasales.core.models import JSONValue, utcnow
from infrasales.scheduler.recurrence import next_occurrence

_log = structlog.stdlib.get_logger(__name__)

_KNOWN = frozenset(ConfigKey)


async def store_defaults(db: Database) -> list[ConfigKey]:
    """Store each setting's default where no value is stored yet (on startup); which were.

    Stored values are never replaced, and instances starting together store each default once.
    Defaults come from the code, not from anyone's change: they are logged, not audited. An
    unreachable database is logged, not raised: the app starts all the same, and the next start
    stores what is missing.
    """
    stored: list[ConfigKey] = []
    try:
        async with db.session() as session:
            for key in ConfigKey:
                value = key.default.model_dump(mode="json")
                if await insert_if_absent(
                    session, ConfigEntry, {"key": key, "value": value}, unique=["key"]
                ):
                    stored.append(key)
    except SQLAlchemyError:
        _log.warning("config.defaults_not_stored", exc_info=True)
        return []
    if stored:
        _log.info("config.defaults_stored", keys=stored)
    return stored


class StaleRevisionError(Exception):
    """The setting changed since the caller read it."""


def _read(entry: ConfigEntry) -> ConfigEntryRead:
    schedule = Schedule.model_validate(entry.value)
    return ConfigEntryRead(
        key=ConfigKey(entry.key),
        value=schedule,
        revision=entry.revision,
        updated_at=entry.updated_at,
        next_run_at=next_occurrence(schedule, utcnow()) if schedule.enabled else None,
    )


async def entries(session: AsyncSession) -> list[ConfigEntryRead]:
    """Every current setting, by key."""
    rows = (await session.exec(select(ConfigEntry).order_by(col(ConfigEntry.key)))).all()
    return [_read(row) for row in rows if row.key in _KNOWN]


async def entry(session: AsyncSession, key: ConfigKey) -> ConfigEntryRead | None:
    row = (await session.exec(select(ConfigEntry).where(col(ConfigEntry.key) == key))).first()
    return _read(row) if row else None


async def replace(
    session: AsyncSession, key: str, value: dict[str, JSONValue], *, revision: int
) -> tuple[ConfigEntry, dict[str, JSONValue]] | None:
    """Set `key` to `value` if it is still at `revision`: the row, and its value before.

    None if there is no such setting. The row stays locked until the transaction ends
    (PostgreSQL; SQLite's `BEGIN IMMEDIATE` serializes writers anyway), so concurrent changes
    apply one after the other.
    """
    locked = select(ConfigEntry).where(col(ConfigEntry.key) == key).with_for_update()
    row = (await session.exec(locked)).first()
    if row is None:
        return None
    if row.revision != revision:
        raise StaleRevisionError
    before = row.value
    row.value, row.revision = value, row.revision + 1
    session.add(row)
    await session.flush()  # sets updated_at
    return row, before


async def update(  # noqa: PLR0913  # the change, and who made it
    session: AsyncSession,
    key: ConfigKey,
    value: Schedule,
    *,
    revision: int,
    actor: str,
    request: Request,
) -> ConfigEntryRead | None:
    """Set `key` to `value` if it is still at `revision`; None if there is no such setting."""
    replaced = await replace(session, key, value.model_dump(mode="json"), revision=revision)
    if replaced is None:
        return None
    row, before = replaced
    details = {"before": before, "after": row.value}
    audit.record(
        session, actor=actor, action="config.updated", target=key, details=details, request=request
    )
    return _read(row)
