"""Which extractor reads a document: first match wins (ADR 03 §5).

1. the extractor named on the Feed;
2. the first URL pattern that matches (an ordered list, empty at first, generic last: yt-dlp);
3. the document's media type.

To add a site-specific extractor: one class, one entry in `EXTRACTORS`, one pattern in
`URL_PATTERNS`, one saved page with its expected output as a test (docs/scraping/extractors.md).
To read another media type: one class, one entry in `EXTRACTORS` and one in `media.KNOWN`
(which also names its raw file).
"""

import re
from collections.abc import Mapping, Sequence

from infrasales.extract import media
from infrasales.extract.extractor import Extractor, NoExtractorError
from infrasales.extract.html import HtmlExtractor
from infrasales.extract.passthrough import PassthroughExtractor
from infrasales.extract.pdf import PdfExtractor

EXTRACTORS: Mapping[str, Extractor] = {
    extractor.name: extractor
    for extractor in (HtmlExtractor(), PassthroughExtractor(), PdfExtractor())
}

URL_PATTERNS: Sequence[tuple[re.Pattern[str], str]] = ()  # (URL pattern, extractor name)


def choose(named: str | None, url: str, media_type: str) -> Extractor:
    """The extractor for the document at `url` of `media_type`, on a Feed naming `named`."""
    known = media.known(media_type)
    name = named or _by_pattern(url) or (known.extractor if known else None)
    if name is None:
        msg = f"no extractor for {media_type or 'an unknown media type'}"
        raise NoExtractorError(msg)
    try:
        return EXTRACTORS[name]
    except KeyError:
        msg = f"no extractor named {name!r}"
        raise NoExtractorError(msg) from None


def _by_pattern(url: str) -> str | None:
    return next((name for pattern, name in URL_PATTERNS if pattern.search(url)), None)
