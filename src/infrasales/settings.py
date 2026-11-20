"""Configuration from the environment: each capability is chosen independently.

Values come from environment variables (nested sections use `__`, e.g. `AUTH__PROVIDER`) and
from secret files in /run/secrets (`/run/secrets/database_url`, `/run/secrets/auth__password`).
Profiles are env files in `profiles/` (gitignored, copied from their committed `.env.example`);
the application itself has no notion of dev or prod.
"""

from datetime import timedelta
from importlib.metadata import version
from typing import Self, override

from pydantic import (
    BaseModel,
    DirectoryPath,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    NestedSecretsSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from infrasales.ai.embeddings import EmbeddingSettings
from infrasales.ai.settings import ConnectionSettings, LLMSettings
from infrasales.alerts.settings import AlertSettings
from infrasales.auth.settings import AuthSettings
from infrasales.core.db import Pool
from infrasales.core.grants import Grantee
from infrasales.core.logs import LogFormat
from infrasales.core.secrets import SecretBox
from infrasales.mail.settings import SmtpSettings
from infrasales.scheduler.settings import SchedulerSettings
from infrasales.sink.settings import SinkSettings


class RetentionSettings(BaseModel):
    """How long data is kept (`RETENTION__*`); PRIVACY.md documents why."""

    audit_days: int = Field(default=180, ge=1)
    job_run_days: int = Field(default=90, ge=8)
    # None: Source Versions are kept for good, the evidence of every claim (ADR 06 §7). A period
    # is longer than a listed Source's longest wait for its next check (a week,
    # `infrasales.jobs.scrape`): a page its Feed still lists is never deleted between two checks.
    source_days: int | None = Field(default=None, ge=8)

    @property
    def audit_period(self) -> timedelta:
        return timedelta(days=self.audit_days)

    @property
    def job_run_period(self) -> timedelta:
        return timedelta(days=self.job_run_days)

    @property
    def source_period(self) -> timedelta | None:
        """How long a Source Version is kept after it stopped being current (ADR 03 §8)."""
        return None if self.source_days is None else timedelta(days=self.source_days)


class MaintenanceSettings(BaseSettings):
    """What every command needs: the database and logging. `migrate` and `prune` stop here."""

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        nested_model_default_partial_update=True,
        frozen=True,
        hide_input_in_errors=True,
        extra="ignore",
    )

    database_url: SecretStr
    database_pool: Pool = Field(default_factory=Pool)
    database_app_role: str | None = None
    database_retention_role: str | None = None
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    sink: SinkSettings = Field(default_factory=SinkSettings)  # retention deletes files too
    log_format: LogFormat = "json"
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _roles_need_postgresql(self) -> Self:
        roles = self.database_app_role or self.database_retention_role
        if roles and not self.database_url.get_secret_value().startswith("postgresql"):
            msg = "DATABASE_APP_ROLE and DATABASE_RETENTION_ROLE need PostgreSQL"
            raise ValueError(msg)
        return self

    def database_roles(self) -> dict[Grantee, str]:
        """The PostgreSQL roles to grant least privilege to, by what they are for."""
        roles: dict[Grantee, str | None] = {
            "app": self.database_app_role,
            "retention": self.database_retention_role,
        }
        return {grantee: role for grantee, role in roles.items() if role}

    @classmethod
    def load(cls) -> Self:
        """Read environment variables and secret files."""
        return cls()  # pyright: ignore[reportCallIssue]  # values come from the environment

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        secrets = NestedSecretsSettingsSource(
            file_secret_settings,
            secrets_dir="/run/secrets",  # tests pass `_secrets_dir=` to read another directory
            secrets_dir_missing="ok",
            secrets_nested_delimiter="__",
        )
        return init_settings, env_settings, secrets


class WebSettings(BaseModel):
    host: str = "127.0.0.1"  # WEB__HOST; the container image listens on 0.0.0.0
    port: int = 8000
    # Where browsers reach the app: https makes the session cookie Secure and `__Host-`.
    public_url: HttpUrl = HttpUrl("http://localhost:8000")
    frontend_dir: DirectoryPath | None = None  # the built UI; unset: API only
    api_docs: bool = False  # Swagger UI on /api/docs, for development; the contract: openapi.json

    @model_validator(mode="after")
    def _api_docs_only_on_localhost(self) -> Self:
        """Swagger UI runs a CDN's script: never on an app others reach, whatever else is set."""
        local = self.public_url.scheme == "http" and self.public_url.host in _LOCAL_HOSTS
        if self.api_docs and not local:
            msg = "WEB__API_DOCS is for development only: WEB__PUBLIC_URL must be http://localhost"
            raise ValueError(msg)
        return self


_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})


class WorkerSettings(MaintenanceSettings):
    """What the scheduler worker needs, inside `infrasales web` or alone (`infrasales worker`)."""

    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    secrets_key: SecretStr | None = None
    openrouter: ConnectionSettings = Field(default_factory=ConnectionSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    smtp: SmtpSettings | None = None
    alerts: AlertSettings = Field(default_factory=AlertSettings)
    otel_exporter_otlp_endpoint: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: HttpUrl = HttpUrl("https://cloud.langfuse.com")
    langfuse_tracing_environment: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,40}$")
    langfuse_release: str = Field(default_factory=lambda: version("infrasales"))  # e.g. a git SHA

    @field_validator("secrets_key")
    @classmethod
    def _a_fernet_key(cls, key: SecretStr | None) -> SecretStr | None:
        if key is not None:
            SecretBox(key)
        return key

    @model_validator(mode="after")
    def _keys_are_stored_encrypted(self) -> Self:
        if self.openrouter.api_key and not self.secrets_key:
            msg = "API keys are stored encrypted: set SECRETS_KEY (`infrasales secrets-key`)"
            raise ValueError(msg)
        return self

    def secret_box(self) -> SecretBox | None:
        return SecretBox(self.secrets_key) if self.secrets_key else None

    @field_validator("langfuse_tracing_environment")
    @classmethod
    def _not_reserved(cls, environment: str | None) -> str | None:
        if environment and environment.startswith("langfuse"):
            msg = "Langfuse reserves environments starting with 'langfuse'"
            raise ValueError(msg)
        return environment

    @model_validator(mode="after")
    def _mail_copies_end_before_a_run_can_change_workers(self) -> Self:
        if self.smtp and self.smtp.timeout_seconds >= self.scheduler.stop_margin_seconds:
            msg = (
                "SMTP__TIMEOUT_SECONDS must be below a quarter of SCHEDULER__LEASE_SECONDS:"
                " a mail copy in flight must end before another worker may take its run over"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _alert_mail_needs_smtp(self) -> Self:
        if self.alerts.recipients and not self.smtp:
            msg = "ALERTS__RECIPIENTS needs SMTP__HOST: alerts are mailed through it"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _langfuse_keys_come_in_pairs(self) -> Self:
        if bool(self.langfuse_public_key) != bool(self.langfuse_secret_key):
            msg = "set both LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY, or neither"
            raise ValueError(msg)
        return self


class Settings(WorkerSettings):
    """Everything the web server needs, one section per capability."""

    auth: AuthSettings  # AUTH__PROVIDER: no default, sign-in is always an explicit choice
    web: WebSettings = Field(default_factory=WebSettings)
