import re

import pytest

from infrasales.extract import registry
from infrasales.extract.extractor import NoExtractorError
from infrasales.extract.html import HtmlExtractor

URL = "https://news.test/a"


def test_the_feeds_extractor_wins_over_the_media_type() -> None:
    assert registry.choose("html", URL, "application/pdf").name == "html"


def test_a_matching_url_pattern_wins_over_the_media_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "URL_PATTERNS", [(re.compile(r"^https://news\.test/"), "html")])

    assert registry.choose(None, URL, "image/png").name == "html"
    with pytest.raises(NoExtractorError):
        registry.choose(None, "https://other.test/a", "image/png")


def test_otherwise_the_media_type_decides() -> None:
    assert isinstance(registry.choose(None, URL, "application/xhtml+xml"), HtmlExtractor)


@pytest.mark.parametrize(
    ("named", "media_type"), [(None, "image/png"), (None, ""), ("nope", "text/html")]
)
def test_no_extractor_for_unknown_names_and_media_types(named: str | None, media_type: str) -> None:
    with pytest.raises(NoExtractorError):
        registry.choose(named, URL, media_type)
