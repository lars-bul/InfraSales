"""The Lister port: what a Feed lists now, as items. One Lister per Feed kind."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from infrasales.core.failures import ExpectedError
from infrasales.feeds.models import Feed
from infrasales.fetch.fetcher import Fetcher

MAX_ITEMS = 300  # items read per Feed and run: the newest, the scrape then takes the unseen


@dataclass(frozen=True, slots=True)
class Item:
    """One document a Feed lists, with what the Feed says about it (`metadata.json` discovery).

    An API item may carry its full `content` (with its `media_type`): no page fetch is needed.
    """

    url: str
    title: str | None = None
    published_at: datetime | None = None
    summary: str | None = None
    author: str | None = None
    content: bytes | None = None
    media_type: str | None = None  # of `content`


class ListerSettings(BaseModel):
    """The settings of a Feed of one kind (`feed.settings`); unknown keys are refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Lister(Protocol):
    @property
    def settings(self) -> type[ListerSettings]:
        """What a Feed of this kind may set: adding a Feed validates its settings with it."""
        ...

    async def list(self, feed: Feed, fetcher: Fetcher) -> list[Item]:
        """The items `feed` lists now, newest first where the Feed tells, at most `MAX_ITEMS`.

        Raises when the Feed cannot be read (`FetchError`, `UnreadableFeedError`, …): the
        Feed failed; the scrape records it and goes on with the next.
        """
        ...


class UnreadableFeedError(ExpectedError):
    """The Feed answered, but not with what its kind expects (no RSS, no sitemap, …)."""

    reason = "unreadable"
