"""Feeds: the places InfraSales collects Sources from (CONTEXT.md)."""

from datetime import datetime
from enum import StrEnum

from sqlmodel import Field

from infrasales.core.models import BaseTable, JSONType, JSONValue, UTCDateTime, enum_type
from infrasales.fetch.fetcher import FetcherName

MAX_URL_LENGTH = 2048


class FeedKind(StrEnum):
    """How a Feed's new items are listed: one Lister per kind (`infrasales.feeds.kinds`)."""

    RSS = "rss"  # an RSS or Atom feed
    SITEMAP = "sitemap"  # the newest entries of a sitemap


class FeedState(StrEnum):
    OK = "ok"  # read without failure the last time, or never read yet
    FAILING = "failing"  # the last read failed: `last_error` says why
    BLOCKED = "blocked"  # the site blocks InfraSales' bot: a person must decide (ADR 03 §6)


class FeedCategory(StrEnum):
    """Who publishes what a Feed lists: the Feeds and Sources pages filter and group by it."""

    PRESS = "press"  # trade press and news sites
    MUNICIPALITY = "municipality"  # a municipality: its council information system, its website
    UTILITY = "utility"  # a Stadtwerk or network operator: news, heat network roadmaps
    PROCUREMENT = "procurement"  # tenders and awards: procurement portals, OCDS, TED
    AUTHORITY = "authority"  # a state or federal authority: energy atlases, funding, registers


class Feed(BaseTable, table=True):
    name: str = Field(max_length=200)
    slug: str = Field(max_length=64, unique=True)  # names its folders in the sink
    kind: FeedKind = Field(sa_type=enum_type(FeedKind))
    category: FeedCategory = Field(default=FeedCategory.PRESS, sa_type=enum_type(FeedCategory))
    url: str = Field(max_length=MAX_URL_LENGTH, unique=True)
    settings: dict[str, JSONValue] = Field(default_factory=dict, sa_type=JSONType)  # per kind
    fetcher: FetcherName = Field(default=FetcherName.HTTP, sa_type=enum_type(FetcherName))
    extractor: str | None = Field(default=None, max_length=64)  # overrides the choice by document
    enabled: bool = True
    state: FeedState = Field(default=FeedState.OK, sa_type=enum_type(FeedState))
    last_error: str | None = Field(default=None, max_length=255)  # a reason, never details
    last_scraped_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
