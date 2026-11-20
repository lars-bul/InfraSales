import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import ProgrammingError
from sqlmodel import SQLModel

from infrasales.core import grants, schema
from tests.helpers import postgres_only


def test_every_table_has_a_policy() -> None:
    schema.import_models()

    assert set(grants.POLICY) == {*SQLModel.metadata.tables, "alembic_version"}


def test_roles_lose_everything_then_get_what_the_policy_grants() -> None:
    result = grants.statements({"retention": "infrasales_retention"}, lambda name: f'"{name}"')

    assert result[:2] == [
        'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "infrasales_retention"',
        'GRANT USAGE ON SCHEMA public TO "infrasales_retention"',
    ]
    assert 'GRANT SELECT, INSERT, DELETE ON "audit_event" TO "infrasales_retention"' in result
    assert not any('"config_entry"' in statement for statement in result)  # never touches it


def test_grant_runs_the_statements_and_commits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def statements(*_: object) -> list[str]:
        return ["CREATE TABLE granted (id INTEGER)"]

    monkeypatch.setattr(grants, "statements", statements)

    grants.grant(f"sqlite+aiosqlite:///{tmp_path}/grants.db", {"app": "infrasales_app"})

    engine = create_engine(f"sqlite:///{tmp_path}/grants.db")
    assert inspect(engine).get_table_names() == ["granted"]
    engine.dispose()


def _as(role: str) -> str:
    variable = f"TEST_{role.upper()}_DATABASE_URL"
    return schema.sync_url(os.environ[variable]).render_as_string(hide_password=False)


@postgres_only
@pytest.mark.usefixtures("database_url")
@pytest.mark.parametrize(
    ("role", "statement"),
    [
        ("app", "UPDATE audit_event SET action = 'tampered'"),
        ("app", "DELETE FROM audit_event"),
        ("app", "DELETE FROM job_run"),
        ("app", "UPDATE job_step SET result = '{}'"),
        ("app", "DELETE FROM job_step"),  # what a run did stays recorded
        ("retention", "UPDATE config_entry SET value = '{}'"),
        ("retention", "SELECT * FROM config_entry"),
    ],
)
def test_roles_cannot_exceed_the_policy(role: str, statement: str) -> None:
    engine = create_engine(_as(role))

    with pytest.raises(ProgrammingError, match="permission denied"), engine.begin() as connection:
        connection.execute(text(statement))
    engine.dispose()


@postgres_only
@pytest.mark.usefixtures("database_url")
def test_the_app_can_check_the_schema_contract() -> None:
    """Readiness runs as the app: planning its probes' inserts needs INSERT on every table."""
    engine = create_engine(_as("app"))

    with engine.connect() as connection:
        assert schema.usable(connection)
    engine.dispose()


AUDIT_INSERT = (
    "INSERT INTO audit_event (id, created_at, updated_at, action, outcome, details)"
    " VALUES (gen_random_uuid(), now(), now(), 'test', 'success', '{}')"
)


@postgres_only
@pytest.mark.usefixtures("database_url")
@pytest.mark.parametrize(
    ("role", "statement"),
    [
        ("app", AUDIT_INSERT),
        ("app", "SELECT * FROM alembic_version"),
        ("app", "DELETE FROM feed WHERE false"),  # admins delete a Feed without Sources
        ("retention", "DELETE FROM audit_event WHERE created_at < now() - interval '1 day'"),
    ],
)
def test_roles_can_do_their_job(role: str, statement: str) -> None:
    engine = create_engine(_as(role))

    with engine.begin() as connection:
        connection.execute(text(statement))
    engine.dispose()


@postgres_only
def test_retention_deletes_a_finished_run_with_its_steps(database_url: str) -> None:
    owner = create_engine(schema.sync_url(database_url))
    with owner.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO job_run (id, created_at, updated_at, job, scheduled_for, status,"
                " attempts, run_after, trigger)"
                " VALUES (gen_random_uuid(), now(), now(), 'report', now(), 'succeeded', 1,"
                " now(), 'schedule')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO job_step (id, created_at, updated_at, run_id, name, result)"
                " SELECT gen_random_uuid(), now(), now(), id, 'write', '\"Hi\"' FROM job_run"
            )
        )
    retention = create_engine(_as("retention"))

    with retention.begin() as connection:
        connection.execute(text("DELETE FROM job_run"))
    with owner.begin() as connection:
        left = connection.execute(text("SELECT count(*) FROM job_step")).scalar_one()
    owner.dispose()
    retention.dispose()

    assert left == 0  # the cascade runs with the table owner's rights
