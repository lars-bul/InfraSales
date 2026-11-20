"""Alembic environment: online migrations through a synchronous engine, SQLite or PostgreSQL."""

from alembic import context
from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel

from infrasales.core import schema
from infrasales.settings import MaintenanceSettings


def _run() -> None:
    schema.import_models()
    config = context.config
    url = config.attributes.get("url") or MaintenanceSettings.load().database_url.get_secret_value()
    engine = create_engine(schema.sync_url(url), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection, connection.begin():
            schema.serialize(connection)
            context.configure(
                connection=connection,
                target_metadata=SQLModel.metadata,
                render_as_batch=True,  # SQLite alters tables by rebuilding them
                compare_type=True,
                render_item=schema.render_item,
                process_revision_directives=schema.revision_directives(config),
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


_run()
