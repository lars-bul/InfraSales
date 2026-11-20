import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx2
import pytest
import structlog
from alembic import command
from pydantic import SecretStr

from infrasales.app import create_app
from infrasales.auth.settings import BasicAuthSettings
from infrasales.config.service import store_defaults
from infrasales.core import schema
from infrasales.core.db import Database
from infrasales.core.grants import grant
from infrasales.core.secrets import new_key
from infrasales.fetch import http
from infrasales.scheduler.settings import SchedulerSettings
from infrasales.settings import Settings
from infrasales.sink.settings import SinkSettings
from tests.helpers import PASSWORD, POSTGRES_URL, ROLES, app_url
from tests.scrape.support import Scraping, memory_sink_uri, scraping_world


@pytest.fixture(autouse=True)
def _isolated_logging() -> Iterator[None]:
    """Restore the root logger and structlog after tests that configure logging."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:], root.level = handlers, level
    structlog.reset_defaults()


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reaches the real web: the fetchers' resolver knows no host (fakes pass their own)."""

    async def no_dns(host: str) -> list[str]:
        raise OSError(host)

    monkeypatch.setattr(http, "resolve_host", no_dns)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def database_url(tmp_path: Path) -> Iterator[str]:
    """A migrated database per test, with the defaults startup stores.

    SQLite, or PostgreSQL (reset after each test).
    """
    url = POSTGRES_URL or f"sqlite+aiosqlite:///{tmp_path}/test.db"
    schema.upgrade(url)
    if POSTGRES_URL:
        grant(url, ROLES)
    asyncio.run(_store_defaults(url))
    yield url
    if POSTGRES_URL:
        command.downgrade(schema.alembic_config(url), "base")


async def _store_defaults(url: str) -> None:
    db = Database(url)
    try:
        await store_defaults(db)
    finally:
        await db.dispose()


@pytest.fixture
def settings(database_url: str) -> Settings:
    """The app's settings: on PostgreSQL it connects as its own role, as in production."""
    auth = BasicAuthSettings(provider="basic", password=SecretStr(PASSWORD))
    scheduler = SchedulerSettings(enabled=False)  # tests run the worker explicitly
    sink = SinkSettings(uri=memory_sink_uri())
    url = SecretStr(app_url(database_url))
    key = SecretStr(new_key())
    return Settings(database_url=url, auth=auth, scheduler=scheduler, sink=sink, secrets_key=key)


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx2.AsyncClient]:
    """The application with its lifespan, called in-process."""
    app = create_app(settings)
    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        yield client


@pytest.fixture
async def scraping(database_url: str) -> AsyncIterator[Scraping]:
    """The scrape job's world: the database (seeded Feeds disabled), a sink, a fake web."""
    async with scraping_world(database_url) as world:
        yield world
