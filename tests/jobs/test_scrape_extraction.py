"""Which extractor reads each document, through the scrape job seam (BIG-23, ADR 03 §5)."""

import json
import re
from pathlib import Path

import lxml.html
import pytest

from infrasales.extract import registry
from infrasales.extract.extractor import Extracted
from infrasales.feeds.models import FeedState
from tests.scrape.support import (
    PDF,
    RSS,
    Entry,
    Scraping,
    counts,
    feed_outcome,
    pdf_document,
    rss_feed,
    stored_feeds,
    stored_sources,
    stored_versions,
)

pytestmark = pytest.mark.anyio

PAGES = Path(__file__).parents[1] / "extract" / "pages"  # saved pages and their expected output

FEED = "https://behoerde.test/feed.xml"
REPORT = "https://behoerde.test/reports/heat-plan.pdf"


async def test_a_pdf_is_stored_as_raw_pdf_with_its_text_read_by_the_pdf_extractor(
    scraping: Scraping,
) -> None:
    report = pdf_document(
        "Municipal heat plan: final report.",
        "We found that the old town suits a heat network.",
        "We propose that the utility builds the network in three stages from next year,"
        " so that households can connect early and leave their gas boilers behind.",
        "A consultation on the plan runs for eight weeks.",
        title="Municipal heat plan",
    )  # long enough to pass the quality gate: a complete text, not `partial`
    scraping.web.serve(REPORT, report, media_type=PDF)
    scraping.web.serve(FEED, rss_feed(Entry(REPORT, "Heat plan")), media_type=RSS)
    await scraping.add_feed("behoerde", FEED)

    run = await scraping.run_now()

    assert counts(run)["versions_new"] == 1
    (version,) = await stored_versions(scraping.db)
    assert (version.media_type, version.extractor) == (PDF, "pdf")
    assert version.extractor_version.startswith("1+pypdf-")
    files = await scraping.files(version.storage_key)
    assert files[f"{version.storage_key}/raw.pdf"] == report
    extracted = json.loads(files[f"{version.storage_key}/extracted.json"])
    assert extracted == {
        "extractor": {"name": "pdf", "version": version.extractor_version},
        "title": "Municipal heat plan",
        "author": None,
        "published_at": None,
        "text": (
            "Municipal heat plan: final report.\n\n"
            "We found that the old town suits a heat network.\n\n"
            "We propose that the utility builds the network in three stages from next year,"
            " so that households can connect early and leave their gas boilers behind.\n\n"
            "A consultation on the plan runs for eight weeks."
        ),
    }


@pytest.mark.parametrize(
    ("media_type", "body", "raw"),
    [
        ("application/json", '{"title": "Décision", "agency": "BNetzA"}', "raw.json"),
        ("application/ld+json", '{"@type": "NewsArticle"}', "raw.json"),
        ("text/xml", '<?xml version="1.0"?><notice>Décision</notice>', "raw.xml"),
        (
            "application/atom+xml",
            '<?xml version="1.0" encoding="ISO-8859-1"?><feed>D\xe9cision</feed>',
            "raw.xml",
        ),
    ],
)
async def test_json_and_xml_documents_are_kept_as_they_are(
    scraping: Scraping, media_type: str, body: str, raw: str
) -> None:
    """The text is the document itself, decoded (UTF-8 unless an XML declaration says else)."""
    encoding = "latin-1" if "ISO-8859-1" in body else "utf-8"
    notice = "https://behoerde.test/api/notices/42"
    scraping.web.serve(notice, body.encode(encoding), media_type=media_type)
    scraping.web.serve(FEED, rss_feed(Entry(notice)), media_type=RSS)
    await scraping.add_feed("behoerde", FEED)

    run = await scraping.run_now()

    assert counts(run)["versions_new"] == 1
    (version,) = await stored_versions(scraping.db)
    assert (version.extractor, version.extractor_version) == ("passthrough", "1")
    files = await scraping.files(version.storage_key)
    assert files[f"{version.storage_key}/{raw}"] == body.encode(encoding)
    extracted = json.loads(files[f"{version.storage_key}/extracted.json"])
    assert extracted["text"] == body
    assert extracted["extractor"] == {"name": "passthrough", "version": "1"}


class NoticesExtractor:
    """A test-only site-specific extractor: the notices of a town hall's notice page.

    The generic extractor would keep the banner, the related links and the "last updated"
    footer, so every footer change would make a new Source Version.
    """

    name = "example-notices"
    version = "1"

    def extract(self, raw: bytes, url: str) -> Extracted:
        del url
        page = lxml.html.fromstring(raw)
        notices = [
            "\n".join(
                [notice.findtext("h2", "").strip()]
                + [f"- {item.text_content().strip()}" for item in notice.iter("li")]
            )
            for notice in page.find_class("notice")
        ]
        return Extracted(text="\n\n".join(notices), title=page.findtext(".//h1"))


NOTICES = "https://rathaus.beispielstadt.test/bekanntmachungen"
PATTERN = re.compile(r"^https://rathaus\.beispielstadt\.test/bekanntmachungen")


@pytest.fixture
def site_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test-only extractor, registered as a site-specific one: one class, one URL pattern."""
    monkeypatch.setitem(registry.EXTRACTORS, NoticesExtractor.name, NoticesExtractor())
    monkeypatch.setattr(registry, "URL_PATTERNS", [(PATTERN, NoticesExtractor.name)])


@pytest.mark.usefixtures("site_extractor")
async def test_a_site_specific_extractor_reads_the_urls_its_pattern_matches_and_no_others(
    scraping: Scraping,
) -> None:
    other = "https://rathaus.beispielstadt.test/wahlen"
    scraping.web.serve(NOTICES, (PAGES / "notices.html").read_bytes())
    scraping.web.serve(other, (PAGES / "notices.html").read_bytes())
    scraping.web.serve(FEED, rss_feed(Entry(NOTICES), Entry(other)), media_type=RSS)
    await scraping.add_feed("beispielstadt", FEED)

    await scraping.run_now()

    urls = {source.id: source.url for source in await stored_sources(scraping.db)}
    read_by = {urls[version.source_id]: version for version in await stored_versions(scraping.db)}
    assert (read_by[NOTICES].extractor, read_by[other].extractor) == ("example-notices", "html")
    files = await scraping.files(read_by[NOTICES].storage_key)
    extracted = files[f"{read_by[NOTICES].storage_key}/extracted.json"]
    assert json.loads(extracted) == json.loads((PAGES / "notices.json").read_text(encoding="utf-8"))


@pytest.mark.usefixtures("site_extractor")
async def test_the_extractor_a_feed_names_wins_over_url_patterns_and_media_types(
    scraping: Scraping,
) -> None:
    """The page matches the site's pattern and is HTML; its Feed says: keep it as it is."""
    scraping.web.serve(NOTICES, (PAGES / "notices.html").read_bytes())
    scraping.web.serve(FEED, rss_feed(Entry(NOTICES)), media_type=RSS)
    await scraping.add_feed("beispielstadt", FEED, extractor="passthrough")

    await scraping.run_now()

    (version,) = await stored_versions(scraping.db)
    assert version.extractor == "passthrough"
    extracted = json.loads((await scraping.files())[f"{version.storage_key}/extracted.json"])
    assert extracted["text"] == (PAGES / "notices.html").read_bytes().decode()


async def test_a_document_no_extractor_can_read_is_skipped_and_its_feed_goes_on(
    scraping: Scraping,
) -> None:
    """A broken file is the document's failure: the Feed is fine and its other items are read."""
    broken = "https://behoerde.test/reports/broken.pdf"
    scraping.web.serve(broken, b"%PDF-1.7\n this is no PDF at all", media_type=PDF)
    scraping.web.serve(REPORT, pdf_document("Final report."), media_type=PDF)
    scraping.web.serve(FEED, rss_feed(Entry(broken), Entry(REPORT)), media_type=RSS)
    await scraping.add_feed("behoerde", FEED)

    run = await scraping.run_now()

    assert run.result == {
        "feeds_read": 1,
        "versions_new": 1,
        "versions_unchanged": 0,
        "documents_failed": 1,
        "failed_feeds": [],
        "out_of_time": [],
        "feeds": [feed_outcome("behoerde", items=2, new=1, failed=1)],
    }
    (feed,) = [feed for feed in await stored_feeds(scraping.db) if feed.slug == "behoerde"]
    assert (feed.state, feed.last_error) == (FeedState.OK, None)
    (version,) = await stored_versions(scraping.db)
    assert version.storage_key.endswith(str(version.id))
    assert all("broken" not in key for key in await scraping.files())


class BuggyExtractor:
    name = "buggy"
    version = "1"

    def extract(self, raw: bytes, url: str) -> Extracted:
        del raw
        raise KeyError(url)


async def test_an_extractor_bug_skips_the_document_not_the_feed(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(registry.EXTRACTORS, "buggy", BuggyExtractor())
    monkeypatch.setattr(registry, "URL_PATTERNS", [(PATTERN, "buggy")])
    scraping.web.serve(NOTICES, (PAGES / "notices.html").read_bytes())
    scraping.web.serve(REPORT, pdf_document("Final report."), media_type=PDF)
    scraping.web.serve(FEED, rss_feed(Entry(NOTICES), Entry(REPORT)), media_type=RSS)
    await scraping.add_feed("behoerde", FEED)

    run = await scraping.run_now()

    assert (counts(run)["versions_new"], counts(run)["documents_failed"]) == (1, 1)
    assert counts(run)["failed_feeds"] == []
