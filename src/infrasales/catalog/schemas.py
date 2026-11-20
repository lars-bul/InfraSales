"""What the Source API reads: Sources, their versions, a version's text."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from infrasales.feeds.models import FeedCategory


class FeedRef(BaseModel):
    """The Feed a version was filed under."""

    slug: str
    name: str


class VersionRead(BaseModel):
    """A committed Source Version: when and how it was got, and what it is called."""

    id: UUID
    number: int  # 1 is the Source's first text, each higher one a changed text
    fetched_at: datetime
    run_id: UUID | None  # the run that wrote it; None once the run is pruned
    feed: FeedRef
    http_status: int | None  # None: the Feed carried the content (API items)
    media_type: str
    partial: bool  # only what the Feed said (a paywall), or too little text
    title: str | None  # None for versions stored before titles were kept: see the text
    published_at: datetime | None
    extractor: str
    extractor_version: str
    superseded_at: datetime | None  # None: the current text


class SourceListed(BaseModel):
    """A Source in the list, with the version it is listed by: its latest, or the run's."""

    id: UUID
    url: str
    first_seen_at: datetime
    last_checked_at: datetime
    versions: int  # its committed versions, older ones pruned by retention not counted
    version: VersionRead


class SourceRead(BaseModel):
    """A Source with every committed version, newest first."""

    id: UUID
    url: str
    first_seen_at: datetime
    last_checked_at: datetime
    versions: list[VersionRead]


class VersionText(BaseModel):
    """A version's text as its extractor read it (`extracted.json`)."""

    number: int
    title: str | None
    author: str | None
    published_at: datetime | None
    text: str


class SourceFilter(BaseModel):
    """Which Sources to list or count, each by its listed version: its latest, or the run's.

    Every filter given must hold; a filter given several values holds for any one of them.
    """

    feed: list[Annotated[str, Field(max_length=64)]] = Field(
        default_factory=list[str],
        max_length=100,
        description="Feeds' slugs: the Sources listed by a version filed under one of them",
    )
    category: list[FeedCategory] = Field(
        default_factory=list[FeedCategory],
        description="The Sources listed by a version whose Feed is of one of these categories",
    )
    run: UUID | None = None  # a run: the Sources it wrote a version of, by that version
    q: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    since: AwareDatetime | None = Field(
        default=None, description="The listed version was fetched then or later"
    )
    until: AwareDatetime | None = Field(
        default=None, description="The listed version was fetched before then"
    )
    changed: bool | None = Field(
        default=None, description="True: more than one committed version; false: exactly one"
    )
    partial: bool | None = Field(
        default=None, description="The listed version is partial (a paywall), or is not"
    )


class SourceQuery(SourceFilter):
    """Which Sources to list: a page back from `before` (a listed version's ID), filtered."""

    limit: int = Field(default=20, ge=1, le=50)
    before: UUID | None = None


class SourceCount(BaseModel):
    """How many Sources the filters match, every page together."""

    count: int
