"""The FastAPI application: wiring only. Features own their routes, models and logic."""

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.metadata import version
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

from infrasales.ai import router as ai
from infrasales.ai import service as ai_service
from infrasales.ai.router import AI, AiContext
from infrasales.audit import router as audit
from infrasales.auth import router as auth
from infrasales.auth.provider import AUTH_PROVIDER, AuthProvider, load_provider
from infrasales.catalog import router as sources
from infrasales.config import router as config
from infrasales.config.service import store_defaults
from infrasales.core import health
from infrasales.core.context import RequestContextMiddleware
from infrasales.core.db import DATABASE, Database
from infrasales.core.errors import ErrorMiddleware, invalid_request
from infrasales.core.logs import configure_logging
from infrasales.core.security import SecurityMiddleware
from infrasales.feeds import router as feeds
from infrasales.forecast import router as forecast
from infrasales.jobs import router as jobs
from infrasales.jobs.catalog import catalog
from infrasales.observability import TELEMETRY, start_telemetry
from infrasales.scheduler.settings import SCHEDULER
from infrasales.scheduler.worker import WORKER, Worker
from infrasales.settings import Settings
from infrasales.sink.store import SINK, Sink
from infrasales.tenancy import router as company

TITLE = "InfraSales"
DOCS_SPEC = "/api/openapi.json"  # with WEB__API_DOCS only
# Swagger UI loads its script and styles from jsdelivr, runs one inline script and uses inline
# styles; only its page gets this policy, every other response keeps the strict one.
_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)


def api() -> APIRouter:
    """Every route; the same in every configuration, so `openapi.json` is one fixed contract.

    Each operation is named after its route function (`read_session`, not FastAPI's
    `read_session_api_auth_session_get`): short names for the generated frontend client.
    """
    router = APIRouter(generate_unique_id_function=lambda route: route.name)
    router.include_router(health.router)
    router.include_router(auth.router)
    router.include_router(audit.router)
    router.include_router(config.router)
    router.include_router(ai.router)
    router.include_router(jobs.router)
    router.include_router(feeds.router)
    router.include_router(jobs.feeds_router)  # the Feed overlap: told by the runs
    router.include_router(sources.router)
    router.include_router(forecast.router)
    router.include_router(company.router)
    return router


def openapi() -> dict[str, Any]:
    """The OpenAPI document the frontend's API types are generated from."""
    app = FastAPI(title=TITLE, version=version("infrasales"))
    app.include_router(api())
    return app.openapi()


def create_app(settings: Settings, provider: AuthProvider | None = None) -> FastAPI:
    """The app for `settings`; `provider` replaces the configured sign-in provider (tests)."""
    provider = provider or load_provider(settings.auth, settings.web.public_url)
    db = Database(settings.database_url.get_secret_value(), settings.database_pool)
    box = settings.secret_box()
    telemetry = start_telemetry(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Cleanup runs however the app stops, in reverse: worker, database, then telemetry."""
        async with AsyncExitStack() as stack:
            if telemetry:
                stack.callback(telemetry.shutdown)  # last: it still gets the others' spans
            stack.push_async_callback(db.dispose)
            await store_defaults(db)
            await ai_service.seed(db, settings, box)
            if settings.scheduler.enabled:  # off when `infrasales worker` runs on its own
                worker = Worker(db, catalog(settings, db), settings.scheduler, telemetry=telemetry)
                WORKER.set(app, await stack.enter_async_context(worker.running()))
            yield

    # The contract is `infrasales openapi`, checked into git; development may also browse it live.
    app = FastAPI(
        title=TITLE,
        version=version("infrasales"),
        docs_url=None,  # served by `_api_docs`, under its own CSP
        redoc_url=None,
        openapi_url=DOCS_SPEC if settings.web.api_docs else None,
        lifespan=lifespan,
    )
    DATABASE.set(app, db)
    SCHEDULER.set(app, settings.scheduler)
    SINK.set(app, Sink(settings.sink.uri))
    AI.set(app, AiContext(settings, box))
    AUTH_PROVIDER.set(app, provider)
    # Innermost first: error responses pass the security headers, and every response is logged.
    app.add_exception_handler(RequestValidationError, invalid_request)
    app.add_middleware(ErrorMiddleware)
    app.add_middleware(
        SecurityMiddleware,
        origin=str(settings.web.public_url),
        form_targets=provider.form_targets,
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(api())
    if settings.web.api_docs:
        app.add_api_route("/api/docs", _api_docs, include_in_schema=False)
    provider.install(app)
    if telemetry:
        telemetry.instrument(app)
        TELEMETRY.set(app, telemetry)
    if settings.web.frontend_dir:  # after the API: the UI's routes have the lowest priority
        app.frontend("/", directory=settings.web.frontend_dir, fallback="index.html")
    return app


async def _api_docs() -> HTMLResponse:
    """Swagger UI for `WEB__API_DOCS`, under its own CSP: the security middleware keeps it."""
    page = get_swagger_ui_html(openapi_url=DOCS_SPEC, title=f"{TITLE} API")
    page.headers["Content-Security-Policy"] = _DOCS_CSP
    return page


def from_environment() -> FastAPI:
    """The app configured from the environment: the factory `infrasales web --reload` serves."""
    settings = Settings.load()
    configure_logging(log_format=settings.log_format, level=settings.log_level)
    return create_app(settings)
