"""A run's progress across its attempts: what an earlier attempt already did.

A retried job starts again from the top; steps let it skip what was done before. The report
is written once, not again by the model, and copies already mailed are not mailed again.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import ColumnElement
from sqlmodel import col, select

from infrasales.core.db import Database, insert_if_absent
from infrasales.core.models import JSONValue
from infrasales.scheduler.models import JobStep


class StepResultError(Exception):
    """A step's stored result no longer has the shape the job expects of it."""

    def __init__(self, name: str, returns: object) -> None:
        super().__init__(
            f"step {name!r} holds a result that is no {returns}: a step whose result changes"
            " shape needs a new name"
        )


class Steps:
    def __init__(self, db: Database, run_id: UUID) -> None:
        self._db = db
        self._run_id = run_id

    async def once[T](self, name: str, work: Callable[[], Awaitable[T]], *, returns: type[T]) -> T:
        """`work`'s result: computed by the first attempt to get here, reused by later ones."""
        result = TypeAdapter(returns)
        async with self._db.session() as session:
            done = (await session.exec(select(JobStep).where(self._named(name)))).first()
        stored = (
            done.result
            if done is not None
            else await self.record(name, result.dump_python(await work(), mode="json"))
        )
        try:
            return result.validate_python(stored)
        except ValidationError as error:
            raise StepResultError(name, returns) from error

    async def recorded(self, prefix: str) -> frozenset[str]:
        """The names of this run's steps that start with `prefix`."""
        starts = col(JobStep.name).startswith(prefix, autoescape=True)
        query = select(JobStep.name).where(col(JobStep.run_id) == self._run_id, starts)
        async with self._db.session() as session:
            return frozenset((await session.exec(query)).all())

    async def record(self, name: str, result: JSONValue = None) -> JSONValue:
        """Record `name` as done; the result first recorded for it (attempts may overlap)."""
        values = {"run_id": self._run_id, "name": name, "result": result}
        async with self._db.session() as session:
            await insert_if_absent(session, JobStep, values, unique=["run_id", "name"])
            return (await session.exec(select(JobStep).where(self._named(name)))).one().result

    def _named(self, name: str) -> ColumnElement[bool]:
        return (col(JobStep.run_id) == self._run_id) & (col(JobStep.name) == name)
