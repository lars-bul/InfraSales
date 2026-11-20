"""Server-side sessions: revocable at once, with idle and absolute timeouts (shorter for admins).

Functions run in the caller's transaction, so a sign-in commits together with its audit event.
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.auth.models import AuthSession, Role, User

# (idle timeout, absolute lifetime) per role
TIMEOUTS = {
    Role.VIEWER: (timedelta(hours=8), timedelta(hours=24)),
    Role.ADMIN: (timedelta(hours=1), timedelta(hours=8)),
}
TOUCH_INTERVAL = timedelta(minutes=5)  # bounds writes: last_seen_at moves at most this often


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def start(session: AsyncSession, user: User, now: datetime) -> str:
    """Start a session for `user`; return the token for the cookie."""
    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            token_hash=_hash(token),
            subject=user.subject,
            name=user.name,
            role=user.role,
            last_seen_at=now,
            expires_at=now + TIMEOUTS[user.role][1],
        )
    )
    return token


async def resolve(session: AsyncSession, token: str, now: datetime) -> User | None:
    """The session's user, or None if the token is unknown, expired or idle too long."""
    query = select(AuthSession).where(col(AuthSession.token_hash) == _hash(token))
    row = (await session.exec(query)).first()
    if row is None or row.expires_at <= now or row.last_seen_at <= now - TIMEOUTS[row.role][0]:
        return None
    if now - row.last_seen_at >= TOUCH_INTERVAL:
        row.last_seen_at = now
    return User(subject=row.subject, name=row.name, role=row.role)


async def end(session: AsyncSession, token: str) -> None:
    await session.exec(delete(AuthSession).where(col(AuthSession.token_hash) == _hash(token)))


async def revoke(session: AsyncSession, subject: str) -> int:
    """End every session of `subject` at once, e.g. after a role was taken away; how many."""
    ended = await session.exec(delete(AuthSession).where(col(AuthSession.subject) == subject))
    return ended.rowcount
