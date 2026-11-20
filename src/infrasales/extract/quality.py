"""The quality gate: is an extracted text the whole document, or only part of it?

A text is complete when it has a title (its own, or the Feed's: a PDF often names none in its
metadata, as the Förderregister's printed documents) and at least `MIN_TEXT_CHARS` characters,
and its extractor did not find it incomplete (a paywall's teaser: the page says so in its JSON-LD,
`isAccessibleForFree: false`, as Google asks publishers of paywalled articles to). An incomplete
text (paywalled, too short, a scanned PDF without text) is stored as a `partial` Source Version
with what the Feed gave freely: its title, its summary as the text, its date and author (the link
is the Source's address). Without a summary from the Feed the extracted text is kept: a short
page's text still shows when it changes.
"""

import re
from dataclasses import replace

import lxml.html

from infrasales.extract.extractor import Extracted
from infrasales.feeds.lister import Item

MIN_TEXT_CHARS = 250  # trafilatura's MIN_EXTRACTED_SIZE: below it, it finds no article text
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # lxml refuses them (ValueError)


def complete(extracted: Extracted) -> bool:
    return (
        not extracted.partial
        and bool(extracted.title)
        and len(extracted.text.strip()) >= MIN_TEXT_CHARS
    )


def gate(item: Item, extracted: Extracted) -> Extracted:
    """`extracted` if it is complete; else a `partial` text from what the Feed said."""
    titled = extracted if extracted.title else replace(extracted, title=item.title)
    if complete(titled):
        return titled
    summary = _plain(item.summary)
    return Extracted(
        text=summary or extracted.text,
        title=item.title or extracted.title,
        author=item.author or extracted.author,
        published_at=item.published_at or extracted.published_at,
        partial=True,
    )


def _plain(summary: str | None) -> str:
    """A Feed's summary is often HTML: its text, whitespace collapsed; control characters too."""
    if not summary or not summary.strip():
        return ""
    fragment = lxml.html.fragment_fromstring(_CONTROL.sub(" ", summary), create_parent="div")
    return " ".join(fragment.text_content().split())
