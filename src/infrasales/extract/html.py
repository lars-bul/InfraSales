"""The generic HTML extractor: trafilatura, completed by the page's JSON-LD.

Ported from the draft branch `feat/core-foundation-scraper` (lars-bul).
"""

import json
from collections.abc import Iterator
from importlib.metadata import version
from typing import Any, cast

import lxml.etree
import lxml.html
import trafilatura

from infrasales.core.dates import parse_date
from infrasales.core.text import stripped
from infrasales.extract.extractor import Extracted

ARTICLE_TYPES = frozenset(
    {"Article", "NewsArticle", "BlogPosting", "TechArticle", "ReportageNewsArticle", "Report"}
)
BODY_FALLBACK_CHARS = 500  # trafilatura's text shorter: the JSON-LD articleBody, if longer
_RULES = 2  # raise when the rules below change what the same page gives (2: paywalls)


class HtmlExtractor:
    name = "html"
    version = f"{_RULES}+trafilatura-{version('trafilatura')}"

    def extract(self, raw: bytes, url: str) -> Extracted:
        """Bytes, not text: the parsers detect the page's own encoding."""
        found = trafilatura.extract(
            raw, url=url, output_format="json", with_metadata=True, include_comments=False
        )
        data: dict[str, Any] = json.loads(found) if found else {}
        ld = _json_ld(raw)
        text = str(data.get("text") or "").strip()
        body = _plain(ld.get("articleBody"))
        if len(text) < BODY_FALLBACK_CHARS and len(body) > len(text):
            text = body
        return Extracted(
            text=text,
            title=stripped(data.get("title")) or stripped(ld.get("headline")),
            author=stripped(data.get("author")) or _author(ld.get("author")),
            published_at=parse_date(ld.get("datePublished")) or parse_date(data.get("date")),
            partial=_paywalled(ld),
        )


def _paywalled(ld: dict[str, Any]) -> bool:
    """Whether the page says it is not free to read: what InfraSales sees is a teaser.

    Told by schema.org `isAccessibleForFree`, as Google asks publishers of paywalled articles.
    """
    free = ld.get("isAccessibleForFree", True)
    return free is False or (isinstance(free, str) and free.strip().lower() == "false")


def _author(value: object) -> str | None:
    if isinstance(value, dict):
        return stripped(cast("dict[str, object]", value).get("name"))
    if isinstance(value, list):
        names = [name for item in cast("list[object]", value) if (name := _author(item))]
        return ", ".join(names) or None
    return stripped(value)


def _plain(value: object) -> str:
    """`articleBody` is sometimes HTML."""
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        return lxml.html.fromstring(value).text_content().strip()
    except ValueError, lxml.etree.LxmlError:
        return value.strip()


def _nodes(value: object) -> Iterator[dict[str, Any]]:
    if isinstance(value, list):
        for item in cast("list[object]", value):
            yield from _nodes(item)
    elif isinstance(value, dict):
        node = cast("dict[str, Any]", value)
        yield node
        yield from _nodes(node.get("@graph", []))


def _types(value: object) -> set[str]:
    """A JSON-LD `@type`: one name, or a list of them."""
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {item for item in cast("list[object]", value) if isinstance(item, str)}
    return set()


def _json_ld(page: bytes) -> dict[str, Any]:
    """The page's first Article-like JSON-LD object, or {}."""
    try:
        doc = lxml.html.fromstring(page)
    except ValueError, lxml.etree.LxmlError:
        return {}
    scripts = cast("list[str]", doc.xpath('//script[@type="application/ld+json"]/text()'))
    for raw in scripts:
        try:
            loaded = json.loads(raw)
        except ValueError:
            continue
        for node in _nodes(loaded):
            if _types(node.get("@type")) & ARTICLE_TYPES:
                return node
    return {}
