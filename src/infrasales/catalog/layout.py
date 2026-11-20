"""The folder format of the sink: one folder per Source Version (ADR 03 §2).

```
<run scheduled time, UTC: 2026-10-16T060000Z>/<feed slug>/<source version id>/
    raw.<ext>        the bytes as fetched (transfer encoding decoded, never re-encoded)
    extracted.json   text, title, author, date; names the extractor and its version
    metadata.json    discovery, fetch, content, extraction, identity; written last
```

`metadata.json` repeats the catalog rows so the catalog could be rebuilt from the sink; it holds
no version number (given only at commit): a rebuild orders a Source's versions by fetch time.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from infrasales.core.models import JSONValue
from infrasales.extract import media
from infrasales.extract.extractor import Extracted, Extractor
from infrasales.feeds.lister import Item
from infrasales.feeds.models import Feed
from infrasales.fetch.fetcher import Response, Validators

EXTRACTED = "extracted.json"
METADATA = "metadata.json"  # written last: a folder without it is incomplete


def run_folder(scheduled_for: datetime) -> str:
    """A run's folder: its scheduled time in UTC to the second, without colons."""
    return scheduled_for.astimezone(UTC).strftime("%Y-%m-%dT%H%M%SZ")


def version_folder(run: str, feed_slug: str, version_id: uuid.UUID) -> str:
    """A Source Version's folder: its `storage_key`."""
    return f"{run}/{feed_slug}/{version_id}"


def raw_name(media_type: str) -> str:
    """`raw.html`, `raw.pdf`, `raw.xml` (`application/atom+xml`), …; `raw.bin` if unknown."""
    known = media.known(media_type)
    return f"raw.{known.extension if known else 'bin'}"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class Document:
    """A document as got: fetched (`response`), or carried by the Feed's item (`response` None)."""

    item: Item
    raw: bytes
    media_type: str
    charset: str | None
    fetched_at: datetime
    response: Response | None = None

    @property
    def url(self) -> str:
        """Where it came from: after redirects, if fetched."""
        return self.response.final_url if self.response else self.item.url

    @property
    def http_status(self) -> int | None:
        """The response's status; None: the Feed carried it."""
        return self.response.status if self.response else None

    @property
    def validators(self) -> Validators | None:
        """The response's `ETag` and `Last-Modified`; None: the Feed carried it."""
        return self.response.validators if self.response else None

    @property
    def not_modified(self) -> bool:
        """The server answered a conditional request `304 Not Modified`: no content."""
        return self.response is not None and self.response.not_modified

    @classmethod
    def fetched(cls, item: Item, response: Response) -> Document:
        return cls(
            item,
            response.content,
            response.media_type,
            response.charset,
            response.fetched_at,
            response,
        )


@dataclass(frozen=True, slots=True)
class Reading:
    """A document as got and read by an extractor: what a Source Version is made of."""

    document: Document
    extractor: Extractor
    extracted: Extracted

    @property
    def text_sha256(self) -> str:
        """What tells two versions apart: the hash of the text."""
        return sha256(self.extracted.text.encode())


@dataclass(frozen=True, slots=True)
class Identity:
    source_id: uuid.UUID
    version_id: uuid.UUID
    url: str  # normalised
    run_id: uuid.UUID | None  # None: not run by the scheduler (a notebook)
    run_folder: str


def extracted_json(extractor: Extractor, extracted: Extracted) -> bytes:
    document: dict[str, JSONValue] = {
        "extractor": {"name": extractor.name, "version": extractor.version},
        "title": extracted.title,
        "author": extracted.author,
        "published_at": _time(extracted.published_at),
        "text": extracted.text,
    }
    return _json(document)


def metadata_json(feed: Feed, reading: Reading, identity: Identity) -> bytes:
    document, extractor, extracted = reading.document, reading.extractor, reading.extracted
    item, response = document.item, document.response
    fetch: dict[str, JSONValue] | None = None
    if response is not None:
        fetch = {
            "fetcher": feed.fetcher.value,
            "requested_url": response.url,
            "final_url": response.final_url,
            "status": response.status,
            "headers": dict(response.headers),
            "fetched_at": _time(response.fetched_at),
            "robots": response.robots,
        }
    metadata: dict[str, JSONValue] = {
        "discovery": {
            "feed": {
                "id": str(feed.id),
                "slug": feed.slug,
                "name": feed.name,
                "kind": feed.kind.value,
                "url": feed.url,
            },
            "listed": {
                "url": item.url,
                "title": item.title,
                "published_at": _time(item.published_at),
                "summary": item.summary,
                "author": item.author,
            },
        },
        "fetch": fetch,  # null: the Feed carried the content
        "content": {
            "file": raw_name(document.media_type),
            "media_type": document.media_type,
            "charset": document.charset,
            "size": len(document.raw),
            "raw_sha256": sha256(document.raw),
            "text_sha256": reading.text_sha256,
        },
        "extraction": {
            "extractor": extractor.name,
            "version": extractor.version,
            "partial": extracted.partial,
        },
        "identity": {
            "source_id": str(identity.source_id),
            "source_version_id": str(identity.version_id),
            "url": identity.url,
            "run_id": str(identity.run_id) if identity.run_id else None,
            "run_folder": identity.run_folder,
        },
    }
    return _json(metadata)


def _time(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _json(document: JSONValue) -> bytes:
    return json.dumps(document, ensure_ascii=False, indent=2).encode()
