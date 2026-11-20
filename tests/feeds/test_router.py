import asyncio
import gzip
import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx2
import pytest
from sqlalchemy import ColumnElement, false
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.app import create_app
from infrasales.catalog.models import Source, SourceVersion, VersionState
from infrasales.core.db import Database
from infrasales.feeds import discovery, kinds, service
from infrasales.feeds.lister import Item, ListerSettings
from infrasales.feeds.models import Feed, FeedKind
from infrasales.feeds.router import NETWORK
from infrasales.fetch.fetcher import Fetcher
from infrasales.settings import Settings
from tests.helpers import SAME_ORIGIN, audit_events, sign_in
from tests.scrape.support import RSS, FakeWeb, rss_feed

pytestmark = pytest.mark.anyio

FEED = "https://news.test/feed.xml"
SITE = "https://news.test/"


async def test_an_admin_adds_a_feed_and_sees_it_listed(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await sign_in(client, "alice")

    added = await client.post(
        "/api/feeds",
        json={"name": "Heizwerk Journal", "kind": "rss", "url": FEED},
        headers=SAME_ORIGIN,
    )
    listed = (await client.get("/api/feeds")).json()

    assert added.status_code == 201
    feed = added.json()
    assert {k: feed[k] for k in ("name", "slug", "kind", "url", "settings", "extractor")} == {
        "name": "Heizwerk Journal",
        "slug": "heizwerk-journal",
        "kind": "rss",
        "url": FEED,
        "settings": {},
        "extractor": None,
    }
    assert (feed["enabled"], feed["state"], feed["last_error"], feed["last_scraped_at"]) == (
        True,
        "ok",
        None,
        None,
    )
    assert feed in listed
    event = (await audit_events(database_url))[-1]
    assert (event.actor, event.action, event.target) == (
        "basic:alice",
        "feed.created",
        "heizwerk-journal",
    )
    assert event.details == {"kind": "rss", "url": FEED}


async def add(client: httpx2.AsyncClient, **feed: object) -> httpx2.Response:
    return await client.post("/api/feeds", json={"kind": "rss"} | feed, headers=SAME_ORIGIN)


async def test_a_feed_is_added_as_press_unless_another_category_is_given(
    client: httpx2.AsyncClient,
) -> None:
    await sign_in(client, "alice")

    press = await add(client, name="News", url=FEED)
    utility = await add(client, name="Stadtwerke", url=f"{SITE}stadtwerke.xml", category="utility")
    unknown = await add(client, name="Blog", url=f"{SITE}blog.xml", category="blog")

    assert (press.json()["category"], utility.json()["category"]) == ("press", "utility")
    assert unknown.status_code == 422
    listed = {f["slug"]: f["category"] for f in (await client.get("/api/feeds")).json()}
    assert listed == {"news": "press", "stadtwerke": "utility"}


async def test_a_second_feed_at_the_same_address_is_a_conflict(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await sign_in(client, "alice")
    await add(client, name="News", url=FEED)

    again = await add(client, name="Other News", url=FEED)

    assert again.status_code == 409
    created = [e for e in await audit_events(database_url) if e.action == "feed.created"]
    assert len(created) == 1


async def test_each_feed_gets_a_slug_of_its_own(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "alice")

    slugs = [
        (await add(client, name=name, url=f"https://news.test/{n}.xml")).json()["slug"]
        for n, name in enumerate(["Stadtwerke Süd!", "Stadtwerke   Sud", "日本", "Stadtwerke Süd"])
    ]

    assert slugs == ["stadtwerke-sud", "stadtwerke-sud-2", "feed", "stadtwerke-sud-3"]


async def test_a_slug_taken_by_a_concurrent_add_is_given_the_next_free_one(
    client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another admin adds a Feed under the same slug between our slug lookup and insert."""
    await sign_in(client, "alice")
    free_slug = service.free_slug  # the race window opens after it
    raced: list[str] = []

    async def taken_meanwhile(session: AsyncSession, base: str) -> str:
        slug = await free_slug(session, base)
        if not raced:
            raced.append(slug)
            rival = Feed(name="Rival", slug=slug, kind=FeedKind.RSS, url="https://rival.test/rss")
            session.add(rival)
            await session.flush()
        return slug

    monkeypatch.setattr(service, "free_slug", taken_meanwhile)

    added = await add(client, name="News", url=FEED)

    assert (added.status_code, added.json()["slug"], raced) == (201, "news-2", ["news"])
    listed = (await client.get("/api/feeds")).json()
    assert {(f["slug"], f["url"]) for f in listed} >= {
        ("news", "https://rival.test/rss"),
        ("news-2", FEED),
    }


class AgencySettings(ListerSettings):
    agency: str
    per_page: int = 20


class AgencyLister:
    """A test-only Lister with settings: Feeds of its kind name an agency."""

    settings = AgencySettings

    async def list(self, feed: Feed, fetcher: Fetcher) -> list[Item]:
        raise NotImplementedError


@pytest.fixture
def agency_kind(monkeypatch: pytest.MonkeyPatch) -> FeedKind:
    """An API kind read by `AgencyLister`, whichever Listers the registry has."""
    monkeypatch.setitem(kinds.LISTERS, FeedKind.SITEMAP, AgencyLister())
    return FeedKind.SITEMAP


async def test_settings_are_checked_by_the_kinds_lister(
    client: httpx2.AsyncClient, agency_kind: FeedKind
) -> None:
    await sign_in(client, "alice")
    url = "https://api.test/documents.json"

    missing = await add(client, name="BNetzA", kind=agency_kind, url=url)
    unknown_key = await add(
        client, name="BNetzA", url=FEED, settings={"agency": "bnetza", "pages": 2}
    )
    wrong_type = await add(
        client,
        name="BNetzA",
        kind=agency_kind,
        url=url,
        settings={"agency": "bnetza", "per_page": "x"},
    )
    added = await add(
        client,
        name="BNetzA",
        kind=agency_kind,
        url=url,
        settings={"agency": "bnetza", "per_page": "5"},
    )

    assert [r.status_code for r in (missing, unknown_key, wrong_type)] == [422] * 3
    assert "agency: Field required" in missing.text
    assert "agency: Extra inputs are not permitted" in unknown_key.text  # rss takes none
    assert "per_page: Input should be a valid integer" in wrong_type.text
    assert added.status_code == 201
    assert added.json()["settings"] == {
        "agency": "bnetza",
        "per_page": 5,
    }  # as the Lister reads them


async def test_a_feed_must_be_of_a_kind_infrasales_reads(
    client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(kinds.LISTERS, FeedKind.SITEMAP)
    await sign_in(client, "alice")

    unknown = await add(client, name="Shop", kind="html-listing", url=FEED)
    unread = await add(client, name="Sitemap", kind="sitemap", url=FEED)

    assert (unknown.status_code, unread.status_code) == (422, 422)
    assert "Feeds of kind sitemap cannot be read yet" in unread.text
    assert FEED not in [feed["url"] for feed in (await client.get("/api/feeds")).json()]


@pytest.mark.parametrize(
    "feed",
    [
        {"name": " ", "url": FEED},
        {"name": "News", "url": "ftp://news.test/feed.xml"},
        {"name": "News", "url": "https://news.test/" + "a" * 2048},
        {"name": "News", "url": FEED, "extractor": "word"},
        {"name": "News", "url": FEED, "fetcher": "browser"},
    ],
)
async def test_invalid_feeds_are_refused(client: httpx2.AsyncClient, feed: dict[str, str]) -> None:
    await sign_in(client, "alice")

    assert (await add(client, **feed)).status_code == 422


async def test_a_feed_may_name_its_extractor(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "alice")

    added = await add(client, name="News", url=FEED, extractor="html")

    assert added.json()["extractor"] == "html"


@pytest.mark.parametrize(("user", "status"), [(None, 401), ("vera", 403)])
async def test_only_admins_manage_feeds(
    client: httpx2.AsyncClient, user: str | None, status: int
) -> None:
    if user:
        await sign_in(client, user)

    listed = await client.get("/api/feeds")
    added = await add(client, name="News", url=FEED)
    suggested = await client.post("/api/feeds/suggest", json={"url": SITE}, headers=SAME_ORIGIN)
    deleted = await client.delete(f"/api/feeds/{uuid.uuid7()}", headers=SAME_ORIGIN)

    assert [r.status_code for r in (listed, added, suggested, deleted)] == [status] * 4


NOW = datetime(2026, 10, 17, 9, tzinfo=UTC)


async def collected(database_url: str, *, listed_by: str, filed_under: str | None = None) -> None:
    """A Source the Feed `listed_by` listed first, and its version filed under `filed_under`."""
    db = Database(database_url)
    async with db.session() as session:
        source = Source(
            url="https://news.test/story",
            url_hash=hashlib.sha256(b"https://news.test/story").hexdigest(),
            first_feed_id=uuid.UUID(listed_by),
            first_seen_at=NOW,
            last_checked_at=NOW,
        )
        session.add(source)
        if filed_under is not None:
            await session.flush()
            session.add(
                SourceVersion(
                    source_id=source.id,
                    feed_id=uuid.UUID(filed_under),
                    fetched_at=NOW,
                    media_type="text/html",
                    raw_sha256="0" * 64,
                    text_sha256="0" * 64,
                    extractor="html",
                    extractor_version="1",
                    storage_key="run/news/version",
                )
            )
    await db.dispose()


async def listed_slugs(client: httpx2.AsyncClient) -> dict[str, bool]:
    """Each Feed's slug, and whether it has collected Sources."""
    return {feed["slug"]: feed["has_sources"] for feed in (await client.get("/api/feeds")).json()}


async def test_an_admin_deletes_a_feed_that_has_collected_nothing(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await sign_in(client, "alice")
    feed = (await add(client, name="News", url=FEED)).json()
    assert feed["has_sources"] is False
    assert (await listed_slugs(client))["news"] is False

    deleted = await client.delete(f"/api/feeds/{feed['id']}", headers=SAME_ORIGIN)

    assert deleted.status_code == 204
    assert "news" not in await listed_slugs(client)
    event = (await audit_events(database_url))[-1]
    assert (event.actor, event.action, event.target, event.details) == (
        "basic:alice",
        "feed.deleted",
        "news",
        {"kind": "rss", "url": FEED},
    )
    again = await client.delete(f"/api/feeds/{feed['id']}", headers=SAME_ORIGIN)
    assert again.status_code == 404


@pytest.mark.parametrize(
    "named_by", ["a Source it listed first", "a Source Version filed under it"]
)
async def test_a_feed_that_has_collected_sources_stays(
    client: httpx2.AsyncClient, database_url: str, named_by: str
) -> None:
    await sign_in(client, "alice")
    first = (await add(client, name="News", url=FEED)).json()
    other = (await add(client, name="Other", url="https://other.test/feed.xml")).json()
    if named_by.startswith("a Source it"):
        await collected(database_url, listed_by=first["id"])
        feed = first
    else:
        await collected(database_url, listed_by=first["id"], filed_under=other["id"])
        feed = other

    refused = await client.delete(f"/api/feeds/{feed['id']}", headers=SAME_ORIGIN)

    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "The Feed has collected Sources, so it stays",
    )
    assert (await listed_slugs(client))[feed["slug"]] is True
    assert "feed.deleted" not in [e.action for e in await audit_events(database_url)]


async def stored_versions_of(
    database_url: str, feed_id: str, *states: tuple[VersionState, ...], moved_to: str | None = None
) -> None:
    """A Source per item of `states`, with versions in those states filed under the Feed.

    The latest committed version is the Source's latest, as collection sets it; with `moved_to`,
    each Source's last version is filed under that Feed instead.
    """
    db = Database(database_url)
    async with db.session() as session:
        for n, versions in enumerate(states):
            url = f"https://news.test/story-{n}"
            source = Source(
                url=url,
                url_hash=hashlib.sha256(url.encode()).hexdigest(),
                first_feed_id=uuid.UUID(feed_id),
                first_seen_at=NOW,
                last_checked_at=NOW,
            )
            session.add(source)
            await session.flush()
            for number, state in enumerate(versions, start=1):
                filed_under = moved_to if moved_to and number == len(versions) else feed_id
                version = SourceVersion(
                    source_id=source.id,
                    version_no=number if state == VersionState.COMMITTED else None,
                    feed_id=uuid.UUID(filed_under),
                    fetched_at=NOW,
                    media_type="text/html",
                    raw_sha256="0" * 64,
                    text_sha256="0" * 64,
                    extractor="html",
                    extractor_version="1",
                    storage_key=f"run/news/{uuid.uuid7()}",
                    state=state,
                )
                session.add(version)
                await session.flush()
                if state == VersionState.COMMITTED:
                    source.latest_version_id = version.id
                    session.add(source)
    await db.dispose()


async def test_each_feed_is_listed_with_how_many_sources_its_versions_name(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    """Each Source once, however many versions it has; versions not committed are not counted."""
    await sign_in(client, "alice")
    news = (await add(client, name="News", url=FEED)).json()
    empty = (await add(client, name="Empty", url="https://empty.test/feed.xml")).json()
    committed, writing = VersionState.COMMITTED, VersionState.WRITING
    await stored_versions_of(
        database_url, news["id"], (committed,), (committed, committed, writing), (writing,)
    )

    listed = {f["slug"]: f for f in (await client.get("/api/feeds")).json()}

    assert (news["sources"], empty["sources"]) == (0, 0)  # as added
    assert (listed["news"]["sources"], listed["news"]["has_sources"]) == (2, True)
    assert (listed["empty"]["sources"], listed["empty"]["has_sources"]) == (0, False)
    assert {f["sources"] for slug, f in listed.items() if slug != "news"} == {0}  # the rest


async def test_a_source_counts_under_the_feed_its_latest_version_came_from(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    """As the Sources page lists it by `?feed=`: the count links to that list, number and all."""
    await sign_in(client, "alice")
    first = (await add(client, name="First", url=FEED)).json()
    then = (await add(client, name="Then", url="https://then.test/feed.xml")).json()
    committed = VersionState.COMMITTED
    await stored_versions_of(database_url, first["id"], (committed, committed), moved_to=then["id"])

    listed = {f["slug"]: f for f in (await client.get("/api/feeds")).json()}
    counted = {
        slug: (await client.get("/api/sources/count", params={"feed": slug})).json()["count"]
        for slug in ("first", "then")
    }

    assert (listed["first"]["sources"], listed["first"]["has_sources"]) == (0, True)
    assert (listed["then"]["sources"], listed["then"]["has_sources"]) == (1, True)
    assert counted == {"first": 0, "then": 1}


def nothing_collected(_: object) -> ColumnElement[bool]:
    return false()


async def test_a_source_stored_while_the_feed_is_deleted_keeps_the_feed(
    client: httpx2.AsyncClient, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await sign_in(client, "alice")
    feed = (await add(client, name="News", url=FEED)).json()
    await collected(database_url, listed_by=feed["id"])
    # the check found nothing yet: the foreign key refuses the delete
    monkeypatch.setattr(service, "_has_sources", nothing_collected)

    refused = await client.delete(f"/api/feeds/{feed['id']}", headers=SAME_ORIGIN)

    assert refused.status_code == 409
    assert "news" in await listed_slugs(client)
    assert "feed.deleted" not in [e.action for e in await audit_events(database_url)]


@dataclass
class Web:
    client: httpx2.AsyncClient
    fake: FakeWeb

    async def suggest(self, url: str) -> httpx2.Response:
        return await self.client.post("/api/feeds/suggest", json={"url": url}, headers=SAME_ORIGIN)


@pytest.fixture
async def web(settings: Settings) -> AsyncIterator[Web]:
    """The app, signed in as an admin, its suggestions reaching a fake web."""
    app = create_app(settings)
    fake = FakeWeb()
    NETWORK.set(app, fake.network())
    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        await sign_in(client, "alice")
        yield Web(client, fake)


def home_page(title: str, *head: str) -> str:
    return f"<!doctype html><html><head><title>{title}</title>{''.join(head)}</head><body/></html>"


SITEMAP = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://news.test/a</loc></url></urlset>"
)


async def test_a_page_linking_its_feed_suggests_that_feed(web: Web) -> None:
    link = '<link rel="alternate" type="application/rss+xml" href="/news/rss">'
    web.fake.serve(SITE, home_page(" News Today ", link))
    web.fake.serve("https://news.test/news/rss", rss_feed(), media_type=RSS)

    response = await web.suggest(SITE)

    assert response.status_code == 200
    assert response.json() == {
        "name": "News Today",
        "kind": "rss",
        "url": "https://news.test/news/rss",
    }


async def test_a_feed_at_a_usual_path_is_found(web: Web) -> None:
    web.fake.serve(SITE, home_page("News"))
    web.fake.serve("https://news.test/feed.xml", rss_feed(), media_type=RSS)

    suggestion = (await web.suggest(SITE)).json()

    assert (suggestion["kind"], suggestion["url"]) == ("rss", "https://news.test/feed.xml")


async def test_a_feed_address_suggests_itself(web: Web) -> None:
    web.fake.redirect("https://news.test/rss", "https://news.test/rss.xml")
    web.fake.serve("https://news.test/rss.xml", rss_feed(title="News Feed"), media_type=RSS)

    suggestion = (await web.suggest("https://news.test/rss")).json()

    assert suggestion == {"name": "News Feed", "kind": "rss", "url": "https://news.test/rss.xml"}


async def test_a_site_with_only_a_sitemap_suggests_the_sitemap(web: Web) -> None:
    robots = "User-agent: *\nDisallow:\nSitemap: https://news.test/maps/news.xml\n"
    web.fake.serve(SITE, home_page("News"))
    web.fake.serve("https://news.test/robots.txt", robots, media_type="text/plain")
    web.fake.serve("https://news.test/maps/news.xml", SITEMAP, media_type="application/xml")

    suggestion = (await web.suggest(SITE)).json()

    assert suggestion == {
        "name": "News",
        "kind": "sitemap",
        "url": "https://news.test/maps/news.xml",
    }
    assert web.fake.fetched("https://news.test/robots.txt") == 1  # read once: rules and sitemaps


async def test_a_gzipped_sitemap_at_a_usual_path_is_found(web: Web) -> None:
    web.fake.serve(SITE, "not html at all", media_type="text/plain")
    gzipped = gzip.compress(SITEMAP.encode())
    web.fake.serve("https://news.test/sitemap.xml", gzipped, media_type="application/gzip")

    suggestion = (await web.suggest(SITE)).json()

    assert suggestion == {
        "name": "news.test",
        "kind": "sitemap",
        "url": "https://news.test/sitemap.xml",
    }


async def test_a_sitemap_address_suggests_itself(web: Web) -> None:
    web.fake.serve("https://news.test/sitemap_index.xml", SITEMAP, media_type="application/xml")

    suggestion = (await web.suggest("https://news.test/sitemap_index.xml")).json()

    assert (suggestion["kind"], suggestion["url"]) == (
        "sitemap",
        "https://news.test/sitemap_index.xml",
    )


async def test_nothing_to_read_is_an_error(web: Web) -> None:
    feed_link = '<link rel="alternate" type="application/atom+xml" href="https://internal.test/a">'
    web.fake.serve(SITE, home_page("News", feed_link))
    web.fake.serve("https://news.test/robots.txt", "Sitemap: https://news.test/map.xml")
    web.fake.serve("https://news.test/map.xml", "<html>no sitemap</html>")
    web.fake.serve("https://news.test/feed", "<<<", media_type="application/xml")

    response = await web.suggest(SITE)

    assert response.status_code == 422
    assert response.json()["detail"] == "Neither a feed nor a sitemap was found there"
    assert "internal.test" not in web.fake.hosts()  # the private feed link was not followed


@pytest.mark.parametrize(
    ("url", "detail"),
    [
        ("http://internal.test/", "That address is not allowed"),
        ("http://metadata.test/latest/", "That address is not allowed"),
        ("https://gone.test/", "That address could not be read"),  # 404
    ],
)
async def test_unreadable_addresses_are_refused(web: Web, url: str, detail: str) -> None:
    response = await web.suggest(url)

    assert (response.status_code, response.json()["detail"]) == (422, detail)
    assert web.fake.hosts() <= {"gone.test"}


async def test_a_site_behind_a_bot_wall_is_refused_and_a_refused_page_unreadable(
    web: Web,
) -> None:
    web.fake.serve(SITE, "Just a moment", status=403, headers={"cf-mitigated": "challenge"})
    web.fake.serve("https://members.test/", "Forbidden", status=403)

    walled = await web.suggest(SITE)
    refused = await web.suggest("https://members.test/")

    assert (walled.status_code, walled.json()["detail"]) == (
        422,
        "That site blocks InfraSales' bot",
    )
    assert (refused.status_code, refused.json()["detail"]) == (
        422,
        "That address could not be read",
    )


async def test_a_site_too_slow_to_answer_is_given_up(
    web: Web, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(discovery, "TIME_LIMIT_SECONDS", 0.05)

    def never(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=_never_ending())

    web.fake.route("https://news.test/robots.txt", never)  # the first request a suggestion sends

    response = await web.suggest(SITE)

    assert (response.status_code, response.json()["detail"]) == (
        504,
        "The site did not answer in time",
    )


async def _never_ending() -> AsyncIterator[bytes]:
    yield b"<html>"
    await asyncio.Event().wait()


async def test_a_suggestion_obeys_robots_txt_and_pauses_between_requests(web: Web) -> None:
    robots = "User-agent: *\nDisallow: /feed\nDisallow: /rss\n"  # also /feed.xml, /rss.xml
    web.fake.serve("https://news.test/robots.txt", robots, media_type="text/plain")
    web.fake.serve(SITE, home_page("News"))
    web.fake.serve("https://news.test/feed.xml", rss_feed(), media_type=RSS)  # disallowed
    web.fake.serve("https://news.test/atom.xml", rss_feed(), media_type=RSS)

    suggestion = (await web.suggest(SITE)).json()

    assert suggestion["url"] == "https://news.test/atom.xml"
    assert [str(r.url) for r in web.fake.requests] == [
        "https://news.test/robots.txt",
        SITE,
        "https://news.test/atom.xml",  # /feed, /rss, /feed.xml, /rss.xml: never requested
    ]
    pause = discovery.PAUSE_SECONDS  # shorter than the scrape's: an admin is waiting
    assert web.fake.times("news.test") == [0, pause, 2 * pause]


async def test_a_page_robots_txt_disallows_is_not_read(web: Web) -> None:
    web.fake.serve("https://news.test/robots.txt", "User-agent: *\nDisallow: /\n")
    web.fake.serve(SITE, home_page("News"))

    response = await web.suggest(SITE)

    assert (response.status_code, response.json()["detail"]) == (
        422,
        "robots.txt does not let InfraSales read that address",
    )
    assert web.fake.fetched(SITE) == 0


async def test_a_site_whose_pauses_do_not_fit_is_given_up_at_once(web: Web) -> None:
    """A Crawl-delay longer than a suggestion's time: no waiting for a 504 that must come."""
    web.fake.serve("https://news.test/robots.txt", "User-agent: *\nCrawl-delay: 60\n")
    web.fake.serve(SITE, home_page("News"))

    response = await web.suggest(SITE)

    assert (response.status_code, response.json()["detail"]) == (
        504,
        "The site asks for longer pauses than a suggestion has",
    )
    assert (web.fake.fetched(SITE), web.fake.time.now) == (0, 0)


async def test_a_feed_link_that_is_no_address_is_left_out(web: Web) -> None:
    broken = '<link rel="alternate" type="application/rss+xml" href="http://[::1/broken">'
    good = '<link rel="alternate" type="application/rss+xml" href="/news/rss">'
    web.fake.serve(SITE, home_page("News", broken, good))
    web.fake.serve("https://news.test/news/rss", rss_feed(), media_type=RSS)

    response = await web.suggest(SITE)

    assert (response.status_code, response.json()["url"]) == (200, "https://news.test/news/rss")
