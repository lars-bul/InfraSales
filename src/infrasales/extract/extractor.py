"""The extractor port: a document's raw bytes become its text and metadata.

Every extractor has a name (what a Feed may name, and what `extracted.json` records) and a
version: change the version whenever the output for the same bytes may change (new rules, a new
library release), so a re-check can tell an extractor upgrade from a content change.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import structlog

from infrasales.core.failures import ExpectedError

_log = structlog.stdlib.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Extracted:
    text: str  # what changes count on: two versions differ when their texts do
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    partial: bool = False  # only part of the document's text (a paywall's teaser, too short)


class Extractor(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def extract(self, raw: bytes, url: str) -> Extracted:
        """Blocking and CPU-bound: callers run it with `asyncio.to_thread`."""
        ...


class ExtractionError(ExpectedError):
    """The document cannot be read: it is skipped, its Feed goes on. `reason` says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class NoExtractorError(ExtractionError):
    """No extractor reads this document (an unknown name, or an unsupported media type)."""


def guarded_extract(extractor: Extractor, raw: bytes, url: str) -> Extracted:
    """`extractor.extract`, any failure an `ExtractionError`: one bad file must not fail its Feed.

    Like Scrapy's callback errors: an extractor bug or a file it chokes on is logged and that
    document skipped (it is tried again in the next run, since nothing was stored).
    """
    try:
        return extractor.extract(raw, url)
    except ExtractionError:
        raise
    except Exception as error:
        _log.exception("extract.failed", extractor=extractor.name, url=url)
        msg = f"{extractor.name} extractor failed ({type(error).__name__})"
        raise ExtractionError(msg) from error
