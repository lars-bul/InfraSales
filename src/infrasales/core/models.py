"""Shared table definitions: the base table, portable column types and constraint names."""

import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from functools import cache
from typing import override

from sqlalchemy import JSON, DateTime, Dialect, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declared_attr
from sqlalchemy.types import TypeDecorator, TypeEngine
from sqlmodel import Field, SQLModel

# Deterministic constraint names
SQLModel.metadata.naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


# A person's ID, "<provider>:<their ID there>", as sessions, audit records and job runs store
# it: room for "oidc:" and an OpenID Connect `sub` of at most 255 characters.
SUBJECT_LENGTH = 260

type JSONValue = str | int | float | bool | Sequence[JSONValue] | Mapping[str, JSONValue] | None


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Aware UTC datetimes on every dialect (SQLite drops the offset; it is restored on read)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    @override
    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            msg = "naive datetimes are not allowed"
            raise ValueError(msg)
        return value.astimezone(UTC) if value else None

    @override
    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class JSONType(TypeDecorator[object]):
    """JSON on SQLite, JSONB on PostgreSQL."""

    impl = JSON
    cache_ok = True

    @override
    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[object]:
        return dialect.type_descriptor(JSONB() if dialect.name == "postgresql" else JSON())


@cache
def enum_type[E: StrEnum](enum: type[E]) -> type[TypeDecorator[E]]:
    """A column type storing `enum` by value in a plain string column (no native enum types).

    Use it as `Field(sa_type=enum_type(Status))`: reading the column returns the enum again.
    """

    class EnumString(TypeDecorator[E]):
        impl = String(32)
        cache_ok = True

        @override
        def process_bind_param(self, value: E | str | None, dialect: Dialect) -> str | None:
            return None if value is None else enum(value).value

        @override
        def process_result_value(self, value: str | None, dialect: Dialect) -> E | None:
            return None if value is None else enum(value)

    EnumString.__name__ = f"{enum.__name__}String"
    return EnumString


def _snake_case(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class BaseTable(SQLModel):
    """Base of every table: a time-ordered UUID key and creation/update timestamps.

    The `sa_column_kwargs` defaults also apply to SQL-level inserts and updates, which bypass
    the Python-side `default_factory`.
    """

    id: uuid.UUID = Field(
        default_factory=uuid.uuid7, primary_key=True, sa_column_kwargs={"default": uuid.uuid7}
    )
    created_at: datetime = Field(
        default_factory=utcnow, sa_type=UTCDateTime, sa_column_kwargs={"default": utcnow}
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"default": utcnow, "onupdate": utcnow},
    )

    # One snake_case name per table class (`AuditEvent` → `audit_event`).
    @declared_attr  # pyright: ignore[reportArgumentType]
    def __tablename__(cls) -> str:  # noqa: N805  # pyright: ignore[reportIncompatibleVariableOverride]
        return cls.table_name()

    @classmethod
    def table_name(cls) -> str:
        """The table's name, typed (SQLAlchemy's `__tablename__` is not)."""
        return _snake_case(cls.__name__)
