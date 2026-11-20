import io
import logging

import pytest
from pydantic import HttpUrl, SecretStr, ValidationError
from pydantic_ai import Agent

from infrasales.core.logs import configure_logging
from infrasales.observability import start_telemetry
from infrasales.settings import WorkerSettings

DATABASE = SecretStr("sqlite+aiosqlite://")


def test_without_an_exporter_telemetry_stays_off() -> None:
    assert start_telemetry(WorkerSettings(database_url=DATABASE)) is None


def test_otlp_exports_traces_and_logs() -> None:
    configure_logging(stream=io.StringIO())  # the root logger is restored after the test
    settings = WorkerSettings(
        database_url=DATABASE, otel_exporter_otlp_endpoint="http://127.0.0.1:4318"
    )

    pipeline = start_telemetry(settings)

    assert pipeline
    assert len(logging.getLogger().handlers) == 2  # stdout and OTLP
    pipeline.shutdown()
    assert len(logging.getLogger().handlers) == 1  # OTLP's is detached: it stopped exporting


def test_langfuse_needs_both_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, object]] = []

    def langfuse(**arguments: object) -> None:
        created.append(arguments)

    monkeypatch.setattr("langfuse.Langfuse", langfuse)
    settings = WorkerSettings(
        database_url=DATABASE,
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key=SecretStr("sk-lf-test"),
    )

    pipeline = start_telemetry(settings)

    assert pipeline
    assert created[0]["base_url"] == "https://cloud.langfuse.com"
    pipeline.shutdown()
    Agent.instrument_all(instrument=False)
    with pytest.raises(ValidationError, match="LANGFUSE_SECRET_KEY"):
        WorkerSettings(database_url=DATABASE, langfuse_public_key="pk-lf-test")


def test_a_self_hosted_langfuse_gets_its_url_without_a_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SDK appends `/api/public/otel/...`: a double slash got redirected, losing spans."""
    created: list[dict[str, object]] = []

    def langfuse(**arguments: object) -> None:
        created.append(arguments)

    monkeypatch.setattr("langfuse.Langfuse", langfuse)
    settings = WorkerSettings(
        database_url=DATABASE,
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key=SecretStr("sk-lf-test"),
        langfuse_base_url=HttpUrl("https://langfuse.example.org/"),
    )

    pipeline = start_telemetry(settings)

    assert pipeline
    assert created[0]["base_url"] == "https://langfuse.example.org"
    pipeline.shutdown()
    Agent.instrument_all(instrument=False)
