from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from infrasales.audit.models import Outcome
from infrasales.core.models import SUBJECT_LENGTH, JSONValue


class AuditEventRead(BaseModel):
    """An audit event as admins see it: without the client network."""

    id: UUID
    created_at: datetime
    actor: str | None
    action: str
    outcome: Outcome
    target: str | None
    details: dict[str, JSONValue]


class AuditQuery(BaseModel):
    """Which events to read: a page back from `before`, narrowed down by exact matches."""

    limit: int = Field(default=50, ge=1, le=200)
    before: UUID | None = None  # older than this event: a full page may have more behind it
    action: str | None = Field(default=None, max_length=64, examples=["auth.login"])
    actor: str | None = Field(default=None, max_length=SUBJECT_LENGTH)  # e.g. "oidc:<sub>"
