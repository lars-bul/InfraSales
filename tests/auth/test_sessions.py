from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from infrasales.auth import sessions
from infrasales.auth.models import AuthSession, Role, User
from infrasales.core.db import Database
from infrasales.core.models import utcnow

pytestmark = pytest.mark.anyio
ADMIN = User(subject="basic:alice", name="alice", role=Role.ADMIN)
VIEWER = User(subject="basic:vera", name="vera", role=Role.VIEWER)


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    yield db
    await db.dispose()


async def _start(db: Database, user: User, now: datetime) -> str:
    async with db.session() as session:
        return await sessions.start(session, user, now)


async def _resolve(db: Database, token: str, now: datetime) -> User | None:
    async with db.session() as session:
        return await sessions.resolve(session, token, now)


async def test_a_started_session_resolves_to_its_user(db: Database) -> None:
    token = await _start(db, ADMIN, utcnow())

    assert await _resolve(db, token, utcnow()) == ADMIN
    assert await _resolve(db, "unknown-token", utcnow()) is None


async def test_only_the_token_hash_is_stored(db: Database) -> None:
    token = await _start(db, VIEWER, utcnow())

    async with db.session() as session:
        stored = (await session.exec(select(AuthSession))).one()

    assert token not in stored.token_hash
    assert len(stored.token_hash) == 64


@pytest.mark.parametrize(
    ("user", "idle_limit"), [(ADMIN, timedelta(hours=1)), (VIEWER, timedelta(hours=8))]
)
async def test_idle_sessions_expire_sooner_for_admins(
    db: Database, user: User, idle_limit: timedelta
) -> None:
    start = utcnow()
    active, idle = await _start(db, user, start), await _start(db, user, start)

    assert await _resolve(db, active, start + idle_limit - timedelta(seconds=1)) == user
    assert await _resolve(db, idle, start + idle_limit) is None


async def test_sessions_end_at_their_absolute_lifetime_however_active(db: Database) -> None:
    start = utcnow()
    token = await _start(db, ADMIN, start)

    for step in range(1, 10):  # active every 50 minutes (within the 1 h idle timeout)
        assert await _resolve(db, token, start + step * timedelta(minutes=50)) == ADMIN
    assert await _resolve(db, token, start + timedelta(hours=8)) is None


async def test_activity_is_recorded_at_most_every_five_minutes(db: Database) -> None:
    start = utcnow()
    token = await _start(db, VIEWER, start)

    await _resolve(db, token, start + timedelta(minutes=4))
    async with db.session() as session:
        unchanged = (await session.exec(select(AuthSession))).one().last_seen_at
    await _resolve(db, token, start + timedelta(minutes=6))
    async with db.session() as session:
        touched = (await session.exec(select(AuthSession))).one().last_seen_at

    assert unchanged == start
    assert touched == start + timedelta(minutes=6)


async def test_ended_sessions_are_gone(db: Database) -> None:
    token = await _start(db, VIEWER, utcnow())

    async with db.session() as session:
        await sessions.end(session, token)

    assert await _resolve(db, token, utcnow()) is None
