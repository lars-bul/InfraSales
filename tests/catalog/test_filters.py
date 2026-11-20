"""The Source API's filters and its count, on Sources stored straight into the catalog.

Five Sources under Feeds of three categories, their last changes days apart; listed
newest change first. `test_router.py` covers the run filter on what the scrape job stores.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from sqlmodel import col, select

from infrasales.catalog.models import Source, SourceVersion, VersionState
from infrasales.catalog.urls import url_hash
from infrasales.core.db import Database
from infrasales.feeds.models import Feed, FeedCategory, FeedKind
from tests.helpers import sign_in

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)


@dataclass(frozen=True)
class Stored:
    """A Source as stored: its Feed, its committed versions' ages, whether the latest is partial."""

    url: str
    feed: str  # its Feed's slug: the Feed is made with the first Source under it
    ages: tuple[timedelta, ...]  # how long ago each committed version was fetched, oldest first
    partial: bool = False
    title: str | None = None


# Oldest change first, as they are stored: version IDs (UUIDv7) then follow the changes.
GRANT = Stored(
    "https://rp.test/foerderbescheid",
    "regierungspraesidium",
    (timedelta(days=60), timedelta(days=40)),
)
HEAT_PLAN = Stored(
    "https://swu.test/waermeplan", "stadtwerke-ulm", (timedelta(days=10),), title="Waermeplan"
)
DECISION = Stored(
    "https://zfk.test/ratsbeschluss",
    "zfk",
    (timedelta(days=5), timedelta(days=3)),
    partial=True,
    title="Ratsbeschluss Netzausbau",
)
PRESS_RELEASE = Stored(
    "https://rp.test/pressemitteilung",
    "regierungspraesidium-presse",
    (timedelta(days=1),),
    partial=True,
)
TENDER = Stored(
    "https://energate.test/ausschreibung", "energate", (timedelta(hours=2),), title="Ausschreibung"
)
EVERY_SOURCE = (GRANT, HEAT_PLAN, DECISION, PRESS_RELEASE, TENDER)
CATEGORIES = {
    "regierungspraesidium": FeedCategory.AUTHORITY,
    "regierungspraesidium-presse": FeedCategory.AUTHORITY,
    "stadtwerke-ulm": FeedCategory.UTILITY,
    "stadtwerke-heidelberg": FeedCategory.UTILITY,  # nothing collected from it
    "zfk": FeedCategory.PRESS,
    "energate": FeedCategory.PRESS,
}


async def feed_named(db: Database, slug: str) -> Feed:
    """The Feed of `slug`, made with its category the first time it is asked for."""
    async with db.session() as session:
        found = (await session.exec(select(Feed).where(col(Feed.slug) == slug))).one_or_none()
        if found is None:
            found = Feed(
                name=slug,
                slug=slug,
                kind=FeedKind.RSS,
                category=CATEGORIES[slug],
                url=f"https://{slug}.test/feed",
            )
            session.add(found)
        return found


NEWEST_FIRST = [stored.url for stored in reversed(EVERY_SOURCE)]


async def store(db: Database, stored: Stored) -> None:
    """The Source with its committed versions, the latest one pointed at, and one being written."""
    feed = await feed_named(db, stored.feed)
    async with db.session() as session:
        first_seen = NOW - stored.ages[0]
        source = Source(
            url=stored.url,
            url_hash=url_hash(stored.url),
            first_feed_id=feed.id,
            first_seen_at=first_seen,
            last_checked_at=NOW,
        )
        session.add(source)
        await session.flush()
        latest = None
        for number, age in enumerate(stored.ages, start=1):
            latest = version(source, feed, NOW - age, number=number, partial=stored.partial)
            latest.title = stored.title
            session.add(latest)
            await session.flush()
        source.latest_version_id = latest.id if latest else None
        session.add(version(source, feed, NOW, number=None, partial=False))  # not listed


def version(
    source: Source, feed: Feed, fetched_at: datetime, *, number: int | None, partial: bool
) -> SourceVersion:
    return SourceVersion(
        source_id=source.id,
        version_no=number,
        feed_id=feed.id,
        fetched_at=fetched_at,
        media_type="text/html",
        raw_sha256="0" * 64,
        text_sha256=f"{number}".ljust(64, "0"),
        extractor="html",
        extractor_version="1",
        storage_key=f"run/{feed.slug}/{uuid.uuid7()}",
        partial=partial,
        state=VersionState.COMMITTED if number else VersionState.WRITING,
    )


@pytest.fixture
async def client_with_sources(client: httpx2.AsyncClient, database_url: str) -> httpx2.AsyncClient:
    db = Database(database_url)
    for stored in EVERY_SOURCE:
        await store(db, stored)
    await feed_named(db, "stadtwerke-heidelberg")
    await db.dispose()
    await sign_in(client, "alice")
    return client


async def urls(client: httpx2.AsyncClient, *params: tuple[str, str | int]) -> list[str]:
    response = await client.get("/api/sources", params=params)
    assert response.status_code == 200, response.text
    return [listed["url"] for listed in response.json()]


async def counted(client: httpx2.AsyncClient, *params: tuple[str, str | int]) -> int:
    response = await client.get("/api/sources/count", params=params)
    assert response.status_code == 200, response.text
    return response.json()["count"]


def ago(delta: timedelta) -> str:
    return (NOW - delta).isoformat()


async def test_every_source_is_listed_by_its_latest_committed_version_and_counted(
    client_with_sources: httpx2.AsyncClient,
) -> None:
    listed = (await client_with_sources.get("/api/sources")).json()

    assert [s["url"] for s in listed] == NEWEST_FIRST
    assert [s["versions"] for s in listed] == [1, 1, 2, 1, 2]
    assert await counted(client_with_sources) == len(EVERY_SOURCE)


async def test_sources_are_filtered_by_one_feed_or_several(
    client_with_sources: httpx2.AsyncClient,
) -> None:
    client = client_with_sources

    assert await urls(client, ("feed", "energate")) == [TENDER.url]
    assert await urls(client, ("feed", "energate"), ("feed", "zfk")) == [
        TENDER.url,
        DECISION.url,
    ]
    assert await urls(client, ("feed", "stadtwerke-heidelberg")) == []  # nothing collected from it
    assert (
        await counted(
            client, ("feed", "regierungspraesidium"), ("feed", "regierungspraesidium-presse")
        )
        == 2
    )


async def test_sources_are_filtered_by_their_feeds_category(
    client_with_sources: httpx2.AsyncClient,
) -> None:
    client = client_with_sources

    assert await urls(client, ("category", "authority")) == [PRESS_RELEASE.url, GRANT.url]
    assert await urls(client, ("category", "press"), ("category", "utility")) == [
        TENDER.url,
        DECISION.url,
        HEAT_PLAN.url,
    ]
    assert await counted(client, ("category", "utility")) == 1
    refused = await client.get("/api/sources", params={"category": "blog"})
    assert refused.status_code == 422


async def test_sources_are_filtered_by_when_they_last_changed(
    client_with_sources: httpx2.AsyncClient,
) -> None:
    """`since` holds from its time on, `until` up to but not including its time."""
    client = client_with_sources
    two_days, a_fortnight = timedelta(days=2), timedelta(days=14)

    assert await urls(client, ("since", ago(two_days))) == [TENDER.url, PRESS_RELEASE.url]
    assert await urls(client, ("until", ago(two_days))) == [DECISION.url, HEAT_PLAN.url, GRANT.url]
    assert await urls(client, ("since", ago(a_fortnight)), ("until", ago(two_days))) == [
        DECISION.url,
        HEAT_PLAN.url,
    ]
    assert await urls(client, ("since", ago(TENDER.ages[-1]))) == [TENDER.url]
    assert await urls(client, ("until", ago(GRANT.ages[-1]))) == []
    # DECISION's first version is older than a fortnight, its latest is not: the latest counts.
    assert await counted(client, ("until", ago(timedelta(days=4)))) == 2


async def test_a_time_without_its_offset_is_refused(
    client_with_sources: httpx2.AsyncClient,
) -> None:
    client = client_with_sources

    naive = {"since": "2026-10-20T12:00:00"}
    responses = [
        await client.get("/api/sources", params=naive),
        await client.get("/api/sources/count", params=naive),
    ]

    assert [r.status_code for r in responses] == [422, 422]


async def test_sources_are_filtered_by_whether_they_changed_and_whether_they_are_partial(
    client_with_sources: httpx2.AsyncClient,
) -> None:
    client = client_with_sources

    assert await urls(client, ("changed", "true")) == [DECISION.url, GRANT.url]
    assert await urls(client, ("changed", "false")) == [
        TENDER.url,
        PRESS_RELEASE.url,
        HEAT_PLAN.url,
    ]
    assert await urls(client, ("partial", "true")) == [PRESS_RELEASE.url, DECISION.url]
    assert await urls(client, ("partial", "false")) == [TENDER.url, HEAT_PLAN.url, GRANT.url]
    assert await counted(client, ("changed", "true"), ("partial", "true")) == 1


async def test_filters_combine_and_each_must_hold(
    client_with_sources: httpx2.AsyncClient,
) -> None:
    client = client_with_sources
    a_week = ("since", ago(timedelta(days=7)))

    assert await urls(client, ("category", "authority"), ("changed", "true")) == [GRANT.url]
    assert await urls(client, ("category", "press"), ("partial", "true"), a_week) == [DECISION.url]
    assert await urls(client, ("feed", "zfk"), ("partial", "false")) == []
    assert await urls(client, ("category", "utility"), ("q", "waermeplan")) == [HEAT_PLAN.url]
    assert await urls(client, ("feed", "regierungspraesidium"), ("category", "press")) == []
    filters = [("category", "press"), ("category", "authority"), a_week]
    assert await counted(client, *filters) == 3  # TENDER, PRESS_RELEASE, DECISION
    assert await counted(client, ("q", "netzausbau"), ("changed", "true")) == 1


async def test_filtered_sources_are_paged_back_from_the_last_listed_version(
    client_with_sources: httpx2.AsyncClient,
) -> None:
    client = client_with_sources
    filters: list[tuple[str, str | int]] = [("category", "press"), ("category", "authority")]
    pages: list[str] = []
    before: list[tuple[str, str | int]] = []

    while page := (
        await client.get("/api/sources", params=[*filters, ("limit", 1), *before])
    ).json():
        pages.append(page[0]["url"])
        before = [("before", page[0]["version"]["id"])]

    assert pages == [TENDER.url, PRESS_RELEASE.url, DECISION.url, GRANT.url]
    assert await counted(client, *filters) == len(pages)  # every page together
