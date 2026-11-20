"""Request dependencies: the signed-in user, and role checks. Deny by default."""

from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request
from opentelemetry import trace
from pydantic import HttpUrl

from infrasales.auth import sessions
from infrasales.auth.cookies import session_token
from infrasales.auth.models import Role, User
from infrasales.auth.provider import AUTH_PROVIDER
from infrasales.core.db import Session
from infrasales.core.models import utcnow


def public_url(request: Request) -> HttpUrl:
    return AUTH_PROVIDER.get(request).public_url


async def _optional_user(request: Request, session: Session) -> User | None:
    token = session_token(request, public_url(request))
    user = await sessions.resolve(session, token, utcnow()) if token else None
    if user:
        structlog.contextvars.bind_contextvars(user=user.subject)
        trace.get_current_span().set_attribute("user.id", user.subject)  # a no-op untraced
    return user


OptionalUser = Annotated[User | None, Depends(_optional_user)]


async def _current_user(user: OptionalUser) -> User:
    if user is None:
        raise HTTPException(401, "Sign in first")
    return user


CurrentUser = Annotated[User, Depends(_current_user)]


async def _admin_user(user: CurrentUser) -> User:
    if user.role is not Role.ADMIN:
        raise HTTPException(403, "Admins only")
    return user


AdminUser = Annotated[User, Depends(_admin_user)]
