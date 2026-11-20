"""Feed overlap: which Feeds list the same documents, by the recent Source Collection runs.

Each run keeps, per Feed, which of its addresses other Feeds list too (`scrape.FeedOverlap`).
Summed over the runs that finished in a window, that is each Feed's own share (what only it
lists) and the pairs of Feeds that overlap most. The counts are listings: an address counts
once in each run that lists it, so one a Feed lists all week counts in every run of the week.
Results stored before overlap was counted are left out.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy.orm import load_only
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.jobs.names import JobName
from infrasales.jobs.schemas import SourceCollectionResult, typed_result
from infrasales.scheduler.models import JobRun, JobStatus

MAX_DAYS = 90
MAX_RUNS = 1000  # the newest, if more finished in the window: hourly runs for 6 weeks
TOP_PAIRS = 20
# A run is read for its result only; the newest `MAX_RUNS` at most.
_RESULTS = load_only(*(getattr(JobRun, field) for field in ["job", "result"]))


class OverlapQuery(BaseModel):
    """Which runs to count: those that finished in the last `days` days."""

    days: int = Field(default=14, ge=1, le=MAX_DAYS)


class FeedShare(BaseModel):
    """How much of what a Feed listed only it lists."""

    feed: str  # its slug
    runs: int  # the runs counted that read it
    own: int  # its listings no other Feed lists
    shared: int  # its listings another Feed lists too
    own_share: float | None  # own / (own + shared); None: it listed nothing


class FeedPair(BaseModel):
    """Two Feeds listing the same addresses."""

    feed: str  # the slugs, in alphabetical order
    other: str
    # Listed by both in a run, or by one while its Source was filed under the other.
    listings: int


class FeedOverlapReport(BaseModel):
    """Which Feeds list the same documents, over the runs counted."""

    days: int  # the window asked for
    runs: int  # Source Collection runs counted: finished in it, with overlap counted
    feeds: list[FeedShare]  # the least own share first
    pairs: list[FeedPair]  # the most listings first, at most `TOP_PAIRS`


async def report(session: AsyncSession, now: datetime, days: int) -> FeedOverlapReport:
    """The overlap of the Source Collection runs that finished in the `days` days before `now`.

    At most the newest `MAX_RUNS`: a run's result is read whole.
    """
    finished = (
        select(JobRun)
        .options(_RESULTS)
        .where(
            col(JobRun.job) == JobName.SCRAPE,
            col(JobRun.status) == JobStatus.SUCCEEDED,
            col(JobRun.finished_at) >= now - timedelta(days=days),
        )
        .order_by(col(JobRun.finished_at).desc())
        .limit(MAX_RUNS)
    )
    results = (typed_result(run.job, run.result) for run in await session.exec(finished))
    return tally((result for result in results if result is not None), days)


@dataclass(slots=True)
class _Tally:
    runs: int = 0
    own: int = 0
    shared: int = 0


def tally(results: Iterable[SourceCollectionResult], days: int) -> FeedOverlapReport:
    """Each Feed's own share and the top pairs, summed over `results`.

    Listed by both in a run, an address is in both Feeds' `listed_with`: it counts once.
    """
    feeds: dict[str, _Tally] = {}
    pairs = Counter[tuple[str, str]]()
    runs = 0
    for result in results:
        read = [(feed.feed, feed.overlap) for feed in result.feeds if feed.overlap is not None]
        runs += bool(read)
        for slug, overlap in read:
            counted = feeds.setdefault(slug, _Tally())
            counted.runs += 1
            counted.own += overlap.own
            counted.shared += overlap.shared
            for other, listings in overlap.listed_with.items():
                if slug < other:
                    pairs[slug, other] += listings
            for other, listings in overlap.filed_under.items():
                pairs[min(slug, other), max(slug, other)] += listings
    shares = sorted(
        (_share(slug, counted) for slug, counted in feeds.items()),
        key=lambda share: (share.own_share is None, share.own_share or 0, share.feed),
    )
    top = sorted(pairs.items(), key=lambda pair: (-pair[1], pair[0]))[:TOP_PAIRS]
    return FeedOverlapReport(
        days=days,
        runs=runs,
        feeds=shares,
        pairs=[FeedPair(feed=feed, other=other, listings=n) for (feed, other), n in top],
    )


def _share(slug: str, counted: _Tally) -> FeedShare:
    listed = counted.own + counted.shared
    return FeedShare(
        feed=slug,
        runs=counted.runs,
        own=counted.own,
        shared=counted.shared,
        own_share=counted.own / listed if listed else None,
    )
