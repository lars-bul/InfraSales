"""`sitemap` Feeds through the scrape job: a fake web, a `memory://` sink, the test database."""

import gzip
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape

import pytest

from infrasales.catalog.models import VersionState
from infrasales.core.models import utcnow
from infrasales.feeds import sitemap
from infrasales.feeds.models import FeedKind
from infrasales.fetch.http import MAX_BYTES
from infrasales.scheduler.models import JobStatus
from tests.scrape.support import (
    RSS,
    Scraping,
    article_page,
    counts,
    rss_feed,
    stored_sources,
    stored_versions,
)

pytestmark = pytest.mark.anyio

SITEMAP = "https://press.test/sitemap.xml"
ARTICLE = "https://press.test/news/consultation-opened"
XML = "application/xml"
WIRE = "https://wire.test/rss"
TEXT = (
    "The district council opened a consultation on the heat network for the new estates.",
    "Residents had asked whether their homes could be connected before the next winter.",
)


@dataclass(frozen=True)
class Url:
    """A `<url>` (or, in an index, a `<sitemap>`) entry."""

    loc: str
    lastmod: datetime | None = None
    news: datetime | None = None  # `news:publication_date`
    title: str | None = None  # `news:title`


def urlset(*urls: Url) -> str:
    entries = "".join(f"<url>{_fields(url)}</url>" for url in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
        ' xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
        f"{entries}</urlset>"
    )


def _fields(url: Url) -> str:
    parts = [f"<loc>{escape(url.loc)}</loc>"]
    if url.lastmod:
        parts.append(f"<lastmod>{url.lastmod.isoformat()}</lastmod>")
    if url.news or url.title:
        news = "<news:publication><news:name>Press</news:name></news:publication>"
        if url.news:
            news += f"<news:publication_date>{url.news.isoformat()}</news:publication_date>"
        if url.title:
            news += f"<news:title>{escape(url.title)}</news:title>"
        parts.append(f"<news:news>{news}</news:news>")
    return "".join(parts)


def ago(**delta: float) -> datetime:
    return utcnow() - timedelta(**delta)


def serve_articles(scraping: Scraping, *urls: str) -> None:
    for url in urls:
        scraping.web.serve(url, article_page(url.rsplit("/", 1)[-1], *TEXT))


async def test_a_sitemap_feeds_recent_entries_become_committed_source_versions(
    scraping: Scraping,
) -> None:
    first, second = ARTICLE, "https://press.test/news/fine"
    serve_articles(scraping, first, second)
    scraping.web.serve(
        SITEMAP,
        urlset(
            Url(first, lastmod=ago(hours=5)),
            Url("", lastmod=ago(hours=1)),  # no address: skipped
            Url(second, lastmod=ago(days=2)),
        ),
        media_type=XML,
    )
    await scraping.add_feed("press", SITEMAP, kind=FeedKind.SITEMAP)

    run = await scraping.run_now()

    assert (run.status, counts(run)["versions_new"], counts(run)["failed_feeds"]) == (
        JobStatus.SUCCEEDED,
        2,
        [],
    )
    assert {source.url for source in await stored_sources(scraping.db)} == {first, second}
    assert {v.state for v in await stored_versions(scraping.db)} == {VersionState.COMMITTED}


async def test_a_news_sitemap_tells_the_title_and_publication_date(scraping: Scraping) -> None:
    published = ago(hours=3).replace(microsecond=0)
    serve_articles(scraping, ARTICLE)
    scraping.web.serve(
        SITEMAP,
        urlset(Url(ARTICLE, lastmod=ago(hours=1), news=published, title="Consultation opened")),
    )
    await scraping.add_feed("press", SITEMAP, kind=FeedKind.SITEMAP)

    await scraping.run_now()

    (version,) = await stored_versions(scraping.db)
    metadata = json.loads((await scraping.files())[f"{version.storage_key}/metadata.json"])
    assert metadata["discovery"]["listed"] == {
        "url": ARTICLE,
        "title": "Consultation opened",
        "published_at": published.isoformat(),
        "summary": None,
        "author": None,
    }


async def test_only_the_newest_entries_within_the_maximum_age_and_count_are_fetched(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sitemap, "MAX_ITEMS", 2)
    newest, newer, new = (f"https://press.test/news/{n}" for n in ("newest", "newer", "new"))
    old, undated = "https://press.test/news/2019-archive", "https://press.test/about"
    serve_articles(scraping, newest, newer, new, old, undated)
    scraping.web.serve(
        SITEMAP,
        urlset(
            Url(old, lastmod=ago(days=31)),
            Url(undated),
            Url(new, lastmod=ago(days=3)),
            Url(newest, news=ago(hours=1), lastmod=ago(days=20)),  # the news date counts
            Url(newer, lastmod=ago(days=1)),
        ),
    )
    await scraping.add_feed("press", SITEMAP, kind=FeedKind.SITEMAP)

    run = await scraping.run_now()

    assert counts(run)["versions_new"] == 2
    fetched = {url for url in (newest, newer, new, old, undated) if scraping.web.fetched(url)}
    assert fetched == {newest, newer}


def sitemapindex(*sitemaps: Url) -> str:
    entries = "".join(f"<sitemap>{_fields(sitemap)}</sitemap>" for sitemap in sitemaps)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</sitemapindex>'
    )


async def test_an_index_is_followed_to_its_newest_sitemaps_gzipped_ones_too(
    scraping: Scraping,
) -> None:
    oldest, older = "https://press.test/sitemap-2024.xml", "https://press.test/sitemap-09.xml"
    newer, newest = "https://press.test/sitemap-10.xml", "https://press.test/sitemap-news.xml.gz"
    articles = {
        sitemap: f"https://press.test/news/{n}"
        for n, sitemap in enumerate((oldest, older, newer, newest))
    }
    serve_articles(scraping, *articles.values())
    for plain in (oldest, older, newer):
        scraping.web.serve(plain, urlset(Url(articles[plain], lastmod=ago(days=1))))
    scraping.web.serve(
        newest,
        gzip.compress(urlset(Url(articles[newest], lastmod=ago(hours=1))).encode()),
        media_type="application/gzip",  # a file, not a transfer encoding: unpacked by the Lister
    )
    scraping.web.serve(
        SITEMAP,
        sitemapindex(
            Url(oldest, lastmod=ago(days=400)),
            Url(older, lastmod=ago(days=20)),
            Url(newest, lastmod=ago(hours=1)),
            Url(newer, lastmod=ago(days=1)),
        ),
    )
    await scraping.add_feed("press", SITEMAP, kind=FeedKind.SITEMAP)

    run = await scraping.run_now()

    assert (counts(run)["versions_new"], counts(run)["failed_feeds"]) == (3, [])
    assert {source.url for source in await stored_sources(scraping.db)} == {
        articles[newest],
        articles[newer],
        articles[older],
    }
    assert scraping.web.fetched(oldest) == 0  # beyond the newest three


ENTITIES = (
    '<?xml version="1.0"?><!DOCTYPE urlset [<!ENTITY x SYSTEM "file:///etc/hostname">]>'
    f"<urlset><url><loc>{ARTICLE}?&x;</loc></url></urlset>"
)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(urlset(Url(ARTICLE)).removesuffix("</urlset>"), id="malformed XML"),
        pytest.param(article_page("A page", *TEXT), id="a page"),
        pytest.param("<?xml version='1.0'?><rss version='2.0'><channel/></rss>", id="an RSS feed"),
        pytest.param(ENTITIES, id="entities"),
        pytest.param(b"\x1f\x8bnot gzip after all", id="broken gzip"),
        pytest.param(gzip.compress(urlset(Url(ARTICLE)).encode())[:-30], id="truncated gzip"),
        pytest.param(gzip.compress(b" " * (MAX_BYTES + 1)), id="too large unpacked"),
        pytest.param(sitemapindex(Url(SITEMAP)), id="an index in an index"),
    ],
)
async def test_what_is_no_sitemap_fails_the_feed_not_the_run(
    scraping: Scraping, body: str | bytes
) -> None:
    serve_articles(scraping, ARTICLE)
    scraping.web.serve(SITEMAP, body, media_type=XML)
    await scraping.add_feed("press", SITEMAP, kind=FeedKind.SITEMAP)
    scraping.web.serve(WIRE, rss_feed(), media_type=RSS)
    await scraping.add_feed("wire", WIRE)  # read: the run fails only when every Feed fails

    run = await scraping.run_now()

    assert run.status == JobStatus.SUCCEEDED
    assert counts(run)["failed_feeds"] == [{"feed": "press", "reason": "unreadable"}]
    assert scraping.web.fetched(ARTICLE) == 0
