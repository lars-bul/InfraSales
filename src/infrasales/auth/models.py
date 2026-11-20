"""Who is signed in: roles, the user, and the server-side session table."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel
from sqlmodel import Field

from infrasales.core.models import SUBJECT_LENGTH, BaseTable, UTCDateTime, enum_type


class Role(StrEnum):
    VIEWER = "viewer"  # sees the configuration
    ADMIN = "admin"  # changes it, triggers jobs, reads the audit log


class User(BaseModel, frozen=True):
    subject: str  # stable, pseudonymous: "basic:alice", "oidc:<sub>"; the audit actor
    name: str
    role: Role


class AuthSession(BaseTable, table=True):
    """A signed-in browser. The cookie holds a random token; only its SHA-256 is stored here.

    No e-mail or profile data: the session holds what the UI shows, and expires.
    """

    token_hash: str = Field(max_length=64, unique=True)
    subject: str = Field(max_length=SUBJECT_LENGTH, index=True)
    name: str = Field(max_length=255)
    role: Role = Field(sa_type=enum_type(Role))
    last_seen_at: datetime = Field(sa_type=UTCDateTime, index=True)  # retention: idle sessions
    expires_at: datetime = Field(sa_type=UTCDateTime, index=True)
