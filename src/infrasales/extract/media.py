"""The media types InfraSales knows: the name of a document's raw file, and who reads it.

One table for both the folder format (`raw.<extension>`, `infrasales.catalog.layout`) and the choice
of extractor by media type (`infrasales.extract.registry`): a new type is one line here.
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MediaType:
    extension: str  # of the raw file: `raw.html`, `raw.pdf`, …
    extractor: str | None  # the extractor that reads it, by name; None: none does


HTML = MediaType("html", "html")
JSON = MediaType("json", "passthrough")
PDF = MediaType("pdf", "pdf")
XML = MediaType("xml", "passthrough")

KNOWN: Mapping[str, MediaType] = {
    "application/json": JSON,
    "application/pdf": PDF,
    "application/x-pdf": PDF,
    "application/xhtml+xml": HTML,
    "application/xml": XML,
    "text/html": HTML,
    "text/plain": MediaType("txt", None),
    "text/xml": XML,
}

BY_SUFFIX: Mapping[str, MediaType] = {"json": JSON, "xml": XML}  # `application/atom+xml`


def known(media_type: str) -> MediaType | None:
    """The type by its exact name, else by its structured syntax suffix (RFC 6839).

    The exact name first: `application/xhtml+xml` is HTML, not XML.
    """
    if found := KNOWN.get(media_type):
        return found
    _, plus, suffix = media_type.rpartition("+")
    return BY_SUFFIX.get(suffix) if plus else None
