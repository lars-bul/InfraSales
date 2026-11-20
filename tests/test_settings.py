import re
from datetime import timedelta
from importlib.metadata import version
from pathlib import Path
from typing import get_args

import pytest
from dotenv import dotenv_values
from pydantic import BaseModel, SecretStr, ValidationError
from pydantic_ai import Agent

from infrasales.alerts.settings import AlertSettings
from infrasales.catalog.versions import RECHECK_AT_LEAST_EVERY
from infrasales.core.secrets import new_key
from infrasales.mail.settings import SmtpSettings
from infrasales.observability import start_telemetry
from infrasales.scheduler.settings import SchedulerSettings
from infrasales.settings import (
    MaintenanceSettings,
    RetentionSettings,
    Settings,
    WebSettings,
    WorkerSettings,
)


def test_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///env.db")
    monkeypatch.setenv("LOG_FORMAT", "console")

    settings = MaintenanceSettings.load()

    assert settings.database_url.get_secret_value() == "sqlite+aiosqlite:///env.db"
    assert settings.log_format == "console"
    assert settings.log_level == "INFO"
    assert "env.db" not in repr(settings)


def test_secret_files_fill_in_what_the_environment_lacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / "database_url").write_text("sqlite+aiosqlite:///secret.db")

    settings = MaintenanceSettings(_secrets_dir=tmp_path)  # pyright: ignore[reportCallIssue]

    assert settings.database_url.get_secret_value() == "sqlite+aiosqlite:///secret.db"


def test_the_database_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        MaintenanceSettings.load()


def test_database_roles_are_for_postgresql_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_APP_ROLE", "infrasales_app")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///x.db")
    with pytest.raises(ValidationError, match="need PostgreSQL"):
        MaintenanceSettings.load()

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://owner@db/infrasales")
    monkeypatch.setenv("DATABASE_RETENTION_ROLE", "infrasales_retention")

    roles = MaintenanceSettings.load().database_roles()

    assert roles == {"app": "infrasales_app", "retention": "infrasales_retention"}


def test_the_connection_budget_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://infrasales@db/infrasales")
    monkeypatch.setenv("DATABASE_POOL__SIZE", "8")
    monkeypatch.setenv("DATABASE_POOL__TIMEOUT_SECONDS", "3")

    pool = MaintenanceSettings.load().database_pool

    assert (pool.size, pool.overflow, pool.timeout_seconds) == (8, 5, 3)


def test_job_runs_outlive_a_week() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 8"):
        RetentionSettings(job_run_days=7)


CHECK_DAYS = RECHECK_AT_LEAST_EVERY.days


def test_source_versions_outlive_the_longest_wait_for_a_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page its Feed still lists is checked at least weekly: never deleted in between."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")
    monkeypatch.setenv("RETENTION__SOURCE_DAYS", "30")

    assert MaintenanceSettings.load().retention.source_period == timedelta(days=30)
    assert RetentionSettings().source_period is None  # kept for good (ADR 06 §7)
    with pytest.raises(ValidationError, match=f"greater than or equal to {CHECK_DAYS + 1}"):
        RetentionSettings(source_days=CHECK_DAYS)


def test_a_mail_copy_must_end_before_a_run_can_change_workers() -> None:
    database = SecretStr("sqlite+aiosqlite://")
    smtp = SmtpSettings(host="h", sender="r@x.org", recipients=["a@x.org"], timeout_seconds=15)

    with pytest.raises(ValidationError, match="SMTP__TIMEOUT_SECONDS must be below"):
        WorkerSettings(database_url=database, smtp=smtp)  # 60 s lease: a 15 s stop margin
    longer_lease = SchedulerSettings(lease_seconds=120)
    assert WorkerSettings(database_url=database, smtp=smtp, scheduler=longer_lease).smtp == smtp


def test_alerts_by_mail_need_an_smtp_server() -> None:
    with pytest.raises(ValidationError, match="ALERTS__RECIPIENTS needs SMTP__HOST"):
        WorkerSettings(
            database_url=SecretStr("sqlite+aiosqlite://"),
            alerts=AlertSettings(recipients=["ops@x.org"]),
        )


def test_langfuse_environments_follow_langfuses_naming_rules() -> None:
    database = SecretStr("sqlite+aiosqlite://")

    settings = WorkerSettings(database_url=database, langfuse_tracing_environment="development")

    assert settings.langfuse_release == version("infrasales")  # the app version, unless set
    for invalid in ("Production", "langfuse-internal", "x" * 41):
        with pytest.raises(ValidationError):
            WorkerSettings(database_url=database, langfuse_tracing_environment=invalid)


@pytest.mark.parametrize(
    "public_url",
    ["https://localhost:8000", "http://infrasales.uni.test", "https://infrasales.uni.test"],
)
def test_the_api_docs_are_refused_where_others_reach_the_app(public_url: str) -> None:
    """Swagger UI loads a CDN's script: never on an address that is not this machine's."""
    with pytest.raises(ValidationError, match="WEB__API_DOCS is for development only"):
        WebSettings.model_validate({"public_url": public_url, "api_docs": True})

    assert not WebSettings.model_validate({"public_url": public_url}).api_docs


@pytest.mark.parametrize(
    "public_url", ["http://localhost:8000", "http://127.0.0.1", "http://[::1]"]
)
def test_the_api_docs_may_be_served_on_localhost(public_url: str) -> None:
    assert WebSettings.model_validate({"public_url": public_url, "api_docs": True}).api_docs


PROFILES = Path(__file__).parent.parent / "profiles"
EXAMPLES = ["dev", "stack", "prod"]  # profiles/<name>.env.example, committed
STANDARD = {"OTEL_SERVICE_NAME", "OTEL_METRIC_EXPORT_INTERVAL"}  # read by the OpenTelemetry SDK


def _use_profile(monkeypatch: pytest.MonkeyPatch, profile: str) -> None:
    for name, value in dotenv_values(PROFILES / f"{profile}.env.example").items():
        monkeypatch.setenv(name, value or "")


def _variables(model: type[BaseModel], prefix: str = "") -> set[str]:
    """Every environment variable `model` reads: nested sections joined by `__`."""
    names: set[str] = set()
    for field, info in model.model_fields.items():
        name = f"{prefix}{field}".upper()
        sections = [kind for kind in _types(info.annotation) if issubclass(kind, BaseModel)]
        names |= set().union(*(_variables(kind, f"{name}__") for kind in sections)) or {name}
    return names


def _types(annotation: object) -> list[type]:
    """The classes an annotation may hold: through unions, Optional and Annotated."""
    if isinstance(annotation, type):
        return [annotation]
    return [kind for arg in get_args(annotation) for kind in _types(arg)]


COMPOSE = {"stack": "compose.yaml", "prod": "compose.prod.yaml"}  # the profile's stack


@pytest.mark.parametrize("profile", EXAMPLES)
def test_each_example_lists_every_variable_the_app_reads(profile: str) -> None:
    """Set or commented out: whoever fills a profile in sees every choice.

    A stack's retention service does not load the profile: its stack's compose file sets them.
    """
    text = (PROFILES / f"{profile}.env.example").read_text()
    listed = set(re.findall(r"^#? ?([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))
    if compose := COMPOSE.get(profile):
        services = (PROFILES.parent / compose).read_text()
        retention = services.split("\n  retention:", 1)[1].split("\n\n", 1)[0]
        listed |= set(re.findall(r"^ +(RETENTION__[A-Z_]+):", retention, flags=re.MULTILINE))

    assert sorted((_variables(Settings) | STANDARD) - listed) == []


@pytest.mark.parametrize("profile", COMPOSE)
def test_a_stacks_retention_settings_are_not_in_its_profile(profile: str) -> None:
    """The profile is the app's: retention settings there would be read by nothing."""
    text = (PROFILES / f"{profile}.env.example").read_text()

    assert re.findall(r"^#? ?(RETENTION__[A-Z_]+)=", text, flags=re.MULTILINE) == []


@pytest.mark.parametrize("profile", ["dev", "stack"])
def test_the_ready_made_profiles_need_no_secrets(
    monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///x.db")  # compose sets it for stack
    _use_profile(monkeypatch, profile)

    settings = WorkerSettings.load()

    assert settings.langfuse_public_key is None  # Langfuse stays off until keys are added
    assert settings.langfuse_tracing_environment == {"dev": "development"}.get(profile, profile)


def test_the_production_example_filled_in_is_a_production_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_profile(monkeypatch, "prod")
    blanks = {
        "AUTH__ISSUER": "https://idp.test",
        "AUTH__CLIENT_ID": "infrasales",
        "AUTH__CLIENT_SECRET": "secret",
        "AUTH__STATE_SECRET": "s" * 32,
        "AUTH__ADMIN_GROUPS": "infrasales-admins",
        "AUTH__VIEWER_GROUPS": "infrasales-users",
        "SECRETS_KEY": new_key(),
        "OPENROUTER__API_KEY": "sk-or-test",
        "LLM__MODEL": "a-model",
        "SMTP__HOST": "smtp.test",
        "SMTP__USERNAME": "infrasales",
        "SMTP__PASSWORD": "secret",
        "SMTP__SENDER": "infrasales@example.test",
        "SMTP__RECIPIENTS": "team@example.test",
        "ALERTS__RECIPIENTS": "ops@example.test",
    }
    for name, value in blanks.items():
        monkeypatch.setenv(name, value)

    settings = Settings.load()

    assert (settings.auth.provider, settings.llm.provider) == ("oidc", "openrouter")
    assert settings.secret_box() is not None
    assert settings.smtp
    assert settings.database_roles() == {
        "app": "infrasales_app",
        "retention": "infrasales_retention",
    }
    assert not settings.llm.trace_content  # production: no prompts in traces


def test_the_dev_profile_traces_to_langfuse_once_keys_are_added(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[dict[str, object]] = []

    def langfuse(**arguments: object) -> None:
        created.append(arguments)

    _use_profile(monkeypatch, "dev")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-dev")  # what one fills in
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-dev")
    monkeypatch.setattr("langfuse.Langfuse", langfuse)
    settings = WorkerSettings.load()

    telemetry = start_telemetry(settings)

    assert telemetry
    assert settings.llm.trace_content  # development: prompts and completions are traced
    resource = telemetry.tracer_provider.resource.attributes
    assert resource["langfuse.environment"] == "development"
    assert resource["langfuse.release"] == version("infrasales")
    assert created[0]["base_url"] == "https://cloud.langfuse.com"
    telemetry.shutdown()
    Agent.instrument_all(instrument=False)
