"""The fetcher port: how a Feed's documents are got. A Feed names its fetcher (`http` today).

Every fetcher enforces the rules nobody may skip (public addresses only, a size cap, robots.txt,
a pause between requests) and answers with a `Response`. A conditional request that the server
answers `304 Not Modified` is a response, not an error.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message
from enum import StrEnum
from typing import Protocol

from infrasales.core.failures import ExpectedError
from infrasales.core.models import utcnow


class FetcherName(StrEnum):
    """The fetchers a Feed may name; another needs an audited admin change (ADR 03 §6)."""

    HTTP = "http"


ROBOTS_DECISION = "infrasales.robots"  # the request extension holding its robots.txt decision

# Response headers kept with a Source Version (`metadata.json`): never cookies.
KEPT_HEADERS = (
    "cache-control",
    "content-language",
    "content-length",
    "content-type",
    "date",
    "etag",
    "last-modified",
    "retry-after",
    "x-robots-tag",
)


@dataclass(frozen=True, slots=True)
class Validators:
    """What makes a request conditional (RFC 9110 §13): a response's `ETag`, `Last-Modified`.

    Kept as the server sent them, stored on the Source, sent back on its next check.
    """

    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class Response:
    url: str  # as requested
    final_url: str  # after redirects
    status: int  # 2xx, or 304 for an unchanged document
    headers: Mapping[str, str]  # `KEPT_HEADERS` the server sent, lower-case names
    content: bytes  # the body as sent, transfer encoding (gzip, …) decoded; empty for a 304
    fetched_at: datetime = field(default_factory=utcnow)
    robots: str = "not checked"  # the robots.txt decision: "allowed", "allowed: no robots.txt"

    @property
    def not_modified(self) -> bool:
        return self.status == 304  # noqa: PLR2004

    @property
    def media_type(self) -> str:
        """The `Content-Type` without parameters, lower-case (`text/html`); "" if not sent."""
        return _content_type(self.headers).get_content_type() if self._typed else ""

    @property
    def charset(self) -> str | None:
        """The `Content-Type`'s charset parameter, if any."""
        return _content_type(self.headers).get_content_charset() if self._typed else None

    @property
    def validators(self) -> Validators:
        return Validators(self.headers.get("etag"), self.headers.get("last-modified"))

    @property
    def _typed(self) -> bool:
        return bool(self.headers.get("content-type"))


def _content_type(headers: Mapping[str, str]) -> Message:
    message = Message()
    message["content-type"] = headers["content-type"]
    return message


class FetchError(ExpectedError):
    """A document could not be got; `reason` is what a failed Feed records (`last_error`)."""

    reason = "fetch failed"


class StatusError(FetchError):
    """The server answered with an error status; the response tells which (429, 404, …)."""

    def __init__(self, response: Response) -> None:
        super().__init__(f"HTTP {response.status} for {response.final_url}")
        self.response = response
        self.reason = f"http {response.status}"


class RefusedError(StatusError):
    """A block answer (`401`, `403`, `451`) without a bot wall's signs: this document is refused.

    For a document, its own failure; for a Feed's listing request, the Feed is blocked.
    """


class BlockedError(ExpectedError):
    """The site refuses InfraSales' bot (a bot wall's challenge, its listing refused): blocked.

    Not a `FetchError`: it is no document's failure but the Feed's, and nothing may try the
    site's other documents to get around it (ADR 03 §6).
    """

    reason = "blocked"

    def __init__(self, url: str, status: int) -> None:
        super().__init__(f"HTTP {status} from a bot wall at {url}")
        self.status = status


class Fetcher(Protocol):
    async def fetch(self, url: str, validators: Validators | None = None) -> Response:
        """GET `url`; conditionally with `validators` (a Source's stored values).

        Returns 2xx and 304 responses; raises `BlockedError` when the site refuses the bot,
        `OutOfTimeError` when the run's time for the Feed is up, `FetchError` otherwise.
        """
        ...
