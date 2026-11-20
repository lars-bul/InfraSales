"""The scrape job: the new documents of every enabled Feed become Source Versions (ADR 03).

One attempt, one small function per step (later work changes one step, not the loop):

    scrape → versions.sweep             leftovers of a crashed attempt: `writing` versions
           → enabled_feeds
           → feed_slugs                 every Feed's slug, disabled ones too: where a Source
                                        is filed (`Listing.file`)
           → read_feed, per Feed        a failing Feed is recorded, the others go on; a
                                        blocked one is alerted; its share of the run's time
               → list_items             the Lister of the Feed's kind
               → collect, per item      each URL once per run; a known URL: check_known;
                                        a failing item is skipped, its Feed goes on; who
                                        else lists the URL is counted (`Listing`)
                   → get               fetched by the Feed's fetcher, or carried by the Feed
                   → extract            by the Feed's, a URL pattern's or the media type's
                                        extractor, in a thread: it is CPU-bound
                   → store              `writing` row, files (metadata.json last), commit
                 check_known            a known URL, if `due`: got again conditionally, its
                                        text hash compared with the latest version's: the
                                        same → mark_checked, changed → store

A bot wall on the Feed's own site blocks the Feed; one on another site (Heizungsforum links
anywhere) fails only that document, and the run fetches nothing more of that site (`walled`).

The run fails (and is retried and alerted as usual) only when every Feed it read failed. It
reports how far it got (`JobContext.progress`, `Reporter`): when a Feed starts, once it is listed,
every few seconds while its items are read, and when it is done. "Run now" shows it.
Fetching is polite: robots.txt and pauses are the fetcher's (`infrasales.fetch.fetchers`).

The run folder is the run's scheduled time (a manual run's: when it was requested), so every
attempt of a run writes into it, each version into a fresh folder of its own.
"""

import asyncio
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

import structlog
from sqlmodel import col, select

from infrasales.catalog import versions
from infrasales.catalog.layout import (
    EXTRACTED,
    METADATA,
    Document,
    Identity,
    Reading,
    extracted_json,
    metadata_json,
    raw_name,
    run_folder,
    sha256,
    version_folder,
)
from infrasales.catalog.models import Source, SourceVersion
from infrasales.catalog.urls import MalformedUrlError, normalize_url
from infrasales.core.db import Database
from infrasales.core.failures import ExpectedError
from infrasales.core.models import JSONValue, utcnow
from infrasales.core.tasks import raise_if_cancelled
from infrasales.extract import quality, registry
from infrasales.extract.extractor import ExtractionError, Extractor, guarded_extract
from infrasales.feeds.alerts import FeedBlocked
from infrasales.feeds.kinds import lister_for
from infrasales.feeds.lister import Item
from infrasales.feeds.models import MAX_URL_LENGTH, Feed, FeedState
from infrasales.feeds.service import note_read
from infrasales.fetch.fetcher import (
    BlockedError,
    Fetcher,
    FetcherName,
    FetchError,
    RefusedError,
    Validators,
)
from infrasales.fetch.fetchers import open_fetchers
from infrasales.fetch.http import Network
from infrasales.fetch.pacing import REAL_TIME, Budget, Clock, OutOfTimeError
from infrasales.fetch.robots import RobotsCache
from infrasales.fetch.walls import same_site, site
from infrasales.scheduler.registry import (
    UNREPORTED,
    UNTRACED,
    JobContext,
    Notice,
    Notifier,
    Progress,
    Trace,
)
from infrasales.sink.store import Sink

_log = structlog.stdlib.get_logger(__name__)
_REASON_LENGTH = 255
_UNKNOWN_MEDIA_TYPE = "application/octet-stream"
_ALERT_SECONDS = 30  # telling an admin may not hold up the run
REPORT_SECONDS = 2.0  # at least between two reports while a Feed's items are read: a write each


@dataclass(frozen=True, slots=True)
class FailedFeed:
    feed: str  # its slug
    reason: str  # what the Feed's `last_error` says: "blocked", "unsafe address", "http 404", …


@dataclass(frozen=True, slots=True)
class OutOfTime:
    feed: str  # its slug
    unread: int | None  # listed documents left for the next run; None: not even listed


@dataclass(slots=True)
class FeedOverlap:
    """Which of a Feed's addresses other Feeds list too: how much it adds of its own.

    Each address counts once per Feed. In this run, both Feeds count it (`listed_with`); before
    it, only the Feed listing it now knows: the catalog files a Source under one Feed alone.
    """

    own: int = 0  # addresses only it lists: no other Feed in this run, none filed them before
    shared: int = 0  # addresses another Feed lists too; own + shared: every address it got to
    listed_with: dict[str, int] = field(default_factory=dict[str, int])  # by slug: in this run
    # By slug: its Source filed under another Feed, which did not list it in this run.
    filed_under: dict[str, int] = field(default_factory=dict[str, int])

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "own": self.own,
            "shared": self.shared,
            "listed_with": dict(self.listed_with),
            "filed_under": dict(self.filed_under),
        }


@dataclass(slots=True)
class FeedOutcome:
    """How the run read one Feed: what it listed, what became of each item, how long it took."""

    feed: str  # its slug
    items: int = 0  # listed: 0 when the listing failed or was out of time
    new: int = 0  # by `Collected`: what became of each item read
    unchanged: int = 0
    known: int = 0
    seen: int = 0
    failed: int = 0
    unread: int | None = 0  # listed, left unread: out of time, or the Feed failed; None: not listed
    reason: str | None = None  # the Feed failed: its `last_error`
    out_of_time: bool = False  # its share of the run's time was used up: the rest waits
    seconds: float = 0.0  # reading it, by the run's clock: pauses in, reports and alerts out
    overlap: FeedOverlap = field(default_factory=FeedOverlap)  # grows as later Feeds are read
    walled: list[str] = field(default_factory=list[str])  # other sites whose wall it met

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "feed": self.feed,
            "items": self.items,
            "new": self.new,
            "unchanged": self.unchanged,
            "known": self.known,
            "seen": self.seen,
            "failed": self.failed,
            "unread": self.unread,
            "reason": self.reason,
            "out_of_time": self.out_of_time,
            "seconds": round(self.seconds, 3),
            "overlap": self.overlap.to_json(),
            "walled": list(self.walled),
        }


@dataclass(slots=True)
class ScrapeResult:
    """What a run did, stored as the run's result: the run history explains it."""

    feeds_read: int = 0  # enabled Feeds this run tried to read, failed ones included
    versions_new: int = 0  # Source Versions committed: new Sources, or changed texts
    versions_unchanged: int = 0  # known Sources checked again and found unchanged
    documents_failed: int = 0  # listed documents that could not be got or read: skipped
    failed_feeds: list[FailedFeed] = field(default_factory=list[FailedFeed])
    out_of_time: list[OutOfTime] = field(default_factory=list[OutOfTime])  # the rest waits
    feeds: list[FeedOutcome] = field(default_factory=list[FeedOutcome])  # each, in reading order

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "feeds_read": self.feeds_read,
            "versions_new": self.versions_new,
            "versions_unchanged": self.versions_unchanged,
            "documents_failed": self.documents_failed,
            "failed_feeds": [{"feed": f.feed, "reason": f.reason} for f in self.failed_feeds],
            "out_of_time": [{"feed": f.feed, "unread": f.unread} for f in self.out_of_time],
            "feeds": [f.to_json() for f in self.feeds],
        }

    def progress(self, feeds: int, reading: Underway | None = None) -> dict[str, JSONValue]:
        """How far a run reading `feeds` Feeds got, `reading` one now: as "Run now" shows it."""
        done = self.feeds if reading is None else self.feeds[:-1]  # the one being read: last
        return {
            "feeds_total": feeds,
            "feeds_done": len(done),
            "versions_new": self.versions_new,
            "current": None if reading is None else reading.to_json(),
            "latest": done[-1].to_json() if done else None,
        }


@dataclass(slots=True)
class Underway:
    """The Feed being read: its outcome so far, and whether its list is in yet."""

    outcome: FeedOutcome
    listed: bool = False

    def to_json(self) -> dict[str, JSONValue]:
        outcome = self.outcome
        return {
            "feed": outcome.feed,
            "items": outcome.items if self.listed else None,  # None: still listing
            "done": outcome.items - (outcome.unread or 0) if self.listed else 0,
            "new": outcome.new,
        }


@dataclass(slots=True)
class Reporter:
    """Tells `progress` how far the run got, the database's to keep (`JobContext.progress`).

    A Feed's start, its list and its end are told at once; its items at most every `every`
    seconds by `clock` (the network's), so a Feed of known, unfetched items is no write each.
    """

    progress: Progress
    feeds: int  # the enabled Feeds the run reads
    clock: Clock = REAL_TIME
    every: float = REPORT_SECONDS
    reading: Underway | None = None
    spent: float = 0.0  # seconds by `clock` spent telling: no Feed's reading time
    _told: float = -math.inf  # when last told, by `clock`

    async def started(self, result: ScrapeResult, outcome: FeedOutcome) -> None:
        self.reading = Underway(outcome)
        await self._tell(result)

    async def listed(self, result: ScrapeResult) -> None:
        if self.reading is not None:
            self.reading.listed = True
        await self._tell(result)

    async def item(self, result: ScrapeResult) -> None:
        """An item is done: told, unless the last report is less than `every` seconds old."""
        if self.clock.monotonic() - self._told >= self.every:
            await self._tell(result)

    async def finished(self, result: ScrapeResult) -> None:
        self.reading = None
        await self._tell(result)

    async def _tell(self, result: ScrapeResult) -> None:
        self._told = self.clock.monotonic()
        await self.progress(result.progress(self.feeds, self.reading))
        self.spent += self.clock.monotonic() - self._told


class Collected(StrEnum):
    """What became of one listed item."""

    NEW = "new"  # stored as a new Source Version: a new URL, or a known one's changed text
    UNCHANGED = "unchanged"  # known, checked again, the same text
    KNOWN = "known"  # known, not due for a check yet
    SEEN = "seen"  # listed before in this run (by this Feed or another): handled once
    FAILED = "failed"  # could not be got or read: skipped


def _count(counts: dict[str, int], feed: str, by: int = 1) -> None:
    if counted := counts.get(feed, 0) + by:
        counts[feed] = counted
    else:
        counts.pop(feed, None)


@dataclass(slots=True)
class Listing:
    """One address in this run: which Feeds listed it, and which Feed its Source is filed under.

    The first Feed handled it; the others found it `seen`. Filed: `Source.first_feed_id`.
    """

    feeds: list[FeedOutcome]  # in reading order
    filed: str | None = None  # a slug; None: a new address, or not looked up (too long)

    @classmethod
    def first(cls, outcome: FeedOutcome) -> Listing:
        """Listed by `outcome`'s Feed, the first in this run: its own, unless `file` says not."""
        outcome.overlap.own += 1
        return cls([outcome])

    def file(self, feed: str | None) -> None:
        """Its Source is filed under `feed` (None: a Feed gone meanwhile): shared, if another."""
        (handler,) = self.feeds  # looked up by the first Feed, before any other lists it
        self.filed = feed
        if feed is not None and feed != handler.feed:
            handler.overlap.own -= 1
            handler.overlap.shared += 1
            _count(handler.overlap.filed_under, feed)

    def add(self, outcome: FeedOutcome) -> bool:
        """Listed by `outcome`'s Feed too: each Feed counts the other; False if it had listed it.

        If its Source is filed under that Feed, the Feeds before it counted it so (`file`): now
        it is listed in this run, and counted so once.
        """
        if any(lister.feed == outcome.feed for lister in self.feeds):
            return False
        first, overlap = self.feeds[0], outcome.overlap
        if len(self.feeds) == 1 and self.filed in (None, first.feed):  # its own until now
            first.overlap.own -= 1
            first.overlap.shared += 1
        listers = {lister.feed for lister in self.feeds}
        if self.filed is not None and self.filed != outcome.feed and self.filed not in listers:
            _count(overlap.filed_under, self.filed)
        for lister in self.feeds:
            _count(lister.overlap.listed_with, outcome.feed)
            _count(overlap.listed_with, lister.feed)
            if self.filed == outcome.feed:
                _count(lister.overlap.filed_under, outcome.feed, -1)
        overlap.shared += 1
        self.feeds.append(outcome)
        return True


@dataclass(slots=True)
class Attempt:
    """One attempt of a scrape run: where it writes, what it fetches with, what it did."""

    db: Database
    sink: Sink
    fetchers: dict[FetcherName, Fetcher]
    run_id: uuid.UUID | None  # None: not run by the scheduler (a notebook)
    folder: str  # the run folder in the sink
    result: ScrapeResult = field(default_factory=ScrapeResult)
    listed: dict[str, Listing] = field(default_factory=dict[str, Listing])  # by normalised URL
    slugs: dict[uuid.UUID, str] = field(default_factory=dict[uuid.UUID, str])  # every Feed's
    budget: Budget = field(default_factory=Budget.unlimited)  # time for requests, by Feed
    walled: set[str] = field(default_factory=set[str])  # sites behind a bot wall, by `site`
    notifier: Notifier | None = None  # told when a Feed becomes blocked
    clock: Clock = REAL_TIME  # the network's: how long each Feed took
    reporter: Reporter = field(default_factory=lambda: Reporter(UNREPORTED, 0))


class AllFeedsFailedError(Exception):
    """Every Feed the run read failed: the run fails, is retried and alerted as usual."""


class WalledSiteError(FetchError):
    """The document's site put up a bot wall earlier in the run: it is not asked again (§6)."""

    reason = "site behind a bot wall"


async def scrape_job(  # noqa: PLR0913  # what the job is bound to in the catalog
    context: JobContext,
    *,
    db: Database,
    sink: Sink,
    network: Network | None = None,
    notifier: Notifier | None = None,
    budget: float | None = None,
    robots: RobotsCache | None = None,
) -> JSONValue:
    """The scheduled job; `network` is the real web unless a test passes a fake one.

    `notifier` hears about blocked Feeds; `budget`: the seconds the run may spend on requests
    (`infrasales.fetch.pacing.run_budget`), None for no limit; `robots`: robots.txt kept across
    runs, None to read it for this run only.
    """
    result = await scrape(
        db,
        sink,
        run_id=context.run_id,
        scheduled_for=context.scheduled_for,
        trace=context.trace,
        progress=context.progress,
        network=network,
        notifier=notifier,
        budget=budget,
        robots=robots,
    )
    return result.to_json()


async def scrape(  # noqa: PLR0913  # the run's identity, and where it reads and writes
    db: Database,
    sink: Sink,
    *,
    run_id: uuid.UUID | None,
    scheduled_for: datetime,
    trace: Trace = UNTRACED,
    progress: Progress = UNREPORTED,
    network: Network | None = None,
    notifier: Notifier | None = None,
    budget: float | None = None,
    robots: RobotsCache | None = None,
) -> ScrapeResult:
    """Read every enabled Feed once; each Feed is a traced step of the run.

    `progress` hears how far the run got, Feed by Feed and within each (`Reporter`).

    Raises `AllFeedsFailedError` when every Feed read failed (none enabled is no failure).
    """
    # The scheduler runs one attempt of this job at a time, so at the start of an attempt every
    # `writing` version is a crash's leftover (ADR 03 §3). If another job ever writes versions,
    # this must change.
    if swept := await versions.sweep(db, sink):
        _log.warning("versions.swept", versions=swept)
    feeds = await enabled_feeds(db)
    slugs = await feed_slugs(db)
    network = network or Network()
    shares = Budget(budget, network.clock, len(feeds))
    async with open_fetchers(network, shares, robots) as fetchers:
        folder = run_folder(scheduled_for)
        attempt = Attempt(
            db,
            sink,
            dict(fetchers),
            run_id,
            folder,
            budget=shares,
            notifier=notifier,
            clock=network.clock,
            slugs=slugs,
            reporter=Reporter(progress, len(feeds), network.clock),
        )
        for feed in feeds:
            with trace.step(
                f"feed {feed.slug}", {"kind": feed.kind.value, "url": feed.url}
            ) as step:
                step.finish((await read_feed(attempt, feed)).to_json())
    result = attempt.result
    if result.feeds_read and len(result.failed_feeds) == result.feeds_read:
        msg = f"all {result.feeds_read} Feeds failed: {result.to_json()['failed_feeds']}"
        raise AllFeedsFailedError(msg)
    return result


async def enabled_feeds(db: Database) -> list[Feed]:
    """The enabled Feeds, oldest first: a URL two Feeds list is filed under the older one."""
    async with db.session() as session:
        enabled = select(Feed).where(col(Feed.enabled).is_(True)).order_by(col(Feed.id))
        return list((await session.exec(enabled)).all())


async def feed_slugs(db: Database) -> dict[uuid.UUID, str]:
    """Every Feed's slug by ID, disabled ones too: a Source may be filed under any."""
    async with db.session() as session:
        return dict((await session.exec(select(Feed.id, Feed.slug))).all())


async def read_feed(attempt: Attempt, feed: Feed) -> FeedOutcome:
    """List the Feed's items and collect each; a failure is the Feed's, never the run's.

    Within the Feed's share of the run's time: once it is used up, the Feed stops without
    failing, and its unread documents wait for the next run (the run's result says how many).
    The outcome is kept in the run's result too, and reported as it grows (`Reporter`).
    """
    result, reporter = attempt.result, attempt.reporter
    result.feeds_read += 1
    attempt.budget.next_feed()
    started, told = attempt.clock.monotonic(), reporter.spent
    outcome = FeedOutcome(feed.slug)
    result.feeds.append(outcome)
    await reporter.started(result, outcome)
    counts = dict.fromkeys(Collected, 0)
    items: list[Item] | None = None
    failure: Exception | None = None
    try:
        items = await list_items(attempt, feed)
        outcome.items = outcome.unread = len(items)
        await reporter.listed(result)
        for item in items:
            counts[await collect_item(attempt, feed, outcome, item)] += 1
            outcome.unread -= 1
            _counted(outcome, counts)
            if outcome.unread:  # the last one: the Feed's end is told next
                await reporter.item(result)
    except OutOfTimeError:
        outcome.out_of_time = True
        if items is None:
            outcome.unread = None
        _log.warning("feed.out_of_time", feed=feed.slug, unread=outcome.unread)
        attempt.result.out_of_time.append(OutOfTime(feed.slug, outcome.unread))
    except Exception as error:  # noqa: BLE001  # one Feed must not stop the others
        raise_if_cancelled()
        failure = error
        if items is None:
            outcome.unread = None
    else:
        _log.info("feed.read", feed=feed.slug, items=len(items), **counts)
    # Its requests and pauses: neither the reports nor telling an admin it is blocked.
    outcome.seconds = attempt.clock.monotonic() - started - (reporter.spent - told)
    if failure is not None:
        outcome.reason = await feed_failed(attempt, feed, failure)
    elif items is not None:  # not even listed: nothing to note
        await note_read(attempt.db, feed.id, FeedState.OK)
    await reporter.finished(result)
    return outcome


def _counted(outcome: FeedOutcome, counts: dict[Collected, int]) -> None:
    outcome.new = counts[Collected.NEW]
    outcome.unchanged = counts[Collected.UNCHANGED]
    outcome.known = counts[Collected.KNOWN]
    outcome.seen = counts[Collected.SEEN]
    outcome.failed = counts[Collected.FAILED]


async def feed_failed(attempt: Attempt, feed: Feed, error: Exception) -> str:
    """Record why the Feed failed; tell an admin when it has just become blocked; the reason.

    `blocked` is news once, not on every run: it is recorded only once the notice was handed
    over. Until then the Feed is `failing` ("blocked"), and the next run tells again.
    """
    reason = failure_reason(error)
    _log.warning("feed.failed", feed=feed.slug, reason=reason, error=type(error).__name__)
    attempt.result.failed_feeds.append(FailedFeed(feed.slug, reason))
    state = FeedState.FAILING
    if isinstance(error, BlockedError):
        notice = FeedBlocked(feed.slug, feed.name, feed.url, attempt.run_id)
        if feed.state == FeedState.BLOCKED or await tell(attempt, notice):
            state = FeedState.BLOCKED
    await note_read(attempt.db, feed.id, state, reason)
    return reason


async def tell(attempt: Attempt, notice: Notice) -> bool:
    """Tell the notifier, if any: bounded, never the Feed's or run's failure; whether told.

    Without a notifier (no alert channel configured) there is nobody to tell: that counts.
    """
    if attempt.notifier is None:
        return True
    try:
        async with asyncio.timeout(_ALERT_SECONDS):
            await attempt.notifier.notify(notice)
    except Exception:  # noqa: BLE001  # the Feed's state is recorded and logged
        raise_if_cancelled()
        _log.exception("feed.alert_failed", key=notice.key)
        return False
    return True


def failure_reason(error: Exception) -> str:
    """A Feed's `last_error`: an expected failure's `reason`, else the error's type."""
    reason = error.reason if isinstance(error, ExpectedError) else type(error).__name__
    return reason[:_REASON_LENGTH]


async def list_items(attempt: Attempt, feed: Feed) -> list[Item]:
    """What the Feed lists now, by the Lister of its kind.

    A listing request refused (`401`, `403`, `451`) blocks the Feed: none of it can be read.
    A document refused is that document's failure only (`collect`).
    """
    try:
        return await lister_for(feed.kind).list(feed, attempt.fetchers[feed.fetcher])
    except RefusedError as error:
        raise BlockedError(error.response.final_url, error.response.status) from error


async def collect_item(attempt: Attempt, feed: Feed, outcome: FeedOutcome, item: Item) -> Collected:
    """`collect`, any failure of it the item's alone: it is skipped, its Feed goes on.

    Only what stops the whole Feed passes: a bot wall on its own site (`BlockedError`), its time
    up (`OutOfTimeError`). Another site's wall fails the document and keeps the run off that
    site (`walled`). Like Scrapy's callback errors: logged, counted, the next item read.
    """
    try:
        return await collect(attempt, feed, outcome, item)
    except BlockedError:
        if same_site(site(item.url), site(feed.url)):
            raise
        walled(attempt, outcome, item.url)
        return _skipped(attempt, item, BlockedError.reason)
    except OutOfTimeError:
        raise
    except Exception:  # noqa: BLE001  # one document must not stop its Feed
        raise_if_cancelled()
        _log.exception("document.failed", url=item.url)
        attempt.result.documents_failed += 1
        return Collected.FAILED


async def collect(attempt: Attempt, feed: Feed, outcome: FeedOutcome, item: Item) -> Collected:
    """Store the item's document as a new Source Version; a known URL's is checked again.

    Which Feeds list the URL is counted first, whatever becomes of the item (`outcome.overlap`).
    """
    try:
        url = normalize_url(item.url)
    except MalformedUrlError as error:
        return _skipped(attempt, item, error.reason)
    if (listing := attempt.listed.get(url)) is not None:
        listing.add(outcome)
        return Collected.SEEN
    attempt.listed[url] = listing = Listing.first(outcome)
    if len(url) > MAX_URL_LENGTH:
        return _skipped(attempt, item, "URL too long")
    source = await versions.find_source(attempt.db, url)
    if source is not None:
        listing.file(attempt.slugs.get(source.first_feed_id))
    if source is not None and source.latest_version_id is not None:
        return await check_known(attempt, feed, item, source)
    try:
        reading = await extract(feed, await get(attempt, feed, item))
    except (FetchError, ExtractionError) as error:
        return _skipped(attempt, item, error.reason)
    await store(attempt, feed, url, reading)
    return Collected.NEW


def walled(attempt: Attempt, outcome: FeedOutcome, url: str) -> None:
    """`url`'s site, not the Feed's, put up a bot wall: the run asks it for nothing more.

    The wall is the site asked (`url`), wherever it answered: a redirect to DataDome is the
    site's own. Not the Feed's failure, and no alert: the Feed's outcome names the site.
    """
    walled_site = site(url)
    _log.warning("site.walled", site=walled_site, feed=outcome.feed)
    attempt.walled.add(walled_site)
    if walled_site not in outcome.walled:
        outcome.walled.append(walled_site)


def _skipped(attempt: Attempt, item: Item, reason: str) -> Literal[Collected.FAILED]:
    _log.warning("document.skipped", url=item.url, reason=reason)
    attempt.result.documents_failed += 1
    return Collected.FAILED


async def check_known(attempt: Attempt, feed: Feed, item: Item, source: Source) -> Collected:
    """A URL with a committed version, checked again (ADR 03 §3).

    A conditional request first: `304 Not Modified` only marks the Source checked. Otherwise
    the text is extracted and its hash compared with the latest version's: text, not HTML, so
    a changed ad or timestamp is no change. Only a URL that is `due` is checked.
    """
    pointer = source.latest_version_id
    latest = None if pointer is None else await versions.find_committed(attempt.db, pointer)
    if latest is not None and not versions.due(source, latest, utcnow()):
        return Collected.KNOWN
    try:
        document = await get(attempt, feed, item, source.validators)
        if document.not_modified:
            await versions.mark_checked(attempt.db, source.id, document.fetched_at)
            return _unchanged(attempt)
        reading = await extract(feed, document)
        latest_text = await latest_text_sha256(attempt, item, latest, reading.extractor)
    except (FetchError, ExtractionError) as error:
        return _skipped(attempt, item, error.reason)
    if reading.text_sha256 == latest_text:
        await versions.mark_checked(attempt.db, source.id, document.fetched_at, document.validators)
        return _unchanged(attempt)
    await store(attempt, feed, source.url, reading)
    return Collected.NEW


def _unchanged(attempt: Attempt) -> Literal[Collected.UNCHANGED]:
    attempt.result.versions_unchanged += 1
    return Collected.UNCHANGED


async def latest_text_sha256(
    attempt: Attempt, item: Item, latest: SourceVersion | None, extractor: Extractor
) -> str | None:
    """The hash of the latest version's text as `extractor` reads it today; None: none.

    Read by another extractor or version, the latest version's raw file is extracted again,
    so like is compared with like: an extractor upgrade alone is no change. No comparison is
    possible with a latest version being deleted (a crash left it so, or retention deleted its
    files meanwhile) or one the extractor cannot read: whatever was got is new. The text read
    again passes the same quality gate as the new one (`extract`), with what the Feed says now.
    """
    if latest is None:
        return None
    if (latest.extractor, latest.extractor_version) == (extractor.name, extractor.version):
        return latest.text_sha256
    try:
        raw = await attempt.sink.read(f"{latest.storage_key}/{raw_name(latest.media_type)}")
    except FileNotFoundError:
        return None
    try:
        again = await asyncio.to_thread(guarded_extract, extractor, raw, normalize_url(item.url))
    except ExtractionError:
        return None
    return sha256(quality.gate(item, again).text.encode())


async def get(
    attempt: Attempt, feed: Feed, item: Item, validators: Validators | None = None
) -> Document:
    """The item's document: carried by the Feed (API items), else fetched by its fetcher.

    Fetched conditionally with `validators` (a known Source's): it may be `not_modified`. Not
    fetched from another site that put up a bot wall in this run (`WalledSiteError`); the
    Feed's own site is asked: its wall blocks the Feed.
    """
    if item.content is not None:
        media_type = item.media_type or _UNKNOWN_MEDIA_TYPE
        return Document(item, item.content, media_type, None, utcnow())
    asked = site(item.url)
    if not same_site(asked, site(feed.url)) and any(
        same_site(asked, walled_site) for walled_site in attempt.walled
    ):
        raise WalledSiteError(item.url)
    response = await attempt.fetchers[feed.fetcher].fetch(item.url, validators)
    return Document.fetched(item, response)


async def extract(feed: Feed, document: Document) -> Reading:
    """The document read by its extractor, in a thread: it is CPU-bound, the lease must renew.

    The extractor: the Feed's, else the first URL pattern's, else the media type's. An
    incomplete text (paywalled, too short) becomes a `partial` one from what the Feed gave.
    """
    extractor = registry.choose(feed.extractor, document.url, document.media_type)
    extracted = await asyncio.to_thread(guarded_extract, extractor, document.raw, document.url)
    return Reading(document, extractor, quality.gate(document.item, extracted))


async def store(attempt: Attempt, feed: Feed, url: str, reading: Reading) -> int | None:
    """Write a new Source Version: its row as `writing`, its files, then commit; its number."""
    document, extractor = reading.document, reading.extractor
    version_id = uuid.uuid7()
    folder = version_folder(attempt.folder, feed.slug, version_id)
    new = versions.NewVersion(
        id=version_id,
        url=url,
        feed_id=feed.id,
        run_id=attempt.run_id,
        fetched_at=document.fetched_at,
        http_status=document.http_status,
        media_type=document.media_type,
        raw_sha256=sha256(document.raw),
        text_sha256=reading.text_sha256,
        extractor=extractor.name,
        extractor_version=extractor.version,
        storage_key=folder,
        partial=reading.extracted.partial,  # the quality gate's verdict (`extract`)
        title=reading.extracted.title,
        published_at=reading.extracted.published_at,
        validators=document.validators or Validators(),
    )
    source_id = await versions.start(attempt.db, new)
    identity = Identity(source_id, version_id, url, attempt.run_id, attempt.folder)
    await attempt.sink.write(f"{folder}/{raw_name(document.media_type)}", document.raw)
    await attempt.sink.write(f"{folder}/{EXTRACTED}", extracted_json(extractor, reading.extracted))
    metadata = metadata_json(feed, reading, identity)
    await attempt.sink.write(f"{folder}/{METADATA}", metadata)  # last: the folder is complete
    number = await versions.commit(attempt.db, new)
    if number is None:  # swept: this worker froze past its lease, another took the run over
        _log.warning("version.discarded", url=url, version_id=str(version_id))
        await attempt.sink.delete(folder)  # files written after the sweep had deleted the folder
        return None
    attempt.result.versions_new += 1
    return number
