"""Shared test helpers."""

import os
from collections.abc import Awaitable, Callable
from typing import cast

import httpx2
import pytest
from sqlalchemy import event, text
from sqlmodel import col, select

from infrasales.audit.models import AuditEvent
from infrasales.core.db import Database
from infrasales.core.grants import Grantee

# `make test-pg` runs everything against PostgreSQL: infrasales_test, as its owner; code under test
# that runs as the app in production connects as the app's role (`app_url`).
POSTGRES_URL = os.environ.get("TEST_DATABASE_URL")
postgres_only = pytest.mark.skipif(not POSTGRES_URL, reason="needs PostgreSQL: make test-pg")
sqlite_only = pytest.mark.skipif(bool(POSTGRES_URL), reason="SQLite specifics")
ROLES: dict[Grantee, str] = {"app": "infrasales_app", "retention": "infrasales_retention"}


def app_url(database_url: str) -> str:
    """The test database as the app sees it: on PostgreSQL its role, with only what it is granted.

    The app's API and jobs under test connect through this, so a statement production would
    refuse (`infrasales.core.grants`) fails the test too; on SQLite, which has no roles, the
    same URL.
    """
    if not POSTGRES_URL:
        return database_url
    url = os.environ.get("TEST_APP_DATABASE_URL")
    if not url:
        msg = "TEST_APP_DATABASE_URL must be set with TEST_DATABASE_URL: make test-pg"
        raise RuntimeError(msg)
    return url


PASSWORD = "test-password"
SAME_ORIGIN = {"sec-fetch-site": "same-origin"}  # what browsers send for the app's own requests


async def sign_in(
    client: httpx2.AsyncClient, username: str, password: str = PASSWORD
) -> httpx2.Response:
    """Sign in through the built-in form; the client keeps the session cookie."""
    form = {"username": username, "password": password}
    return await client.post("/api/auth/login", data=form, headers=SAME_ORIGIN)


async def audit_events(database_url: str) -> list[AuditEvent]:
    """Every audit event, oldest first."""
    db = Database(database_url)
    async with db.session() as session:
        events = (await session.exec(select(AuditEvent).order_by(col(AuditEvent.id)))).all()
    await db.dispose()
    return list(events)


async def audit_actions(database_url: str) -> list[tuple[str | None, str, str]]:
    """(actor, action, outcome) of every audit event, oldest first."""
    return [(e.actor, e.action, e.outcome.value) for e in await audit_events(database_url)]


async def fill(db: Database, *statements: str) -> None:
    """Run SQL to fill tables (e.g. a long history), then refresh the planner's statistics."""
    async with db.session() as session:
        connection = await session.connection()
        for statement in statements:
            await connection.execute(text(statement))
        await connection.execute(text("ANALYZE"))


async def query_plan(db: Database, action: Callable[[], Awaitable[object]], *prefixes: str) -> str:
    """PostgreSQL's plans of the first statement per prefix (e.g. `DELETE FROM x`) in `action`."""
    executed: dict[str, tuple[str, dict[str, object]]] = {}

    def capture(*args: object) -> None:
        _, _, statement, parameters, *_ = args
        for prefix in prefixes:
            if str(statement).startswith(prefix):
                executed.setdefault(prefix, (str(statement), cast("dict[str, object]", parameters)))

    event.listen(db.engine.sync_engine, "before_cursor_execute", capture)
    try:
        await action()
    finally:
        event.remove(db.engine.sync_engine, "before_cursor_execute", capture)
    async with db.session() as session:
        connection = await session.connection()
        plans = [
            (await connection.exec_driver_sql(f"EXPLAIN {statement}", parameters)).all()
            for statement, parameters in (executed[prefix] for prefix in prefixes)
        ]
    return "\n".join(str(row[0]) for plan in plans for row in plan)
