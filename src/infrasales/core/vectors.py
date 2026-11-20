"""Vectors in the database: pgvector on PostgreSQL, sqlite-vec on SQLite, compared in SQL."""

import math
import struct
from collections.abc import Sequence
from typing import Any, cast, override

from sqlalchemy import BindParameter, ColumnElement, Dialect, Float, LargeBinary, bindparam
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.types import TypeDecorator, TypeEngine, UserDefinedType


class _PgVector(UserDefinedType[list[float]]):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    @override
    def get_col_spec(self, **_: object) -> str:
        return f"vector({self.dimensions})"

    @override
    def bind_expression(self, bindvalue: BindParameter[list[float]]) -> ColumnElement[list[float]]:
        return bindvalue.cast(self)


cast("dict[str, type[TypeEngine[Any]]]", ischema_names)["vector"] = _PgVector


class Vector(TypeDecorator[list[float]]):
    impl = LargeBinary
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        super().__init__()
        self.dimensions = dimensions

    @override
    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PgVector(self.dimensions))
        return dialect.type_descriptor(LargeBinary())

    @override
    def process_bind_param(self, value: list[float] | None, dialect: Dialect) -> object:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return f"[{','.join(map(str, value))}]"
        return struct.pack(f"<{len(value)}f", *value)

    @override
    def process_result_value(self, value: object, dialect: Dialect) -> list[float] | None:
        if isinstance(value, bytes):
            return list(struct.unpack(f"<{len(value) // 4}f", value))
        if isinstance(value, str):
            return [float(number) for number in value.strip("[]").split(",")]
        return None


class cosine_distance(FunctionElement[float]):  # noqa: N801
    type = Float()
    inherit_cache = True


@compiles(cosine_distance, "postgresql")
def _postgresql(element: cosine_distance, compiler: SQLCompiler, **kw: object) -> str:
    left, right = element.clauses
    return f"({compiler.process(left, **kw)} <=> {compiler.process(right, **kw)})"


@compiles(cosine_distance, "sqlite")
def _sqlite(element: cosine_distance, compiler: SQLCompiler, **kw: object) -> str:
    return f"vec_distance_cosine({compiler.process(element.clauses, **kw)})"


def vector(values: Sequence[float], dimensions: int) -> BindParameter[list[float]]:
    return bindparam(None, list(values), type_=Vector(dimensions))


def unit(values: Sequence[float], dimensions: int) -> list[float]:
    """The first `dimensions` values scaled to length 1: a Matryoshka embedding, shortened."""
    head = values[:dimensions]
    norm = math.sqrt(sum(value * value for value in head)) or 1.0
    return [value / norm for value in head]
