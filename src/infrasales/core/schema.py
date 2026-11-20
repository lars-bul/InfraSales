"""Schema migrations (Alembic): apply them, and generate new ones from model changes.

`make migrate` autogenerates a revision; the hooks here keep generated scripts clean:
sequential ids (0001, 0002, ...), a message derived from the changes when none is given, no
empty revisions, and plain SQLAlchemy types (migrations never import application code).
"""

import importlib
import pkgutil
import warnings
from collections.abc import Iterable, Iterator
from functools import cache
from typing import Literal, cast

from alembic import command
from alembic.autogenerate.api import AutogenContext
from alembic.config import Config
from alembic.operations.ops import MigrationScript
from alembic.runtime.environment import ProcessRevisionDirectiveFn
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import msg
from sqlalchemy import URL, Connection, Table, TextClause, UniqueConstraint, inspect, make_url
from sqlalchemy.engine.interfaces import ReflectedColumn
from sqlalchemy.exc import DBAPIError
from sqlalchemy.types import TypeDecorator
from sqlmodel import SQLModel

import infrasales
from infrasales.core.db import Database, skip_conflicts
from infrasales.core.models import JSONType

_INDEX_CHANGES = ("add index", "remove index")


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", "infrasales:migrations")
    config.attributes["url"] = url  # not a main option: avoids ConfigParser %-interpolation
    return config


def upgrade(url: str) -> None:
    """Migrate the database at `url` to the newest revision."""
    config = alembic_config(url)
    check_history(config)
    command.upgrade(config, "head")


def check_history(config: Config) -> ScriptDirectory:
    """The migration scripts, refusing two with the same revision ID.

    Revision IDs are sequential, so two branches may both generate the next one. Alembic would
    only warn and silently skip one of the two migrations; this refuses to go on instead.
    """
    script = ScriptDirectory.from_config(config)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("error", r"Revision \S+ is present more than once")
            script.get_heads()  # reads every script
    except UserWarning as duplicate:
        msg = (
            f"{duplicate}: two branches generated the same migration number. In the branch "
            "merged second, delete that migration, rebase, and run `make migrate` again."
        )
        raise RuntimeError(msg) from duplicate
    return script


@cache
def revisions() -> tuple[str | None, frozenset[str]]:
    """This build's newest revision and every revision it knows."""
    script = check_history(alembic_config(""))
    return script.get_current_head(), frozenset(r.revision for r in script.walk_revisions())


async def current_revision(db: Database) -> str | None:
    """The revision the database is migrated to; raises if the database is unreachable."""
    async with db.engine.connect() as connection:
        return await connection.run_sync(
            lambda sync: MigrationContext.configure(sync).get_current_revision()
        )


async def suits_build(db: Database) -> bool:
    """Whether this build can serve with the database's schema (readiness).

    At this build's head: yes. Not migrated, or at an older revision this build knows: no,
    `migrate` has not run. At a revision this build does not know, a newer build migrated it
    during a rolling deploy: yes only if the schema is still `usable` by this build.
    """
    head, known = revisions()
    revision = await current_revision(db)
    if revision == head:
        return True
    if revision is None or revision in known:
        return False
    async with db.engine.connect() as connection:
        return await connection.run_sync(usable)


def usable(connection: Connection) -> bool:
    """Whether this build can work with the schema: expand/contract, checked, not assumed.

    The structural contract a newer build's migrations must keep for an older one: every table
    and column the build uses exists, and so does every index and unique constraint it defines,
    by name; each unique one still enforces the same uniqueness, which the database itself
    decides (`arbitrates`); a column the build may leave empty still accepts NULL, as the build
    writes NULL there explicitly (a default does not help); and every column it does not know
    can be left out of its inserts (nullable, or with a server default). Column types are not
    compared: a migration only widens a type in place (a longer VARCHAR), and otherwise adds a
    new column.
    """
    import_models()
    inspector = inspect(connection)
    dialect = connection.dialect

    def omissible(column: ReflectedColumn) -> bool:
        return column["nullable"] or column.get("default") is not None

    def unique_keys(table: Table) -> list[tuple[list[str], TextClause | None]]:
        """The columns of each unique index and constraint, with a partial index's predicate."""
        where = f"{dialect.name}_where"
        indexes = [
            ([column.name for column in index.columns], index.dialect_kwargs.get(where))
            for index in table.indexes
            if index.unique
        ]
        return indexes + [
            ([column.name for column in constraint.columns], None)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        ]

    def arbitrates(table: Table, columns: list[str], where: TextClause | None) -> bool:
        """Whether the database still takes a unique index as these conflicts' arbiter.

        It plans the build's own insert (EXPLAIN: nothing runs), which it refuses without a
        unique index on exactly these columns and, for a partial index, this predicate: a
        definition changed under the old name fails too.
        """
        values = dict.fromkeys(columns)
        statement = skip_conflicts(dialect.name, table, values, columns, where)
        sql = statement.compile(dialect=dialect, compile_kwargs={"literal_binds": True})
        try:
            with connection.begin_nested():  # a refusal must not end the transaction
                connection.exec_driver_sql(f"EXPLAIN {sql}")
        except DBAPIError:
            return False
        return True

    def usable_table(table: Table) -> bool:
        if not inspector.has_table(table.name):
            return False
        columns = {column["name"]: column for column in inspector.get_columns(table.name)}
        if not set(table.columns.keys()) <= columns.keys():
            return False
        named = {index["name"] for index in inspector.get_indexes(table.name)} | {
            unique["name"] for unique in inspector.get_unique_constraints(table.name)
        }
        needed = {index.name for index in table.indexes} | {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        may_stay_empty = [columns[column.name] for column in table.columns if column.nullable]
        unknown = [column for name, column in columns.items() if name not in table.columns]
        return (
            needed <= named
            and all(column["nullable"] for column in may_stay_empty)
            and all(map(omissible, unknown))
            and all(arbitrates(table, *key) for key in unique_keys(table))
        )

    return all(usable_table(table) for table in SQLModel.metadata.sorted_tables)


def import_models() -> None:
    """Import every `infrasales.<feature>.models` module, so that all tables join the metadata."""
    for module in pkgutil.walk_packages(infrasales.__path__, "infrasales."):
        if module.name.endswith(".models"):
            importlib.import_module(module.name)


def sync_url(url: str) -> URL:
    """The same database through a synchronous driver: Alembic runs synchronously."""
    parsed = make_url(url)
    return parsed.set(drivername="sqlite") if parsed.get_backend_name() == "sqlite" else parsed


def serialize(connection: Connection) -> None:
    """PostgreSQL: concurrent `migrate` runs wait for each other, DDL gives up on locks after 5 s.

    A migration waiting for a lock queues every later query on that table behind it.
    """
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtext('infrasales.migrate'))")
        connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")


def render_item(type_: str, obj: object, autogen_context: AutogenContext) -> str | Literal[False]:
    """Render application column types as the plain SQLAlchemy types they store."""
    if type_ != "type" or not isinstance(obj, TypeDecorator):
        return False
    if isinstance(obj, JSONType):
        autogen_context.imports.add("from sqlalchemy.dialects import postgresql")
        return 'sa.JSON().with_variant(postgresql.JSONB(), "postgresql")'
    return f"sa.{cast('TypeDecorator[object]', obj).impl_instance!r}"


def revision_directives(config: Config) -> ProcessRevisionDirectiveFn:
    """Name revisions 0001, 0002, ...; skip empty autogenerated ones and describe the rest."""

    def process(_: MigrationContext, __: object, directives: list[MigrationScript]) -> None:
        script = directives[0]
        if getattr(config.cmd_opts, "autogenerate", False) and script.upgrade_ops:
            if script.upgrade_ops.is_empty():
                msg("No model changes: no migration written.")
                directives.clear()
                return
            script.message = script.message or describe(script.upgrade_ops.as_diffs())
        head = check_history(config).get_current_head()
        script.rev_id = f"{int(head or 0) + 1:04d}"

    return process


def describe(diffs: Iterable[object]) -> str:
    """Name changes like `add table auth_session` or `add column job_run trigger`.

    Index changes only count when nothing else changed: they accompany new tables and columns.
    """
    names = list(dict.fromkeys(_describe(diff) for diff in _flatten(diffs)))
    return " ".join([name for name in names if not name.startswith(_INDEX_CHANGES)] or names)


def _flatten(diffs: Iterable[object]) -> Iterator[tuple[object, ...]]:
    for diff in diffs:
        if isinstance(diff, list):  # column modifications come grouped per column
            yield from cast("list[tuple[object, ...]]", diff)
        else:
            yield cast("tuple[object, ...]", diff)


def _describe(diff: tuple[object, ...]) -> str:
    action, *targets = diff
    names = [t if isinstance(t, str) else getattr(t, "name", None) for t in targets]
    verb = str(action).replace("_", " ")  # "add_column" → "add column"
    return " ".join([verb, *[name for name in names if isinstance(name, str)][:2]])
