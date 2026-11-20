from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path

import pytest
from sqlalchemy import insert
from sqlalchemy.dialects import postgresql, sqlite
from sqlmodel import Field, SQLModel, select

from infrasales.core.db import Database
from infrasales.core.models import BaseTable, JSONType, UTCDateTime, enum_type, utcnow


class Color(StrEnum):
    RED = "red"


class ProbeRecord(BaseTable, table=True):
    color: Color = Field(sa_type=enum_type(Color))
    data: dict[str, int] = Field(default_factory=dict[str, int], sa_type=JSONType)


# Test tables never join the application's metadata: migrations must not see them.
PROBE_TABLE = SQLModel.metadata.tables["probe_record"]
SQLModel.metadata.remove(PROBE_TABLE)


def test_utcnow_is_aware() -> None:
    assert utcnow().tzinfo is UTC


def test_utc_datetimes_are_normalized_and_naive_ones_rejected() -> None:
    column = UTCDateTime()
    dialect = sqlite.dialect()
    berlin = datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=1)))

    assert column.process_bind_param(berlin, dialect) == datetime(2026, 1, 1, 11, tzinfo=UTC)
    assert column.process_bind_param(None, dialect) is None
    with pytest.raises(ValueError, match="naive"):
        column.process_bind_param(datetime(2026, 1, 1), dialect)  # noqa: DTZ001
    assert column.process_result_value(datetime(2026, 1, 1), dialect) == datetime(  # noqa: DTZ001
        2026, 1, 1, tzinfo=UTC
    )
    assert column.process_result_value(berlin, dialect) == berlin.astimezone(UTC)
    assert column.process_result_value(None, dialect) is None


def test_json_is_jsonb_on_postgresql() -> None:
    assert isinstance(JSONType().load_dialect_impl(postgresql.dialect()), postgresql.JSONB)
    assert not isinstance(JSONType().load_dialect_impl(sqlite.dialect()), postgresql.JSONB)


def test_enums_are_stored_by_value_and_read_back_as_enums() -> None:
    column = enum_type(Color)()

    assert enum_type(Color) is enum_type(Color)
    assert enum_type(Color).__name__ == "ColorString"
    assert column.process_bind_param(Color.RED, sqlite.dialect()) == "red"
    assert column.process_bind_param(None, sqlite.dialect()) is None
    assert column.process_result_value("red", sqlite.dialect()) is Color.RED
    assert column.process_result_value(None, sqlite.dialect()) is None


def test_table_names_are_snake_case() -> None:
    assert PROBE_TABLE.name == ProbeRecord.table_name() == "probe_record"


@pytest.mark.anyio
async def test_base_table_keys_and_timestamps(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with db.engine.begin() as connection:
        await connection.run_sync(PROBE_TABLE.create)
    record = ProbeRecord(color=Color.RED)
    async with db.session() as session:
        session.add(record)
        # SQL-level inserts get the same defaults as ORM inserts.
        await session.exec(insert(ProbeRecord).values(color=Color.RED))
    async with db.session() as session:
        stored = await session.get_one(ProbeRecord, record.id)
        stored.data = {"changed": 1}
    async with db.session() as session:
        rows = (await session.exec(select(ProbeRecord))).all()
    await db.dispose()

    assert len(rows) == 2
    assert all(row.id.version == 7 and row.created_at.tzinfo is UTC for row in rows)
    updated = next(row for row in rows if row.id == record.id)
    assert updated.color is Color.RED
    assert updated.data == {"changed": 1}
    assert updated.updated_at > updated.created_at
