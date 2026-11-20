"""The fetchers of one scrape run, by the name a Feed gives (`feed.fetcher`)."""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager

from infrasales.fetch.fetcher import Fetcher, FetcherName
from infrasales.fetch.http import USER_AGENT, HttpFetcher, Network, http_client
from infrasales.fetch.pacing import Budget, Pacer
from infrasales.fetch.robots import RobotsCache, obey


@asynccontextmanager
async def open_fetchers(
    network: Network, budget: Budget | None = None, robots: RobotsCache | None = None
) -> AsyncGenerator[Mapping[FetcherName, Fetcher]]:
    """Every fetcher, open for one run; closed (connections and all) when the block ends.

    Each obeys robots.txt (as `robots` keeps it; None: read for this run only) and pauses
    between requests to one site, within `budget`.
    """
    async with http_client(network) as client:
        obey(client, Pacer(network.clock, budget), USER_AGENT, robots or RobotsCache(network.clock))
        yield {FetcherName.HTTP: HttpFetcher(client)}
