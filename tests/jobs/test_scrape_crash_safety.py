"""Crash safety of the scrape job (BIG-22): crashes, retries and frozen workers.

They leave nothing a later run or the next stage could mistake for real data, and never
change a stored file.

Through the Worker, like the other scrape tests. A crash is the worker process dying at one
point of an attempt (an exception nothing in the job or the Worker handles); the next attempt
is the same run, taken over by another worker once the lease has passed. A frozen worker is
one that stops at a point, while another worker takes its run over, then goes on.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from random import Random

import pytest

from infrasales.catalog import versions
from infrasales.catalog.models import SourceVersion, VersionState
from infrasales.core.db import Database
from infrasales.scheduler import runs
from infrasales.scheduler.models import JobRun, JobStatus
from infrasales.scheduler.worker import Worker
from infrasales.sink.store import Sink
from tests.helpers import app_url
from tests.scheduler.support import FAST
from tests.scrape.support import (
    RSS,
    Entry,
    Scraping,
    article_page,
    broken_pointers,
    rss_feed,
    stored_run,
    stored_sources,
    stored_versions,
)

pytestmark = pytest.mark.anyio

FEED = "https://news.test/feed.xml"
ARTICLE = "https://news.test/2026/10/heat-network-approved"
OTHER = "https://news.test/2026/10/fernwaerme-tarife"
TEXT = "The town council approved the heat network for the old town at its June session."


class Crash(BaseException):
    """The worker process dies here."""


async def crash() -> None:
    raise Crash


def before_call(
    monkeypatch: pytest.MonkeyPatch,
    owner: object,
    name: str,
    happening: Callable[[], Awaitable[None]],
    *,
    call: int = 1,
) -> None:
    """At the `call`-th call of `owner.name`, `happening` happens first (a crash, a freeze)."""
    original: Callable[..., Awaitable[object]] = getattr(owner, name)
    calls = 0

    async def interrupted(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == call:
            await happening()
        return await original(*args, **kwargs)

    monkeypatch.setattr(owner, name, interrupted)


def serve(scraping: Scraping, *articles: str) -> None:
    for url in articles:
        scraping.web.serve(url, article_page(url.rsplit("/", 1)[-1], TEXT))
    scraping.web.serve(FEED, rss_feed(*(Entry(url) for url in articles)), media_type=RSS)


async def requested(scraping: Scraping) -> JobRun:
    """An admin's "Run now", queued."""
    async with scraping.db.session() as session:
        run, _ = await runs.enqueue(session, "scrape", scraping.clock(), triggered_by="basic:alice")
    return run


async def crashed_run(scraping: Scraping) -> JobRun:
    """A "Run now" whose first attempt dies: the run stays `running`, its lease held."""
    run = await requested(scraping)
    with pytest.raises(Crash):
        await Worker(scraping.db, scraping.registry(), FAST, scraping.clock).tick()
    return await stored_run(scraping.db, run.id)


async def taken_over(scraping: Scraping, run: JobRun) -> JobRun:
    """The next attempt: another worker takes the run over once its lease has passed."""
    scraping.clock.advance(hours=1)
    assert await Worker(scraping.db, scraping.registry(), FAST, scraping.clock).tick()
    return await stored_run(scraping.db, run.id)


async def folders(scraping: Scraping) -> set[str]:
    """The version folders in the sink."""
    return {key.rsplit("/", 1)[0] for key in await scraping.files()}


async def test_a_crash_before_the_commit_is_swept_by_the_next_attempt(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(scraping, ARTICLE)
    await scraping.add_feed("news", FEED)
    before_call(monkeypatch, versions, "commit", crash)

    run = await crashed_run(scraping)

    (left,) = await stored_versions(scraping.db)
    assert (left.state, left.version_no) == (VersionState.WRITING, None)
    assert await folders(scraping) == {left.storage_key}  # its files were written

    run = await taken_over(scraping, run)

    assert (run.status, run.attempts) == (JobStatus.SUCCEEDED, 2)
    (version,) = await stored_versions(scraping.db)
    assert version.id != left.id
    assert (version.state, version.version_no) == (VersionState.COMMITTED, 1)
    (source,) = await stored_sources(scraping.db)
    assert source.latest_version_id == version.id
    assert await folders(scraping) == {version.storage_key}  # the leftover's folder is gone
    assert version.storage_key.split("/")[0] == left.storage_key.split("/")[0]  # same run


async def test_a_retry_leaves_the_files_of_committed_versions_as_they_were(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(scraping, ARTICLE, OTHER)
    await scraping.add_feed("news", FEED)
    before_call(monkeypatch, versions, "commit", crash, call=2)  # the first one is committed
    run = await crashed_run(scraping)
    (committed,) = [v for v in await stored_versions(scraping.db) if v.version_no]
    kept = await scraping.files(committed.storage_key)
    scraping.web.serve(ARTICLE, article_page("Rewritten", "Another text altogether."))

    run = await taken_over(scraping, run)

    assert (run.status, run.attempts) == (JobStatus.SUCCEEDED, 2)
    assert await scraping.files(committed.storage_key) == kept
    first, rewritten, retried = await stored_versions(scraping.db)
    assert first.id == committed.id
    assert first.superseded_at is not None  # the rewritten page is its next version (BIG-20)
    assert (rewritten.source_id, rewritten.version_no) == (first.source_id, 2)
    assert (retried.state, retried.version_no) == (VersionState.COMMITTED, 1)
    assert await folders(scraping) == {
        committed.storage_key,
        rewritten.storage_key,
        retried.storage_key,
    }
    assert await broken_pointers(scraping.db) == {}


@pytest.mark.parametrize(
    ("owner", "name"),
    [(versions, "commit"), (Sink, "write")],
    ids=["before its commit", "before its files"],
)
async def test_a_worker_frozen_past_its_lease_discards_its_version_without_failing(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch, owner: object, name: str
) -> None:
    """Worker A freezes mid-version; B takes the run over and completes it; then A goes on."""
    serve(scraping, ARTICLE)
    await scraping.add_feed("news", FEED)
    queued = await requested(scraping)
    by_b: list[JobRun] = []

    async def b_takes_over() -> None:
        by_b.append(await taken_over(scraping, queued))

    before_call(monkeypatch, owner, name, b_takes_over)

    assert await Worker(scraping.db, scraping.registry(), FAST, scraping.clock).tick()  # A

    (run,) = by_b
    assert (run.status, run.attempts) == (JobStatus.SUCCEEDED, 2)
    assert await stored_run(scraping.db, run.id) == run  # A's outcome is not recorded
    (version,) = await stored_versions(scraping.db)
    assert (version.state, version.version_no, version.run_id) == (
        VersionState.COMMITTED,
        1,
        run.id,
    )
    (source,) = await stored_sources(scraping.db)
    assert source.latest_version_id == version.id
    assert await folders(scraping) == {version.storage_key}  # nothing of A's is left


def another_version(first: SourceVersion, url: str) -> versions.NewVersion:
    """A new text of the Source of `first`, as a concurrent writer would store it."""
    return versions.NewVersion(
        id=uuid.uuid7(),
        url=url,
        feed_id=first.feed_id,
        run_id=None,
        fetched_at=first.fetched_at,
        http_status=200,
        media_type="text/html",
        raw_sha256="0" * 64,
        text_sha256="1" * 64,
        extractor=first.extractor,
        extractor_version=first.extractor_version,
        storage_key=f"elsewhere/news/{uuid.uuid4()}",
    )


async def test_concurrent_commits_for_one_source_are_numbered_one_after_another(
    scraping: Scraping, database_url: str
) -> None:
    """Writers racing to commit versions of one Source (two workers, a frozen one woken up).

    On PostgreSQL each commit is a transaction of its own, on a connection of its own, as the
    app's role; SQLite runs one writer at a time anyway.
    """
    serve(scraping, ARTICLE)
    await scraping.add_feed("news", FEED)
    await scraping.run_now()
    (first,) = await stored_versions(scraping.db)
    racing = [another_version(first, ARTICLE) for _ in range(8)]
    for new in racing:
        await versions.start(scraping.db, new)
    app = Database(app_url(database_url))
    try:
        numbers = await asyncio.gather(*(versions.commit(app, new) for new in racing))
    finally:
        await app.dispose()

    assert sorted(n for n in numbers if n is not None) == list(range(2, 10))
    assert await broken_pointers(scraping.db) == {}
    (source,) = await stored_sources(scraping.db)
    assert source.latest_version_id == racing[numbers.index(9)].id


@pytest.mark.parametrize("seed", range(4))
async def test_after_commits_crashes_and_retries_every_pointer_names_the_highest_version(
    scraping: Scraping, seed: int
) -> None:
    """The invariant, after each round of a seeded mix of what can happen to the writers.

    Each round the Feed lists two more articles, and then one of: a clean run; a run whose
    first attempt dies before a commit or a file; a run whose worker freezes there while
    another completes the run; other writers racing to commit new versions of known Sources,
    one of which never commits before the next run sweeps it.
    """
    random = Random(seed)  # noqa: S311  # a reproducible mix, not a secret
    await scraping.add_feed("news", FEED)
    listed: list[str] = []
    late: list[versions.NewVersion] = []  # started by a writer that froze before its commit
    for round_ in range(6):
        listed += [f"{ARTICLE}-{round_}-{n}" for n in (1, 2)]
        serve(scraping, *listed)
        happening = "clean" if round_ == 0 else random.choice(["clean", "crash", "freeze", "race"])
        owner, name = random.choice([(versions, "commit"), (Sink, "write")])
        call = random.choice([1, 2])
        with pytest.MonkeyPatch.context() as patch:
            if happening == "crash":
                before_call(patch, owner, name, crash, call=call)
                await taken_over(scraping, await crashed_run(scraping))
            elif happening == "freeze":
                queued = await requested(scraping)

                async def b_takes_over(run: JobRun = queued) -> None:
                    await taken_over(scraping, run)

                before_call(patch, owner, name, b_takes_over, call=call)
                assert await Worker(scraping.db, scraping.registry(), FAST, scraping.clock).tick()
            else:
                await scraping.run_now()
        assert [await versions.commit(scraping.db, new) for new in late] == [None] * len(late)
        late = []
        if happening == "race":
            late = await race(scraping, random)
        assert await broken_pointers(scraping.db) == {}, (round_, happening)

    sources = await stored_sources(scraping.db)
    assert sorted(s.url for s in sources) == sorted(listed)
    assert all(s.latest_version_id for s in sources)
    keys = {v.storage_key for v in await stored_versions(scraping.db)}
    assert await folders(scraping) <= keys  # no folder without its row


async def race(scraping: Scraping, random: Random) -> list[versions.NewVersion]:
    """Writers commit new versions of known Sources at once; one more never commits (yet)."""
    stored = [v for v in await stored_versions(scraping.db) if v.version_no == 1]
    by_url = {s.id: s.url for s in await stored_sources(scraping.db)}
    chosen = random.choices(stored, k=4)
    racing = [another_version(v, by_url[v.source_id]) for v in chosen]
    for new in racing:
        await versions.start(scraping.db, new)
        await scraping.sink.write(f"{new.storage_key}/raw.html", b"<p>another text</p>")
    numbers = await asyncio.gather(*(versions.commit(scraping.db, n) for n in racing[:-1]))
    assert None not in numbers
    return racing[-1:]


async def test_a_crash_while_sweeping_is_completed_by_the_attempt_after(
    scraping: Scraping, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(scraping, ARTICLE)
    await scraping.add_feed("news", FEED)
    with pytest.MonkeyPatch.context() as patch:
        before_call(patch, versions, "commit", crash)
        run = await crashed_run(scraping)
    (left,) = await stored_versions(scraping.db)
    before_call(monkeypatch, Sink, "delete", crash)  # the sweep dies before the folder goes
    scraping.clock.advance(hours=1)
    with pytest.raises(Crash):
        await Worker(scraping.db, scraping.registry(), FAST, scraping.clock).tick()
    assert [v.state for v in await stored_versions(scraping.db)] == [VersionState.DELETED]

    run = await taken_over(scraping, run)

    assert (run.status, run.attempts) == (JobStatus.SUCCEEDED, 3)
    (version,) = await stored_versions(scraping.db)
    assert (version.state, version.version_no) == (VersionState.COMMITTED, 1)
    assert await folders(scraping) == {version.storage_key}  # not `left`'s any more
    assert version.id != left.id
