import asyncio
import json
from datetime import timedelta
from pathlib import Path

import pytest
import structlog
import uvicorn
from fastapi import FastAPI
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr
from pydantic_ai import Agent
from sqlalchemy import create_engine, inspect
from sqlmodel import delete, select

from infrasales import retention
from infrasales.app import openapi
from infrasales.auth import sessions
from infrasales.auth.models import AuthSession, Role, User
from infrasales.cli import main
from infrasales.config import service as config_service
from infrasales.config.models import ConfigEntry
from infrasales.config.schemas import ConfigKey
from infrasales.core import grants, schema, telemetry
from infrasales.core.db import Database
from infrasales.core.models import utcnow
from infrasales.core.secrets import SecretBox
from infrasales.scheduler import worker
from tests.helpers import audit_actions, audit_events


def test_version_is_printed(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("infrasales 0.")


def test_a_command_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main([])

    assert "required: command" in capsys.readouterr().err


def test_migrate_applies_the_migrations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/cli.db")

    main(["migrate"])

    engine = create_engine(f"sqlite:///{tmp_path}/cli.db")
    tables = inspect(engine).get_table_names()
    engine.dispose()
    assert "alembic_version" in tables


def test_invalid_configuration_exits_with_the_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        main(["migrate"])

    assert exit_info.value.code == 2
    assert "database_url" in capsys.readouterr().err


def test_web_serves_the_app_with_proxy_aware_graceful_settings(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    calls: list[tuple[object, dict[str, object]]] = []

    def run(app: object, **options: object) -> None:
        calls.append((app, options))

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("AUTH__PROVIDER", "basic")
    monkeypatch.setenv("AUTH__PASSWORD", "test-password")
    monkeypatch.setenv("WEB__PORT", "8123")
    monkeypatch.setattr(uvicorn, "run", run)

    main(["web"])

    ((app, options),) = calls
    assert isinstance(app, FastAPI)
    assert options["port"] == 8123
    assert options["proxy_headers"] is True
    assert options["server_header"] is False
    assert options["reload"] is False

    main(["web", "--reload"])

    app, options = calls[1]
    assert app == "infrasales.app:from_environment"
    assert (options["factory"], options["reload"], options["reload_dirs"]) == (True, True, ["src"])


def test_openapi_prints_the_contract(capsys: pytest.CaptureFixture[str]) -> None:
    main(["openapi"])

    assert json.loads(capsys.readouterr().out) == openapi()


def test_worker_runs_the_scheduler_until_stopped(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    served: list[worker.Worker] = []

    async def serve(scheduler: worker.Worker) -> None:
        served.append(scheduler)
        await asyncio.sleep(0)

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.delenv("AUTH__PROVIDER", raising=False)  # the worker needs no sign-in settings
    monkeypatch.setattr(worker, "serve", serve)

    main(["worker"])

    assert len(served) == 1


def test_worker_flushes_its_telemetry_on_exit(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    spans, logs = InMemorySpanExporter(), InMemoryLogRecordExporter()

    async def serve(_: worker.Worker) -> None:
        structlog.stdlib.get_logger().info("serving")

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", lambda: spans)
    monkeypatch.setattr(telemetry, "OTLPLogExporter", lambda: logs)
    monkeypatch.setattr(worker, "serve", serve)

    main(["worker"])
    Agent.instrument_all(instrument=False)

    assert "serving" in str([record.log_record.body for record in logs.get_finished_logs()])


def test_migrate_grants_the_configured_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []

    def upgrade(url: str) -> None:
        calls.append(("upgrade", url))

    def grant(_: str, roles: object) -> None:
        calls.append(("grant", roles))

    url = "postgresql+psycopg://infrasales_owner@db.invalid/infrasales"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DATABASE_APP_ROLE", "infrasales_app")
    monkeypatch.setattr(schema, "upgrade", upgrade)
    monkeypatch.setattr(grants, "grant", grant)

    main(["migrate"])

    assert calls == [("upgrade", url), ("grant", {"app": "infrasales_app"})]


def test_prune_deletes_expired_rows_once(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)

    main(["prune"])

    actions = [event[1] for event in asyncio.run(audit_actions(database_url))]
    assert actions == ["retention.pruned"]


@pytest.mark.parametrize("every", ["24h", "15m", "30s", "7d"])
def test_prune_takes_an_interval(monkeypatch: pytest.MonkeyPatch, every: str) -> None:
    seen: list[object] = []

    async def run(_: object, __: object, ___: object, interval: object) -> None:
        seen.append(interval)

    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")
    monkeypatch.setattr(retention, "run", run)

    main(["prune", "--every", every])

    (interval,) = seen
    assert isinstance(interval, timedelta)
    assert interval > timedelta(0)


@pytest.mark.parametrize("every", ["0h", "1w", "soon"])
def test_prune_rejects_invalid_intervals(capsys: pytest.CaptureFixture[str], every: str) -> None:
    with pytest.raises(SystemExit):
        main(["prune", "--every", every])

    assert "positive duration" in capsys.readouterr().err


def test_revoke_ends_every_session_of_a_person_at_once(
    monkeypatch: pytest.MonkeyPatch, database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    asyncio.run(_sign_in_twice_and_once(database_url))

    main(["revoke", "oidc:removed-admin"])

    assert capsys.readouterr().out.endswith("2 session(s) of oidc:removed-admin ended\n")
    remaining = asyncio.run(_subjects(database_url))
    assert remaining == ["oidc:colleague"]
    (revoked,) = [e for e in asyncio.run(audit_events(database_url)) if e.action == "auth.revoked"]
    assert (revoked.actor, revoked.target, revoked.details) == (
        None,
        "oidc:removed-admin",
        {"sessions": 2},
    )


async def _sign_in_twice_and_once(database_url: str) -> None:
    db = Database(database_url)
    async with db.session() as session:
        for subject in ("oidc:removed-admin", "oidc:removed-admin", "oidc:colleague"):
            await sessions.start(
                session, User(subject=subject, name="x", role=Role.ADMIN), utcnow()
            )
    await db.dispose()


async def _subjects(database_url: str) -> list[str]:
    db = Database(database_url)
    async with db.session() as session:
        subjects = list((await session.exec(select(AuthSession.subject))).all())
    await db.dispose()
    return subjects


async def _settings_stored(database_url: str, *, clear: bool = False) -> list[ConfigKey]:
    db = Database(database_url)
    async with db.session() as session:
        if clear:
            await session.exec(delete(ConfigEntry))
        keys = [entry.key for entry in await config_service.entries(session)]
    await db.dispose()
    return keys


def test_the_worker_stores_missing_defaults_before_it_plans(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    planned_by: list[list[ConfigKey]] = []

    async def serve(_: worker.Worker) -> None:
        planned_by.append(await _settings_stored(database_url))

    asyncio.run(_settings_stored(database_url, clear=True))
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.delenv("AUTH__PROVIDER", raising=False)
    monkeypatch.setattr(worker, "serve", serve)

    main(["worker"])

    assert planned_by == [[ConfigKey.FORECAST_SCHEDULE, ConfigKey.SCRAPE_SCHEDULE]]


def test_secrets_key_prints_a_new_key_each_time(capsys: pytest.CaptureFixture[str]) -> None:
    main(["secrets-key"])
    main(["secrets-key"])

    first, second = capsys.readouterr().out.split()
    assert first != second
    box = SecretBox(SecretStr(first))
    assert box.open(box.seal("sk-test")) == "sk-test"


def test_the_worker_seeds_the_ai_settings_before_it_plans(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    seeded: list[list[str]] = []

    async def stored_keys() -> list[str]:
        db = Database(database_url)
        async with db.session() as session:
            keys = sorted((await session.exec(select(ConfigEntry.key))).all())
        await db.dispose()
        return keys

    async def serve(_: worker.Worker) -> None:
        seeded.append(await stored_keys())

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(worker, "serve", serve)

    main(["worker"])

    assert seeded == [
        [
            "ai_connection_openrouter",
            "ai_models",
            "forecast_schedule",
            "scrape_schedule",
        ]
    ]
