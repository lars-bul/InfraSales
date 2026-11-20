import io
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx2
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr
from pydantic_ai import Agent
from sqlmodel import delete

from infrasales import app as app_module
from infrasales.app import create_app, from_environment, openapi
from infrasales.config import service as config_service
from infrasales.config.models import ConfigEntry
from infrasales.config.schemas import ConfigKey
from infrasales.core import telemetry
from infrasales.core.db import Database
from infrasales.core.logs import configure_logging
from infrasales.scheduler.settings import SchedulerSettings
from infrasales.scheduler.worker import WORKER
from infrasales.settings import Settings, WebSettings
from tests.helpers import sign_in

pytestmark = pytest.mark.anyio
CONTRACT = Path(__file__).parent.parent / "openapi.json"


def test_the_checked_in_api_contract_is_current() -> None:
    assert json.loads(CONTRACT.read_text()) == openapi(), "run `make api-types`"


async def test_api_docs_are_not_served(client: httpx2.AsyncClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json", "/api/docs", "/api/openapi.json"):
        assert (await client.get(path)).status_code == 404


async def test_development_serves_the_api_docs_under_their_own_csp(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"web": WebSettings(api_docs=True)}))
    transport = httpx2.ASGITransport(app=app)

    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        docs = await client.get("/api/docs")
        spec = await client.get("/api/openapi.json")
        other = await client.get("/api/missing")

    assert docs.status_code == 200
    assert "/api/openapi.json" in docs.text
    assert "https://cdn.jsdelivr.net" in docs.headers["content-security-policy"]
    assert spec.json()["paths"].keys() >= openapi()["paths"].keys()
    assert "/api/docs" not in spec.json()["paths"]
    assert "cdn.jsdelivr.net" not in other.headers["content-security-policy"]


async def test_responses_are_hardened_and_traced(client: httpx2.AsyncClient) -> None:
    response = await client.get("/healthz")

    assert "content-security-policy" in response.headers
    assert "x-request-id" in response.headers


@pytest.mark.parametrize("origin", ["http://[", "http://testserver:x", "null"])
async def test_a_malformed_origin_is_rejected_like_any_cross_site_write(
    client: httpx2.AsyncClient, origin: str
) -> None:
    response = await client.post("/api/auth/logout", headers={"origin": origin})

    assert response.status_code == 403
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "x-request-id" in response.headers


async def test_error_responses_carry_the_security_headers_too(settings: Settings) -> None:
    configure_logging(stream=io.StringIO())
    app = create_app(settings)

    @app.get("/api/boom")
    async def boom() -> None:
        raise RuntimeError

    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/boom")

    assert response.status_code == 500
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


async def test_an_unreachable_database_answers_503_to_retry(
    settings: Settings, tmp_path: Path
) -> None:
    configure_logging(stream=io.StringIO())
    unreachable = SecretStr(f"sqlite+aiosqlite:///{tmp_path}/missing/infrasales.db")
    app = create_app(settings.model_copy(update={"database_url": unreachable}))

    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await sign_in(client, "alice")

    assert (response.status_code, response.headers["retry-after"]) == (503, "5")
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_the_ui_is_served_after_the_api(settings: Settings, tmp_path: Path) -> None:
    ui = tmp_path / "dist"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html><title>InfraSales</title>")
    (ui / "assets" / "app-1234.js").write_text("export {}")
    app = create_app(settings.model_copy(update={"web": WebSettings(frontend_dir=ui)}))
    transport = httpx2.ASGITransport(app=app)

    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        shell = await client.get("/")
        deep_link = await client.get("/schedules", headers={"accept": "text/html"})
        asset = await client.get("/assets/app-1234.js")
        api = await client.get("/api/missing", headers={"accept": "application/json"})
        probe = await client.get("/healthz")

    assert shell.text == deep_link.text == "<!doctype html><title>InfraSales</title>"
    assert deep_link.headers["cache-control"] == "no-cache"
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert api.status_code == 404
    assert probe.json() == {"status": "ok"}


async def test_the_reload_factory_reads_the_environment(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("AUTH__PROVIDER", "basic")
    monkeypatch.setenv("AUTH__PASSWORD", "test-password")
    monkeypatch.setenv("SCHEDULER__ENABLED", "false")

    app = from_environment()
    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        ready = await client.get("/readyz")

    assert ready.status_code == 200  # the configured, migrated database


async def test_the_scheduler_runs_inside_the_app_unless_disabled(settings: Settings) -> None:
    enabled = create_app(settings.model_copy(update={"scheduler": SchedulerSettings()}))
    disabled = create_app(settings)

    async with enabled.router.lifespan_context(enabled), disabled.router.lifespan_context(disabled):
        assert getattr(enabled.state, WORKER.name)
        assert not hasattr(disabled.state, WORKER.name)


async def test_a_failing_lifespan_still_closes_the_database_then_telemetry(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[str] = []

    class Recorded:
        def instrument(self, _: object) -> None:
            pass

        def shutdown(self) -> None:
            closed.append("telemetry")

    close = Database.dispose

    async def dispose(db: Database) -> None:
        closed.append("database")
        await close(db)  # startup used it: storing the defaults

    def start_telemetry(_: Settings) -> Recorded:
        return Recorded()

    monkeypatch.setattr(app_module, "start_telemetry", start_telemetry)
    monkeypatch.setattr(Database, "dispose", dispose)
    app = create_app(settings.model_copy(update={"scheduler": SchedulerSettings()}))

    with pytest.raises(RuntimeError):
        async with app.router.lifespan_context(app):
            raise RuntimeError  # e.g. a failed startup step after the worker began

    assert closed == ["database", "telemetry"]  # after the worker, in that order


# Imported only when configured: unused capabilities cost no memory (and no attack surface).
OPTIONAL = (
    "authlib",
    "itsdangerous",
    "joserfc",
    "infrasales.auth.providers.oidc",
    "openai",
    "pydantic_ai.providers.openai",
    "infrasales.ai.limits",
    "infrasales.mail.smtp",
    "smtplib",
    "infrasales.alerts.mail",
    "infrasales.alerts.webhook",
    "infrasales.core.telemetry",
    "opentelemetry.sdk",
    "langfuse",
)
_LIST_MODULES = """
import json, sys
from infrasales.app import from_environment
from infrasales.core.db import Database
from infrasales.jobs.catalog import catalog
from infrasales.settings import Settings
settings = Settings.load()
from_environment(), catalog(settings, Database(settings.database_url.get_secret_value()))
print("MODULES", json.dumps(sorted(sys.modules)))
"""


def _loaded(database_url: str, **env: str) -> set[str]:
    """Optional modules loaded by the app and its jobs, in a fresh interpreter."""
    environment = os.environ | {"DATABASE_URL": database_url, "LOG_FORMAT": "console"} | env
    command = [sys.executable, "-c", _LIST_MODULES]  # our own interpreter and script
    result = subprocess.run(command, env=environment, capture_output=True, text=True, check=True)
    (line,) = [line for line in result.stdout.splitlines() if line.startswith("MODULES ")]
    modules: list[str] = json.loads(line.removeprefix("MODULES "))
    return {name for name in modules if name.startswith(OPTIONAL)}


def test_unused_capabilities_are_not_even_imported(database_url: str) -> None:
    assert _loaded(database_url, AUTH__PROVIDER="basic", AUTH__PASSWORD="test-password") == set()


def test_configured_capabilities_are_imported(database_url: str) -> None:
    loaded = _loaded(
        database_url,
        AUTH__PROVIDER="oidc",
        AUTH__ISSUER="https://idp.test",
        AUTH__CLIENT_ID="infrasales",
        AUTH__CLIENT_SECRET="secret",
        AUTH__STATE_SECRET="s" * 32,
        AUTH__ADMIN_GROUPS="infrasales-admins",
        SMTP__HOST="smtp.test",
        SMTP__SENDER="infrasales@uni.test",
        SMTP__RECIPIENTS="a@uni.test",
        ALERTS__RECIPIENTS="ops@uni.test",
        ALERTS__WEBHOOK_URL="https://hooks.test/T",
        OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:4318",
        LANGFUSE_PUBLIC_KEY="pk-lf-test",
        LANGFUSE_SECRET_KEY="sk-lf-test",
    )

    roots = {name.partition(".")[0] for name in loaded}
    assert roots >= {"authlib", "smtplib", "langfuse", "opentelemetry", "infrasales"}
    assert {"infrasales.alerts.mail", "infrasales.alerts.webhook"} <= loaded


async def test_requests_are_traced_with_their_user_when_telemetry_is_on(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", lambda: exporter)
    configured = settings.model_copy(
        update={"otel_exporter_otlp_endpoint": "http://127.0.0.1:4318"}
    )
    app = create_app(configured)
    transport = httpx2.ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        await client.get("/api/auth/session")
        await sign_in(client, "alice")
        await client.get("/api/auth/session")
    Agent.instrument_all(instrument=False)

    sessions = [s for s in exporter.get_finished_spans() if s.name == "GET /api/auth/session"]
    anonymous, signed_in = (dict(span.attributes or {}).get("user.id") for span in sessions)
    assert (anonymous, signed_in) == (None, "basic:alice")


async def test_startup_stores_the_default_schedules(settings: Settings, database_url: str) -> None:
    """A fresh database gets its settings when the app starts, before the worker plans."""
    db = Database(database_url)
    async with db.session() as session:
        await session.exec(delete(ConfigEntry))
    app = create_app(settings)

    async with app.router.lifespan_context(app), db.session() as session:
        keys = [entry.key for entry in await config_service.entries(session)]
    await db.dispose()

    assert keys == [ConfigKey.FORECAST_SCHEDULE, ConfigKey.SCRAPE_SCHEDULE]
