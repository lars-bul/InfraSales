import pytest

from infrasales.core.db import Database
from tests.scrape.support import stored_feeds

pytestmark = pytest.mark.anyio


async def test_no_feed_is_seeded_admins_add_them(database_url: str) -> None:
    db = Database(database_url)
    feeds = await stored_feeds(db)
    await db.dispose()

    assert feeds == []
