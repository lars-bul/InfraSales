import uuid
from collections.abc import AsyncIterator

import pytest

from infrasales.core.db import Database
from infrasales.tenancy.context import SETTING, bind, policy_sql
from tests.helpers import POSTGRES_URL

pytestmark = pytest.mark.anyio


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    yield db
    await db.dispose()


def test_a_private_table_is_under_row_level_security_by_tenant() -> None:
    statements = policy_sql("bid")

    assert statements[:2] == [
        "ALTER TABLE bid ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE bid FORCE ROW LEVEL SECURITY",
    ]
    assert f"current_setting('{SETTING}', true)" in statements[2]
    assert "WITH CHECK" in statements[2]


async def test_binding_is_a_no_op_without_postgresql(db: Database) -> None:
    if POSTGRES_URL:
        pytest.skip("SQLite only")
    async with db.session() as session:
        await bind(session, uuid.uuid4())  # nothing to set, nothing raised
