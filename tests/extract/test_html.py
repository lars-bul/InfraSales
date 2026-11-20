import json
from datetime import UTC, datetime

from infrasales.extract.html import HtmlExtractor

URL = "https://news.test/2026/10/story"
BODY = "The authority opened proceedings on the heat network tariff. " * 12


def page(ld: object, body: str = "<p>Short teaser.</p>") -> bytes:
    script = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    return f"<html><head>{script}</head><body>{body}</body></html>".encode()


def test_json_ld_completes_what_the_page_text_lacks() -> None:
    """A teaser on the page, the whole article in its JSON-LD (common on news sites)."""
    ld = {
        "@graph": [
            {"@type": "WebPage", "name": "Story"},
            {
                "@type": ["NewsArticle"],
                "headline": "Tariff reviewed",
                "author": [{"name": "Jane Doe"}, "John Roe"],
                "datePublished": "2026-10-16T06:00:00Z",
                "articleBody": f"<p>{BODY}</p>",
            },
        ]
    }

    extracted = HtmlExtractor().extract(page(ld), URL)

    assert extracted.text == BODY.strip()
    assert extracted.title == "Tariff reviewed"
    assert extracted.author == "Jane Doe, John Roe"
    assert extracted.published_at == datetime(2026, 10, 16, 6, tzinfo=UTC)


def test_broken_or_foreign_json_ld_is_ignored() -> None:
    broken = b'<html><head><script type="application/ld+json">{not json</script></head></html>'
    other = page({"@type": "Organization", "name": "News Inc."})

    for raw in (broken, other, b"", b"\x00\x01"):
        extracted = HtmlExtractor().extract(raw, URL)
        assert (extracted.title, extracted.author, extracted.published_at) == (None, None, None)


def test_an_author_given_as_one_name_and_a_plain_body() -> None:
    ld = {"@type": "Article", "author": {"name": " Jane Doe "}, "articleBody": BODY, "headline": 1}

    extracted = HtmlExtractor().extract(page(ld), URL)

    assert (extracted.author, extracted.title, extracted.text) == ("Jane Doe", None, BODY.strip())


def test_a_page_teaser_longer_than_trafilatura_needs_is_completed_by_the_json_ld_body() -> None:
    """Trafilatura reads the page's teaser (above its own minimum), not the JSON-LD body."""
    teaser = (
        "Subscribers read on. " + "The heat network tariff is under review by the authority. " * 7
    )
    article = f"<article><h1>Tariff</h1><p>{teaser}</p></article>"
    ld = {"@type": "NewsArticle", "headline": "Tariff", "articleBody": BODY}

    extracted = HtmlExtractor().extract(page(ld, article), URL)

    assert extracted.text == BODY.strip()


def test_a_body_that_is_no_html_is_taken_as_text_and_odd_json_ld_is_skipped() -> None:
    """An `articleBody` lxml cannot parse is kept as written; JSON-LD that is no object, too."""
    body = "<!-- " + BODY + " -->"
    scripts = [json.dumps("a string"), json.dumps({"@graph": [42, {"@type": "Person"}]})]
    head = "".join(f'<script type="application/ld+json">{s}</script>' for s in scripts)
    ld = {"@type": "NewsArticle", "articleBody": body}
    raw = page(ld).replace(b"<head>", f"<head>{head}".encode())

    extracted = HtmlExtractor().extract(raw, URL)

    assert extracted.text.split() == body.split()
