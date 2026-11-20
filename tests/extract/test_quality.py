"""The quality gate's rules; what is stored is tested through the scrape job."""

from infrasales.extract.extractor import Extracted
from infrasales.extract.quality import MIN_TEXT_CHARS, gate
from infrasales.feeds.lister import Item

TEXT = "a" * MIN_TEXT_CHARS


def test_a_complete_text_passes_unchanged() -> None:
    extracted = Extracted(TEXT, title="Title")

    assert gate(Item("https://news.test/a", summary="Summary"), extracted) is extracted


def test_a_feed_summary_in_html_becomes_the_partial_text() -> None:
    item = Item("https://news.test/a", title="Feed title", summary="<p>One\n <i>two</i></p>")

    partial = gate(item, Extracted("Subscribe", title="Page title"))

    assert (partial.text, partial.title, partial.partial) == ("One two", "Feed title", True)


def test_control_characters_in_a_summary_become_spaces() -> None:
    """A Feed may send them (a vertical tab, a form feed, …); lxml refuses them."""
    item = Item("https://news.test/a", summary="One\x0btwo\x01 <b>three</b>\x7f")

    assert gate(item, Extracted("Subscribe", title="T")).text == "One two three"


def test_an_empty_summary_keeps_the_extracted_text() -> None:
    partial = gate(Item("https://news.test/a", summary="  "), Extracted("Short", title="T"))

    assert (partial.text, partial.title, partial.partial) == ("Short", "T", True)


def test_a_complete_text_without_a_title_of_its_own_takes_the_feeds() -> None:
    """A PDF often names no title in its metadata; the Feed's listing does."""
    item = Item("https://news.test/a.pdf", title="Feed title", summary="Summary")

    complete = gate(item, Extracted(TEXT))

    assert (complete.text, complete.title, complete.partial) == (TEXT, "Feed title", False)


def test_a_text_without_any_title_is_partial() -> None:
    assert gate(Item("https://news.test/a.pdf"), Extracted(TEXT)).partial
