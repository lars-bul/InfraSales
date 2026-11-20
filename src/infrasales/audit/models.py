"""The audit trail: who did what, when, with which outcome. Append-only and pseudonymous."""

from enum import StrEnum

from sqlalchemy import Index
from sqlmodel import Field

from infrasales.core.models import SUBJECT_LENGTH, BaseTable, JSONType, JSONValue, enum_type


class Outcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class AuditEvent(BaseTable, table=True):
    """One accountable action. `created_at` is when it happened; ids are time-ordered.

    Personal data is limited to the pseudonymous actor and a truncated client network: no
    names, e-mail addresses or free text from users (see PRIVACY.md).
    """

    __table_args__ = (Index("ix_audit_event_created_at", "created_at"),)  # retention

    actor: str | None = Field(default=None, max_length=SUBJECT_LENGTH, index=True)  # None: system
    action: str = Field(max_length=64, index=True)  # "<area>.<verb>", e.g. "config.updated"
    outcome: Outcome = Field(default=Outcome.SUCCESS, sa_type=enum_type(Outcome))
    target: str | None = Field(default=None, max_length=SUBJECT_LENGTH)  # a key, a subject
    details: dict[str, JSONValue] = Field(default_factory=dict[str, JSONValue], sa_type=JSONType)
    client_network: str | None = Field(default=None, max_length=49)  # /24 or /48, never the IP
