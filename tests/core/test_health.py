from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine

from infrasales.app import create_app
from infrasales.core import schema
from infrasales.settings import Settings

pytestmark = pytest.mark.anyio


async def test_liveness_does_not_touch_the_database(client: httpx2.AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.json() == {"status": "ok"}


async def test_ready_once_migrated(client: httpx2.AsyncClient) -> None:
    response = await client.get("/readyz")

    assert (response.status_code, response.json()) == (200, {"status": "ready"})


@pytest.mark.parametrize("database", ["missing-dir/test.db", "unmigrated.db"])
async def test_not_ready_when_unreachable_or_not_migrated(
    settings: Settings, tmp_path: Path, database: str
) -> None:
    url = SecretStr(f"sqlite+aiosqlite:///{tmp_path}/{database}")
    app = create_app(settings.model_copy(update={"database_url": url}))
    transport = httpx2.ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        response = await client.get("/readyz")

    assert (response.status_code, response.json()) == (503, {"status": "unavailable"})


async def test_not_ready_for_a_newer_schema_this_build_cannot_use(
    settings: Settings, tmp_path: Path
) -> None:
    """A newer build migrated the database and dropped a table this build reads."""
    url = f"sqlite+aiosqlite:///{tmp_path}/contracted.db"
    schema.upgrade(url)
    engine = create_engine(schema.sync_url(url))
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE alembic_version SET version_num = '9999'")
        connection.exec_driver_sql("DROP TABLE config_entry")
    engine.dispose()
    app = create_app(settings.model_copy(update={"database_url": SecretStr(url)}))
    transport = httpx2.ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        response = await client.get("/readyz")

    assert response.status_code == 503
