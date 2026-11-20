import os

import pytest
from sqlalchemy import exc
from sqlmodel import delete

from infrasales.catalog.models import SourceVersion
from infrasales.core.db import Database
from infrasales.scheduler.models import JobRun
from tests.helpers import postgres_only
from tests.scrape.support import RSS, Entry, Scraping, article_page, rss_feed, stored_sources
from tests.scrape.support import stored_versions as stored

pytestmark = pytest.mark.anyio


async def scraped_once(scraping: Scraping) -> SourceVersion:
    article = "https://news.test/story"
    scraping.web.serve(article, article_page("Story", "The authority decided today."))
    scraping.web.serve("https://news.test/feed", rss_feed(Entry(article)), media_type=RSS)
    await scraping.add_feed("news", "https://news.test/feed")
    await scraping.run_now()
    (version,) = await stored(scraping.db)
    return version


async def test_a_source_has_one_version_per_number(scraping: Scraping) -> None:
    """The unique key stops a second writer numbering a version the same."""
    first = await scraped_once(scraping)
    twin = SourceVersion.model_validate(first.model_dump(exclude={"id"}) | {"storage_key": "x"})

    with pytest.raises(exc.IntegrityError):
        async with scraping.db.session() as session:
            session.add(twin)


@postgres_only
async def test_the_retention_role_deletes_runs_and_versions_their_references_become_null(
    scraping: Scraping,
) -> None:
    """Job runs are pruned long before the versions they wrote; a deleted latest version."""
    version = await scraped_once(scraping)
    retention = Database(os.environ["TEST_RETENTION_DATABASE_URL"])  # its own role
    try:
        async with retention.session() as session:
            await session.exec(delete(JobRun))
        (kept,) = await stored(scraping.db)
        async with retention.session() as session:
            await session.exec(delete(SourceVersion))
    finally:
        await retention.dispose()

    assert (kept.id, kept.run_id) == (version.id, None)
    (source,) = await stored_sources(scraping.db)
    assert source.latest_version_id is None
