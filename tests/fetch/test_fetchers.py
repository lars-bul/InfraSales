import pytest

from infrasales.fetch.fetcher import FetcherName
from infrasales.fetch.fetchers import open_fetchers
from infrasales.fetch.http import HttpFetcher
from tests.scrape.support import FakeWeb

pytestmark = pytest.mark.anyio


async def test_every_fetcher_a_feed_may_name_is_open_for_a_run() -> None:
    async with open_fetchers(FakeWeb().network()) as fetchers:
        assert set(fetchers) == set(FetcherName)
        assert isinstance(fetchers[FetcherName.HTTP], HttpFetcher)
