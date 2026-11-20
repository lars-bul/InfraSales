"""Database access: one async engine per process and short transactions."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Annotated

import aiosqlite
import sqlite_vec
from fastapi import Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import Connection, Table, TextClause, event, literal, make_url
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.core.state import StateKey

_SQLITE_PRAGMAS = ("journal_mode=WAL", "foreign_keys=ON")
_STOPPING_SECONDS = 5


class Pool(BaseModel):
    """Database connections per process (`DATABASE_POOL__*`), PostgreSQL only.

    Note: replicas of each process type times (size + overflow), plus `migrate` and
    retention, must stay below the server's `max_connections` (or go through PgBouncer).
    """

    size: int = Field(default=5, ge=1)  # kept open
    overflow: int = Field(default=5, ge=0)  # opened under load, closed when returned
    timeout_seconds: float = Field(default=10, gt=0)  # waiting for one, then 503 Retry-After


class Database:
    def __init__(self, url: str, pool: Pool | None = None) -> None:
        """The engine for `url`. SQLite has one writer anyway: its pool is not sized."""
        sqlite = url.startswith("sqlite")
        pool = pool or Pool()
        options: dict[str, object] = (
            {"async_creator": _sqlite_connector(url)}
            if sqlite
            else {
                "connect_args": {"connect_timeout": 5, "prepare_threshold": None},
                "pool_size": pool.size,
                "max_overflow": pool.overflow,
                "pool_timeout": pool.timeout_seconds,
            }
        )
        self.engine: AsyncEngine = create_async_engine(
            url,
            hide_parameters=True,
            pool_pre_ping=not sqlite,
            **options,
        )
        if sqlite:
            event.listen(self.engine.sync_engine, "connect", _sqlite_pragmas)
            event.listen(self.engine.sync_engine, "begin", _sqlite_begin)
        self._sessions = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        """Run a transaction: commit when the block ends, roll back if it raises."""
        async with self._sessions.begin() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()


async def insert_if_absent(
    session: AsyncSession,
    table: type[SQLModel],
    values: Mapping[str, object],
    unique: Sequence[str],
    where: TextClause | None = None,
) -> bool:
    """Insert a row unless one with the same `unique` columns exists; whether it was inserted."""
    statement = skip_conflicts(session.get_bind().dialect.name, table, values, unique, where)
    inserted = await session.exec(statement.returning(literal(1)))  # no row: skipped
    return inserted.first() is not None


def skip_conflicts(
    dialect: str,
    table: type[SQLModel] | Table,
    values: Mapping[str, object],
    unique: Sequence[str],
    where: TextClause | None = None,
) -> postgresql.Insert | sqlite.Insert:
    """`INSERT … ON CONFLICT (unique) [WHERE where] DO NOTHING` in `dialect`."""
    insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
    return (
        insert(table)
        .values(values)
        .on_conflict_do_nothing(index_elements=unique, index_where=where)
    )


def _sqlite_connector(url: str) -> Callable[[], Awaitable[aiosqlite.Connection]]:
    """Open connections to the SQLite database at `url`, none left unclosed by a cancellation.

    A connection that fails to open waits for its thread to stop: aiosqlite does not
    (omnilib/aiosqlite#394, fixed by #397), and the thread fails if the event loop closed first.
    """
    database = make_url(url).database or ":memory:"

    async def connect() -> aiosqlite.Connection:
        connection = aiosqlite.connect(database, isolation_level=None, timeout=15)
        thread = connection._thread  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
        thread.daemon = True
        opening = asyncio.ensure_future(connection)
        try:
            await asyncio.wait([opening])
        except asyncio.CancelledError:
            opening.add_done_callback(_close_abandoned)
            raise
        if opening.exception() is not None:
            await asyncio.to_thread(thread.join, _STOPPING_SECONDS)
        opened = opening.result()
        await opened.enable_load_extension(value=True)
        await opened.load_extension(sqlite_vec.loadable_path())
        await opened.enable_load_extension(value=False)
        return opened

    return connect


def _close_abandoned(opening: asyncio.Future[aiosqlite.Connection]) -> None:
    """Close a connection that opened after its caller had given up (aiosqlite ends failed ones)."""
    if not opening.cancelled() and opening.exception() is None:
        opening.result().stop()  # pyright: ignore[reportUnknownMemberType]


def _sqlite_pragmas(dbapi_connection: DBAPIConnection, _: object) -> None:
    cursor = dbapi_connection.cursor()
    for pragma in _SQLITE_PRAGMAS:
        cursor.execute(f"PRAGMA {pragma}")
    cursor.close()


def _sqlite_begin(connection: Connection) -> None:
    connection.exec_driver_sql("BEGIN IMMEDIATE")


DATABASE = StateKey[Database]("database")


def database(request: Request) -> Database:
    """The application's database, as a FastAPI dependency."""
    return DATABASE.get(request)


async def _session(db: Annotated[Database, Depends(database)]) -> AsyncGenerator[AsyncSession]:
    async with db.session() as session:
        yield session


Session = Annotated[AsyncSession, Depends(_session, scope="function")]
