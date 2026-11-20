from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from infrasales.auth.models import AuthSession, Role, User
from infrasales.core.db import Database
from infrasales.core.models import utcnow


def test_users_are_immutable() -> None:
    user = User(subject="basic:alice", name="alice", role=Role.ADMIN)

    with pytest.raises(ValidationError):
        user.role = Role.VIEWER  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.anyio
async def test_session_roles_are_stored_by_value(database_url: str) -> None:
    db = Database(database_url)
    now = utcnow()
    row = AuthSession(
        token_hash="0" * 64,
        subject="basic:alice",
        name="alice",
        role=Role.ADMIN,
        last_seen_at=now,
        expires_at=now + timedelta(hours=1),
    )
    async with db.session() as session:
        session.add(row)
    async with db.session() as session:
        stored = await session.get_one(AuthSession, row.id)
        raw = await (await session.connection()).execute(text("SELECT role FROM auth_session"))
    await db.dispose()

    assert stored.role is Role.ADMIN
    assert raw.scalar_one() == "admin"
