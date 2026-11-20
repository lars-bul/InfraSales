import asyncio
import contextlib
import gc
import logging
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import QueuePool, text

from infrasales.core.db import Database, Pool

pytestmark = pytest.mark.anyio


async def test_sqlite_runs_in_wal_mode_with_foreign_keys(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/test.db")

    async with db.session() as session:
        connection = await session.connection()
        journal = (await connection.execute(text("PRAGMA journal_mode"))).scalar_one()
        foreign_keys = (await connection.execute(text("PRAGMA foreign_keys"))).scalar_one()
    await db.dispose()

    assert (journal, foreign_keys) == ("wal", 1)


async def _insert_then_fail(db: Database) -> None:
    async with db.session() as session:
        connection = await session.connection()
        await connection.execute(text("INSERT INTO item VALUES ('discarded')"))
        raise RuntimeError


async def test_a_session_commits_on_success_and_rolls_back_on_error(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with db.session() as session:
        connection = await session.connection()
        await connection.execute(text("CREATE TABLE item (name TEXT)"))
        await connection.execute(text("INSERT INTO item VALUES ('kept')"))
    with pytest.raises(RuntimeError):
        await _insert_then_fail(db)

    async with db.session() as session:
        connection = await session.connection()
        names = (await connection.execute(text("SELECT name FROM item"))).scalars().all()
    await db.dispose()

    assert names == ["kept"]


async def test_postgresql_engines_are_created_without_connecting() -> None:
    db = Database("postgresql+psycopg://user:secret@db.invalid/infrasales")

    assert db.engine.dialect.name == "postgresql"
    await db.dispose()


async def test_postgresql_connections_are_budgeted_sqlite_needs_no_pool() -> None:
    budget = Pool(size=3, overflow=2, timeout_seconds=4)
    postgresql = Database(
        "postgresql+psycopg://infrasales@db.example/infrasales", budget
    )  # not connected
    sqlite = Database("sqlite+aiosqlite://", Pool(size=50))  # accepted, and ignored

    pool = cast("QueuePool", postgresql.engine.pool)
    size, timeout = pool.size(), pool.timeout()
    await postgresql.dispose()
    await sqlite.dispose()

    assert (size, timeout) == (3, 4)


async def _cancelled_while_connecting(db: Database) -> None:
    """A query whose caller is cancelled while its connection is still being opened."""

    async def query() -> None:
        async with db.session() as session:
            await (await session.connection()).execute(text("SELECT 1"))

    task = asyncio.create_task(query())
    await asyncio.sleep(0)  # it runs up to opening a connection, in aiosqlite's thread
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_a_connection_opened_for_a_cancelled_query_is_closed(tmp_path: Path) -> None:
    """Left unclosed, it would be finalized later: a ResourceWarning, an error in any test."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/test.db")

    for _ in range(3):  # each opens a connection of its own: none was ever pooled
        await _cancelled_while_connecting(db)
    await asyncio.sleep(0.1)  # the abandoned connections open, then close, in their threads
    gc.collect()

    async with db.session() as session:  # the database is none the worse for it
        assert (await (await session.connection()).execute(text("SELECT 1"))).scalar_one() == 1
    await db.dispose()


async def test_a_connection_failing_to_open_for_a_cancelled_query_is_no_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/missing/test.db")  # cannot be opened

    await _cancelled_while_connecting(db)
    await asyncio.sleep(0.1)
    gc.collect()
    await db.dispose()

    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]  # nothing unretrieved
