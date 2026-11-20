"""The Source API: Sources as the scrape job collected them, their versions, text and raw files.

Through the scrape job's seam, on the sink the app reads (the same `memory://` URI).
"""

import uuid
from collections.abc import AsyncIterator

import httpx2
import pytest

from infrasales.catalog import versions as catalog
from infrasales.catalog.router import download_name
from infrasales.settings import Settings
from infrasales.sink.store import Sink
from tests.helpers import sign_in
from tests.scrape.support import (
    RSS,
    Entry,
    Scraping,
    article_page,
    rss_feed,
    scraping_world,
    stored_sources,
    stored_versions,
)

pytestmark = pytest.mark.anyio

FEED = "https://news.test/feed.xml"
OTHER_FEED = "https://policy.test/feed.xml"
AUSBAU = "https://news.test/2026/10/waermenetz-ausbau"
TARIFF = "https://news.test/2026/10/fernwaerme-tarif"
GUIDANCE = "https://policy.test/waermeplanung-hinweise"
SOUTH_ONLY = ("Der Wärmenetz-Ausbau beginnt heute.", "Es wird im Süden allein gebaut.")
WITH_NORTH = ("Der Wärmenetz-Ausbau beginnt heute.", "Es wird jetzt auch im Norden gebaut.")


@pytest.fixture
async def scraping(database_url: str, settings: Settings) -> AsyncIterator[Scraping]:
    """The scrape job's world, writing to the sink the app reads."""
    async with scraping_world(database_url) as world:
        world.sink = Sink(settings.sink.uri)
        yield world


async def collected_twice(scraping: Scraping) -> tuple[uuid.UUID, uuid.UUID]:
    """Two runs: the first collects two articles, the second a changed text of one; their IDs."""
    scraping.web.serve(AUSBAU, article_page("Wärmenetz-Ausbau", *SOUTH_ONLY))
    scraping.web.serve(
        TARIFF,
        article_page("Fernwärmetarif genehmigt", "Die Behörde genehmigte den Fernwärmetarif."),
    )
    entries = rss_feed(Entry(AUSBAU, "Wärmenetz-Ausbau"), Entry(TARIFF, "Fernwärmetarif genehmigt"))
    scraping.web.serve(FEED, entries, media_type=RSS)
    await scraping.add_feed("news", FEED)
    first = await scraping.run_now()
    retitled = rss_feed(
        Entry(AUSBAU, "Wärmenetz-Ausbau, jetzt auch im Norden"),
        Entry(TARIFF, "Fernwärmetarif genehmigt"),
    )
    scraping.web.serve(FEED, retitled, media_type=RSS)
    scraping.web.serve(AUSBAU, article_page("Wärmenetz-Ausbau, jetzt auch im Norden", *WITH_NORTH))
    second = await scraping.run_now()
    return first.id, second.id


async def test_an_admin_lists_sources_by_their_latest_version_newest_first(
    client: httpx2.AsyncClient, scraping: Scraping
) -> None:
    _, second_run = await collected_twice(scraping)
    await sign_in(client, "alice")

    listed = (await client.get("/api/sources")).json()

    assert [(s["url"], s["versions"], s["version"]["number"]) for s in listed] == [
        (AUSBAU, 2, 2),
        (TARIFF, 1, 1),
    ]
    latest = listed[0]["version"]
    assert latest["title"] == "Wärmenetz-Ausbau, jetzt auch im Norden"
    assert latest["feed"] == {"slug": "news", "name": "News"}
    assert (latest["run_id"], latest["superseded_at"]) == (str(second_run), None)


async def test_a_runs_sources_are_listed_by_the_version_it_wrote(
    client: httpx2.AsyncClient, scraping: Scraping
) -> None:
    first_run, second_run = await collected_twice(scraping)
    await sign_in(client, "alice")

    of_first = (await client.get("/api/sources", params={"run": str(first_run)})).json()
    of_second = (await client.get("/api/sources", params={"run": str(second_run)})).json()

    assert [(s["url"], s["version"]["number"]) for s in of_first] == [(TARIFF, 1), (AUSBAU, 1)]
    assert [(s["url"], s["version"]["number"]) for s in of_second] == [(AUSBAU, 2)]
    counts = [
        (await client.get("/api/sources/count", params={"run": str(run)})).json()
        for run in (first_run, second_run)
    ]
    assert counts == [{"count": 2}, {"count": 1}]
    changed = {"run": str(first_run), "changed": "true"}  # by the Source's versions, any run's
    assert [s["url"] for s in (await client.get("/api/sources", params=changed)).json()] == [AUSBAU]


async def test_sources_are_filtered_by_feed_and_by_title_or_address(
    client: httpx2.AsyncClient, scraping: Scraping
) -> None:
    await collected_twice(scraping)
    scraping.web.serve(
        GUIDANCE,
        article_page("Hinweise zur Wärmeplanung", "Die Oberste Baubehörde gab Hinweise heraus."),
    )
    scraping.web.serve(OTHER_FEED, rss_feed(Entry(GUIDANCE)), media_type=RSS)
    await scraping.add_feed("policy", OTHER_FEED)
    await scraping.run_now()
    await sign_in(client, "alice")

    async def urls(**params: str) -> list[str]:
        return [s["url"] for s in (await client.get("/api/sources", params=params)).json()]

    assert await urls(feed="policy") == [GUIDANCE]
    assert await urls(q="jetzt auch im norden") == [AUSBAU]  # the title, in any case
    assert await urls(q="fernwaerme-tarif") == [TARIFF]  # the address
    assert await urls(q="100%") == []  # a wildcard is a character
    assert await urls(feed="news", q="oberste-baubehoerde") == []


async def test_sources_are_paged_back_from_the_last_listed_version(
    client: httpx2.AsyncClient, scraping: Scraping
) -> None:
    await collected_twice(scraping)
    await sign_in(client, "alice")

    (first,) = (await client.get("/api/sources", params={"limit": 1})).json()
    after = {"limit": 1, "before": first["version"]["id"]}
    (second,) = (await client.get("/api/sources", params=after)).json()
    rest = {"limit": 1, "before": second["version"]["id"]}

    assert (first["url"], second["url"]) == (AUSBAU, TARIFF)
    assert (await client.get("/api/sources", params=rest)).json() == []


async def test_a_source_shows_every_version_newest_first_and_what_each_said(
    client: httpx2.AsyncClient, scraping: Scraping
) -> None:
    first_run, second_run = await collected_twice(scraping)
    await sign_in(client, "alice")
    (source,) = [s for s in (await client.get("/api/sources")).json() if s["url"] == AUSBAU]

    read = (await client.get(f"/api/sources/{source['id']}")).json()
    first = (await client.get(f"/api/sources/{source['id']}/versions/1")).json()
    second = (await client.get(f"/api/sources/{source['id']}/versions/2")).json()

    assert read["url"] == AUSBAU
    assert [(v["number"], v["run_id"]) for v in read["versions"]] == [
        (2, str(second_run)),
        (1, str(first_run)),
    ]
    assert read["versions"][1]["superseded_at"] is not None
    assert (first["number"], first["title"]) == (1, "Wärmenetz-Ausbau")
    assert "Süden allein" in first["text"]
    assert "jetzt auch im Norden" in second["text"]


async def test_a_versions_raw_file_is_downloaded_never_shown(
    client: httpx2.AsyncClient, scraping: Scraping
) -> None:
    await collected_twice(scraping)
    await sign_in(client, "alice")
    (source,) = [s for s in (await client.get("/api/sources")).json() if s["url"] == AUSBAU]

    raw = await client.get(f"/api/sources/{source['id']}/versions/1/raw")

    assert raw.status_code == 200
    assert raw.content == article_page("Wärmenetz-Ausbau", *SOUTH_ONLY).encode()
    assert raw.headers["content-type"] == "text/html; charset=utf-8"
    assert raw.headers["content-disposition"] == 'attachment; filename="news.test-v1.html"'
    assert raw.headers["content-security-policy"] == "sandbox"
    assert raw.headers["x-content-type-options"] == "nosniff"


def test_a_download_is_named_after_the_host_and_version_in_safe_characters() -> None:
    assert (
        download_name("https://www.gemeindetag.test/x", 3, "application/pdf")
        == "www.gemeindetag.test-v3.pdf"
    )
    assert download_name("https://bücher.test/", 1, "text/html") == "b-cher.test-v1.html"
    assert download_name("https://a.test/", 2, "application/x-unknown") == "a.test-v2.bin"


async def test_an_unknown_source_or_version_is_not_found(
    client: httpx2.AsyncClient, scraping: Scraping
) -> None:
    await collected_twice(scraping)
    await sign_in(client, "alice")
    (source,) = [s for s in (await client.get("/api/sources")).json() if s["url"] == TARIFF]

    unknown = await client.get(f"/api/sources/{uuid.uuid7()}")
    no_version = await client.get(f"/api/sources/{source['id']}/versions/2")
    no_raw = await client.get(f"/api/sources/{source['id']}/versions/2/raw")

    assert [r.status_code for r in (unknown, no_version, no_raw)] == [404, 404, 404]


async def test_a_version_whose_files_are_gone_says_so(
    client: httpx2.AsyncClient, scraping: Scraping
) -> None:
    await collected_twice(scraping)
    await sign_in(client, "alice")
    version = next(v for v in await stored_versions(scraping.db) if v.version_no == 1)
    await scraping.sink.delete(version.storage_key)

    text = await client.get(f"/api/sources/{version.source_id}/versions/1")
    raw = await client.get(f"/api/sources/{version.source_id}/versions/1/raw")

    assert [r.status_code for r in (text, raw)] == [410, 410]


async def test_a_version_being_deleted_is_no_longer_shown(
    client: httpx2.AsyncClient, scraping: Scraping
) -> None:
    await collected_twice(scraping)
    await sign_in(client, "alice")
    (ausbau,) = [s for s in await stored_sources(scraping.db) if s.url == AUSBAU]
    versions = await stored_versions(scraping.db)
    (first,) = [v for v in versions if v.source_id == ausbau.id and v.version_no == 1]
    await catalog.delete_version(scraping.db, scraping.sink, first.id)

    read = (await client.get(f"/api/sources/{ausbau.id}")).json()
    listed = (await client.get("/api/sources")).json()

    assert [v["number"] for v in read["versions"]] == [2]
    assert [(s["url"], s["versions"]) for s in listed] == [(AUSBAU, 1), (TARIFF, 1)]
    assert (await client.get(f"/api/sources/{ausbau.id}/versions/1")).status_code == 404


@pytest.mark.parametrize(("user", "status"), [(None, 401), ("vera", 403)])
async def test_only_admins_read_sources(
    client: httpx2.AsyncClient, user: str | None, status: int
) -> None:
    if user:
        await sign_in(client, user)
    some = uuid.uuid7()

    responses = [
        await client.get("/api/sources"),
        await client.get("/api/sources/count"),
        await client.get(f"/api/sources/{some}"),
        await client.get(f"/api/sources/{some}/versions/1"),
        await client.get(f"/api/sources/{some}/versions/1/raw"),
    ]

    assert [r.status_code for r in responses] == [status] * 5
