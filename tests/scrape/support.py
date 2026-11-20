"""Shared scrape test helpers: a fake web, a fresh sink, the scrape job run through the Worker.

The seam (BIG-17): run the scrape job through the scheduler's Worker, against a fake web served
in-process (with fake DNS, so the public-address guard stays on) and a `memory://` sink, then
look at the catalog rows and the sink's files.

    async def test_x(scraping: Scraping) -> None:      # the fixture is in tests/conftest.py
        scraping.web.serve(ARTICLE, article_page("Title", "Text …"))
        scraping.web.serve(FEED, rss_feed(Entry(ARTICLE, "Title")))
        await scraping.add_feed("news", FEED)
        run = await scraping.run_now()
        (version,) = await stored_versions(scraping.db)

Every test database holds the seeded Feeds (the news Feeds, the APIs): `Scraping` disables them
all first, so a test reads only the Feeds it adds. Later tickets: add routes and helpers in
your own test modules, or new functions at the end of this one.
"""

import uuid
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import format_datetime
from functools import partial
from html import escape
from io import BytesIO
from unittest.mock import ANY

import httpx2
from pypdf import PdfWriter
from pypdf.constants import UserAccessPermissions
from pypdf.generic import ContentStream, DictionaryObject, NameObject
from sqlmodel import col, select, update

from infrasales.catalog.models import Source, SourceVersion, VersionState
from infrasales.config.schemas import ConfigKey
from infrasales.core.db import Database
from infrasales.core.models import JSONValue
from infrasales.feeds.models import Feed, FeedKind
from infrasales.fetch.http import Network
from infrasales.fetch.robots import RobotsCache
from infrasales.jobs.scrape import scrape_job
from infrasales.scheduler import runs
from infrasales.scheduler.models import JobRun
from infrasales.scheduler.registry import Registry, ScheduledJob
from infrasales.scheduler.worker import Worker
from infrasales.sink.store import Sink
from tests.alerts.support import RecordingNotifier
from tests.helpers import app_url
from tests.scheduler.support import FAST, Clock

PUBLIC_IP = "93.184.215.14"  # what every host resolves to, unless `FakeWeb.dns` says otherwise
PRIVATE_HOSTS: dict[str, list[str]] = {
    "internal.test": ["10.0.0.1"],
    "localhost": ["127.0.0.1"],
    "metadata.test": ["169.254.169.254"],  # a cloud's instance metadata
}
HTML = "text/html; charset=utf-8"
RSS = "application/rss+xml; charset=utf-8"

type Handler = Callable[[httpx2.Request], httpx2.Response]


@dataclass
class FakeTime:
    """Monotonic time that passes only when the fetcher pauses: pauses cost tests nothing."""

    now: float = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakeWeb:
    """The web, served in-process by URL; unknown URLs answer 404. Records every request.

    Its time is fake: `times(host)` tells when each request to a host was sent.
    """

    routes: dict[str, Handler] = field(default_factory=dict[str, Handler])
    dns: dict[str, list[str]] = field(default_factory=lambda: dict(PRIVATE_HOSTS))
    requests: list[httpx2.Request] = field(default_factory=list[httpx2.Request])
    time: FakeTime = field(default_factory=FakeTime)
    sent_at: list[float] = field(default_factory=list[float])  # by request, in `requests` order

    def route(self, url: str, handler: Handler) -> None:
        """Answer requests for `url` with `handler` (e.g. changing answers, conditional ones)."""
        self.routes[url] = handler

    def serve(  # noqa: PLR0913  # what a response is made of
        self,
        url: str,
        body: bytes | str,
        *,
        media_type: str = HTML,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
        chunked: bool = False,  # no Content-Length: the body is streamed
    ) -> None:
        content = body.encode() if isinstance(body, str) else body
        sent = {"content-type": media_type} | dict(headers or {})

        def answer(_: httpx2.Request) -> httpx2.Response:
            if chunked:
                return httpx2.Response(status, headers=sent, content=_stream(content))
            return httpx2.Response(status, headers=sent, content=content)

        self.route(url, answer)

    def redirect(self, url: str, to: str, status: int = 302) -> None:
        self.route(url, lambda _: httpx2.Response(status, headers={"location": to}))

    def fetched(self, url: str) -> int:
        """How often `url` was requested."""
        return sum(1 for request in self.requests if str(request.url) == url)

    def times(self, host: str) -> list[float]:
        """When each request to `host` was sent, in fake seconds since the test began."""
        return [t for r, t in zip(self.requests, self.sent_at, strict=True) if r.url.host == host]

    def hosts(self) -> set[str]:
        """Every host a request reached."""
        return {request.url.host for request in self.requests}

    async def resolve(self, host: str) -> list[str]:
        return self.dns.get(host, [PUBLIC_IP])

    def network(self) -> Network:
        """What the scrape job fetches through: this web, its DNS and time; the real rules."""
        transport = httpx2.MockTransport(self._handle)
        return Network(transport=transport, resolve=self.resolve, clock=self.time)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        self.sent_at.append(self.time.now)
        handler = self.routes.get(str(request.url))
        return handler(request) if handler else httpx2.Response(404, text="not found")


async def _stream(content: bytes) -> AsyncGenerator[bytes]:
    for start in range(0, len(content), 1 << 16):
        yield content[start : start + (1 << 16)]


@dataclass(frozen=True)
class Entry:
    """An RSS item."""

    url: str
    title: str | None = None
    summary: str | None = None
    author: str | None = None
    published: datetime | None = None


def rss_feed(*entries: Entry, title: str = "News") -> str:
    """An RSS 2.0 document listing `entries`."""
    items = "".join(_rss_item(entry) for entry in entries)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<rss version="2.0"><channel><title>{escape(title)}</title>{items}</channel></rss>'
    )


def _rss_item(entry: Entry) -> str:
    parts = [f"<link>{escape(entry.url)}</link>"]
    if entry.title:
        parts.append(f"<title>{escape(entry.title)}</title>")
    if entry.summary:
        parts.append(f"<description>{escape(entry.summary)}</description>")
    if entry.author:
        parts.append(f"<author>{escape(entry.author)}</author>")
    if entry.published:
        parts.append(f"<pubDate>{format_datetime(entry.published)}</pubDate>")
    return f"<item>{''.join(parts)}</item>"


def article_page(title: str, *paragraphs: str) -> str:
    """A news article's HTML page, as the generic extractor reads it."""
    body = "".join(f"<p>{escape(p)}</p>" for p in paragraphs)
    return (
        f"<!doctype html><html><head><title>{escape(title)}</title></head><body>"
        "<nav><a href='/'>Home</a> <a href='/news'>News</a></nav>"
        f"<article><h1>{escape(title)}</h1>{body}</article>"
        "<footer>Copyright News Inc.</footer></body></html>"
    )


def memory_sink_uri() -> str:
    """A `SINK__URI` of its own: fsspec's memory store is shared by the whole process."""
    return f"memory://t-{uuid.uuid4().hex}"


def memory_sink() -> Sink:
    """A sink of its own, in memory."""
    return Sink(memory_sink_uri())


async def empty(sink: Sink) -> None:
    """Delete everything in `sink`."""
    for folder in {key.split("/", 1)[0] for key in await sink.list()}:
        await sink.delete(folder)


async def sink_files(sink: Sink, folder: str = "") -> dict[str, bytes]:
    """Every file below `folder`, by key."""
    return {key: await sink.read(key) for key in await sink.list(folder)}


async def disable_all_feeds(db: Database) -> None:
    """Disable every Feed, the seeded ones included: a test then adds the Feeds it reads."""
    async with db.session() as session:
        await session.exec(update(Feed).values(enabled=False))


async def add_feed(  # noqa: PLR0913  # a Feed's columns
    db: Database,
    slug: str,
    url: str,
    *,
    kind: FeedKind = FeedKind.RSS,
    name: str | None = None,
    extractor: str | None = None,
    settings: dict[str, JSONValue] | None = None,
) -> Feed:
    """An enabled Feed, added after every other: it is read last."""
    feed = Feed(
        name=name or slug.title(),
        slug=slug,
        kind=kind,
        url=url,
        extractor=extractor,
        settings=settings or {},
    )
    async with db.session() as session:
        session.add(feed)
    return feed


async def stored_feeds(db: Database) -> list[Feed]:
    async with db.session() as session:
        return list((await session.exec(select(Feed).order_by(col(Feed.id)))).all())


async def stored_sources(db: Database) -> list[Source]:
    async with db.session() as session:
        return list((await session.exec(select(Source).order_by(col(Source.id)))).all())


async def stored_versions(db: Database) -> list[SourceVersion]:
    async with db.session() as session:
        query = select(SourceVersion).order_by(col(SourceVersion.id))
        return list((await session.exec(query)).all())


def feed_outcome(feed: str, **fields: JSONValue) -> dict[str, JSONValue]:
    """A Feed's entry in a run's `feeds` (`FeedOutcome`): nothing listed, unless `fields` say.

    Any `seconds` match, unless given: fake time passes only in the fetcher's pauses. Any
    `overlap` too: tests/jobs/test_scrape_overlap.py counts it.
    """
    nothing: dict[str, JSONValue] = dict.fromkeys(
        ["items", "new", "unchanged", "known", "seen", "failed", "unread"], 0
    )
    rest: dict[str, JSONValue] = {
        "reason": None,
        "out_of_time": False,
        "seconds": ANY,
        "overlap": ANY,
        "walled": [],
    }
    return {"feed": feed} | nothing | rest | fields


def overlap(
    own: int = 0,
    shared: int = 0,
    *,
    listed_with: dict[str, int] | None = None,
    filed_under: dict[str, int] | None = None,
) -> dict[str, JSONValue]:
    """A Feed's `overlap` in a run's `feeds` (`FeedOverlap`): none, unless the counts say."""
    return {
        "own": own,
        "shared": shared,
        "listed_with": dict(listed_with or {}),
        "filed_under": dict(filed_under or {}),
    }


def counts(run: JobRun) -> dict[str, JSONValue]:
    """A finished scrape run's result: `feeds_read`, `versions_new`, … (`ScrapeResult`)."""
    assert isinstance(run.result, dict), run.result
    return run.result


async def stored_run(db: Database, run_id: uuid.UUID) -> JobRun:
    async with db.session() as session:
        return await session.get_one(JobRun, run_id)


@dataclass
class Scraping:
    """A test's scraping world: its database, a fresh sink, a fake web and a clock.

    `db` is the schema owner's, for a test's own reads and writes; `app` is the same database
    as the app's role on PostgreSQL, for the code under test: it may do only what production
    grants it (`infrasales.core.grants`). `alerts` hears what admins would (failing runs, blocked
    Feeds); `budget`: the run's seconds for requests (fake seconds, `FakeWeb.time`), None for
    no limit; `robots` keeps robots.txt across runs, as the worker does, for a day of
    `FakeWeb.time`.
    """

    db: Database
    app: Database
    sink: Sink = field(default_factory=memory_sink)
    web: FakeWeb = field(default_factory=FakeWeb)
    clock: Clock = field(default_factory=Clock)
    alerts: RecordingNotifier = field(default_factory=RecordingNotifier)
    budget: float | None = None
    robots: RobotsCache = field(init=False)

    def __post_init__(self) -> None:
        self.robots = RobotsCache(self.web.time)

    def registry(self, schedule: ConfigKey | None = None) -> Registry:
        """The scrape job, bound to this world; on its schedule only if `schedule` is given."""
        job = partial(
            scrape_job,
            db=self.db,
            sink=self.sink,
            network=self.web.network(),
            notifier=self.alerts,
            budget=self.budget,
            robots=self.robots,
        )
        return {"scrape": ScheduledJob(run=job, schedule=schedule, notifier=self.alerts)}

    async def add_feed(
        self, slug: str, url: str, *, kind: FeedKind = FeedKind.RSS, extractor: str | None = None
    ) -> Feed:
        return await add_feed(self.db, slug, url, kind=kind, extractor=extractor)

    async def run_now(self) -> JobRun:
        """An admin's "Run now" at the clock's time, run by a Worker at once; the finished run.

        The clock moves on by a minute: each run is requested at a time of its own.
        """
        async with self.db.session() as session:
            run, _ = await runs.enqueue(session, "scrape", self.clock(), triggered_by="basic:alice")
        assert await Worker(self.db, self.registry(), FAST, self.clock).tick()
        self.clock.advance(minutes=1)
        return await stored_run(self.db, run.id)

    async def run_scheduled(self) -> JobRun:
        """The scrape's scheduled run that is due now, run by a Worker; the finished run."""
        assert await Worker(
            self.db, self.registry(ConfigKey.SCRAPE_SCHEDULE), FAST, self.clock
        ).tick()
        async with self.db.session() as session:
            latest = select(JobRun).order_by(col(JobRun.id).desc()).limit(1)
            return (await session.exec(latest)).one()

    async def files(self, folder: str = "") -> dict[str, bytes]:
        return await sink_files(self.sink, folder)


@asynccontextmanager
async def scraping_world(database_url: str) -> AsyncGenerator[Scraping]:
    """A `Scraping` on the migrated database at `database_url`, every seeded Feed disabled."""
    db = Database(database_url)
    as_app = app_url(database_url)
    app = db if as_app == database_url else Database(as_app)
    world = Scraping(db, app)
    try:
        await disable_all_feeds(db)
        yield world
    finally:
        await empty(world.sink)
        await db.dispose()
        if app is not db:
            await app.dispose()


PDF = "application/pdf"
ALL_PERMISSIONS = UserAccessPermissions.all()


def pdf_document(
    *pages: str,
    title: str | None = None,
    user_password: str | None = None,  # set: the PDF is encrypted
    permissions: UserAccessPermissions = ALL_PERMISSIONS,
) -> bytes:
    """A PDF with one page per entry of `pages`, each a line of Helvetica text."""
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        literal = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content = ContentStream(None, writer)
        content.set_data(f"BT /F1 12 Tf 72 720 Td ({literal}) Tj ET".encode("latin-1"))
        page.replace_contents(content)
    if title is not None:
        writer.add_metadata({"/Title": title})
    if user_password is not None:
        writer.encrypt(user_password, "owner", permissions_flag=permissions, algorithm="AES-128")
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


async def broken_pointers(db: Database) -> dict[uuid.UUID, str]:
    """The Sources breaking the catalog's invariant (ADR 03 §3), with what is wrong; {} if none.

    Every Source's latest pointer names its highest committed version (none: NULL), and that
    version is the only committed one not superseded. Readers find the latest by the pointer.
    """
    committed: dict[uuid.UUID, list[SourceVersion]] = {}
    for version in await stored_versions(db):
        if version.state == VersionState.COMMITTED:
            committed.setdefault(version.source_id, []).append(version)
    broken: dict[uuid.UUID, str] = {}
    for source in await stored_sources(db):
        numbered = sorted(committed.get(source.id, []), key=lambda v: v.version_no or 0)
        highest = numbered[-1].id if numbered else None
        current = [v.id for v in numbered if v.superseded_at is None]
        if source.latest_version_id != highest:
            broken[source.id] = f"points at {source.latest_version_id}, highest is {highest}"
        elif current != ([highest] if highest else []):
            broken[source.id] = f"not superseded: {current}, highest is {highest}"
    return broken
