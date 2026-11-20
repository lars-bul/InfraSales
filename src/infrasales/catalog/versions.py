"""Operations on the catalog: look a Source up; start, commit, list, retain, delete a version.

Writing a version (ADR 03 §3): `start` inserts it as `writing` (and its Source, if new), the
caller writes its files to the sink (`metadata.json` last), then `commit` numbers it in one
transaction. A version deleted while it was being written (the crash sweep) is not committed.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import exists, func, or_
from sqlmodel import col, delete, select, update

from infrasales.catalog.models import MAX_TITLE_LENGTH, Source, SourceVersion, VersionState
from infrasales.catalog.urls import url_hash
from infrasales.core.db import Database, insert_if_absent
from infrasales.core.models import utcnow
from infrasales.fetch.fetcher import Validators
from infrasales.sink.store import Sink

# When a known Source is due for a check (`due`): like a cache's heuristic freshness (RFC 9111
# §4.2.2), a tenth of the time its text has stayed the same, at most a week; a run up to an
# hour early still checks it, so a page is not left for a whole schedule period longer.
RECHECK_FRACTION = 0.1
RECHECK_AT_LEAST_EVERY = timedelta(days=7)
RECHECK_SLACK = timedelta(hours=1)


async def find_source(db: Database, url: str) -> Source | None:
    """The Source at the normalised `url`, if the catalog has one."""
    async with db.session() as session:
        found = select(Source).where(col(Source.url_hash) == url_hash(url))
        return (await session.exec(found)).first()


async def find_committed(db: Database, version_id: uuid.UUID) -> SourceVersion | None:
    """The committed Source Version with this ID; None if it is gone or being deleted."""
    async with db.session() as session:
        found = select(SourceVersion).where(
            col(SourceVersion.id) == version_id, col(SourceVersion.state) == VersionState.COMMITTED
        )
        return (await session.exec(found)).first()


async def committed_after(
    db: Database, after: uuid.UUID | None = None, *, limit: int = 100
) -> list[SourceVersion]:
    """The committed Source Versions after the one with ID `after`, oldest first, at most `limit`.

    What the next stage asks for: new since the last version it read (None: from the first).
    IDs are UUIDv7, so ordered by when each version was made, and versions are made and
    committed one after another by one scrape attempt at a time (ADR 03 §3): none commits
    behind a cursor. Replaced versions are listed too: each says what the page said then.
    """
    async with db.session() as session:
        listed = select(SourceVersion).where(col(SourceVersion.state) == VersionState.COMMITTED)
        if after is not None:
            listed = listed.where(col(SourceVersion.id) > after)
        return list((await session.exec(listed.order_by(col(SourceVersion.id)).limit(limit))).all())


@dataclass(frozen=True, slots=True)
class NewVersion:
    """A Source Version about to be written: its row's values, and its Source's."""

    id: uuid.UUID  # chosen first: it names the folder
    url: str  # normalised
    feed_id: uuid.UUID
    run_id: uuid.UUID | None
    fetched_at: datetime
    http_status: int | None
    media_type: str
    raw_sha256: str
    text_sha256: str
    extractor: str
    extractor_version: str
    storage_key: str
    partial: bool = False
    title: str | None = None  # cut to `MAX_TITLE_LENGTH`
    published_at: datetime | None = None
    validators: Validators = field(default_factory=Validators)  # stored on the Source at commit


async def start(db: Database, new: NewVersion) -> uuid.UUID:
    """Insert the version as `writing`, and its Source if the URL is new; return the Source's ID."""
    async with db.session() as session:
        await insert_if_absent(
            session,
            Source,
            {
                "id": uuid.uuid7(),
                "url": new.url,
                "url_hash": url_hash(new.url),
                "first_feed_id": new.feed_id,
                "first_seen_at": new.fetched_at,
                "last_checked_at": new.fetched_at,
                "etag": new.validators.etag,
                "last_modified": new.validators.last_modified,
            },
            unique=["url_hash"],
        )
        source_id = (
            await session.exec(select(Source.id).where(col(Source.url_hash) == url_hash(new.url)))
        ).one()
        session.add(
            SourceVersion(
                id=new.id,
                source_id=source_id,
                run_id=new.run_id,
                feed_id=new.feed_id,
                fetched_at=new.fetched_at,
                http_status=new.http_status,
                media_type=new.media_type,
                raw_sha256=new.raw_sha256,
                text_sha256=new.text_sha256,
                extractor=new.extractor,
                extractor_version=new.extractor_version,
                storage_key=new.storage_key,
                partial=new.partial,
                title=new.title[:MAX_TITLE_LENGTH] if new.title else None,
                published_at=new.published_at,
            )
        )
    return source_id


async def commit(db: Database, new: NewVersion, now: datetime | None = None) -> int | None:
    """Number the written version and make it its Source's latest, in one transaction.

    Returns its number, or None if it is no longer `writing` (swept as a crash's leftover):
    nothing is committed, and its folder is the caller's to delete.

    Rows are locked first (PostgreSQL; SQLite has one writer at a time): the version, so the
    sweep cannot take it once it is found `writing`; then its Source, so commits of one Source
    take turns, each numbering after the one before, the pointer naming the highest. The
    unique `(source_id, version_no)` is the backstop: a duplicate number fails the transaction
    and changes nothing.
    """
    now = now or utcnow()
    async with db.session() as session:
        writing = (
            select(SourceVersion.source_id)
            .where(
                col(SourceVersion.id) == new.id, col(SourceVersion.state) == VersionState.WRITING
            )
            .with_for_update()
        )
        source_id = (await session.exec(writing)).first()
        if source_id is None:
            return None
        await session.exec(select(Source.id).where(Source.id == source_id).with_for_update())
        highest = select(func.max(col(SourceVersion.version_no))).where(
            col(SourceVersion.source_id) == source_id
        )
        number = ((await session.exec(highest)).one() or 0) + 1
        await session.exec(
            update(SourceVersion)
            .where(col(SourceVersion.id) == new.id)
            .values(version_no=number, state=VersionState.COMMITTED)
        )
        await session.exec(
            update(SourceVersion)
            .where(
                col(SourceVersion.source_id) == source_id,
                col(SourceVersion.state) == VersionState.COMMITTED,
                col(SourceVersion.superseded_at).is_(None),
                col(SourceVersion.id) != new.id,
            )
            .values(superseded_at=now)
        )
        await session.exec(
            update(Source)
            .where(col(Source.id) == source_id)
            .values(
                latest_version_id=new.id,
                last_checked_at=new.fetched_at,
                etag=new.validators.etag,
                last_modified=new.validators.last_modified,
            )
        )
    return number


async def sweep(db: Database, sink: Sink) -> int:
    """Delete every version still `writing`, folder and row; how many versions were deleted.

    Only for a writer that knows no other writer runs (the scrape job, one attempt at a time):
    to it, a `writing` version is a crash's leftover. The leftovers are taken in one statement,
    marked `deleted` only while still `writing`: a frozen writer committing one at the same
    time either commits it first (it is kept) or finds it gone (and discards its work).
    Deletions a crash interrupted (`deleted` versions) are completed too.
    """
    async with db.session() as session:
        await session.exec(
            update(SourceVersion)
            .where(col(SourceVersion.state) == VersionState.WRITING)
            .values(state=VersionState.DELETED)
        )
    return len(await finish_deletions(db, sink))


async def finish_deletions(db: Database, sink: Sink) -> list[uuid.UUID]:
    """Complete every deletion begun: versions marked `deleted`, their folders and rows.

    Returns the Source of each version deleted (a Source left without versions is gone too).
    A crash cuts a deletion off after its mark: the next sweep or retention round finishes it.
    """
    async with db.session() as session:
        marked = select(SourceVersion.id, SourceVersion.source_id).where(
            col(SourceVersion.state) == VersionState.DELETED
        )
        leftovers = list((await session.exec(marked)).all())
    for version_id, _ in leftovers:
        await delete_version(db, sink, version_id)
    return [source_id for _, source_id in leftovers]


def due(source: Source, latest: SourceVersion, now: datetime) -> bool:
    """Whether a known Source is due for a check: the longer its text stayed the same, the later.

    A Feed lists up to 300 URLs every run (a sitemap: a month of them); a fresh one is checked
    every run, one unchanged for a month every 3 days, any at least once a week. `latest` is
    its latest committed version.
    """
    unchanged_for = max(source.last_checked_at - latest.fetched_at, timedelta(0))
    every = min(unchanged_for * RECHECK_FRACTION, RECHECK_AT_LEAST_EVERY)
    return now - source.last_checked_at + RECHECK_SLACK >= every


async def mark_checked(
    db: Database, source_id: uuid.UUID, checked_at: datetime, validators: Validators | None = None
) -> None:
    """The Source was checked at `checked_at` and found unchanged: no new version.

    With `validators` (a full response with the same text), they replace the stored ones;
    without (`304 Not Modified`), the stored ones stay.
    """
    values: dict[str, object] = {"last_checked_at": checked_at}
    if validators is not None:
        values |= {"etag": validators.etag, "last_modified": validators.last_modified}
    async with db.session() as session:
        await session.exec(update(Source).where(col(Source.id) == source_id).values(values))


async def retain(db: Database, version_id: uuid.UUID, until: datetime) -> bool:
    """Keep a committed version at least until `until` (a claim cites it, ADR 03 §8).

    Extends its `retain_until`, never shortens it. Whether the version is committed, and so
    kept: False if there is none, or it is being written or deleted. Retention re-checks a
    version's expiry when it marks it `deleted`, so a version retained meanwhile stays.
    """
    this = (col(SourceVersion.id) == version_id, col(SourceVersion.state) == VersionState.COMMITTED)
    sooner = or_(col(SourceVersion.retain_until).is_(None), col(SourceVersion.retain_until) < until)
    async with db.session() as session:
        await session.exec(update(SourceVersion).where(*this, sooner).values(retain_until=until))
        return (await session.exec(select(SourceVersion.id).where(*this))).first() is not None


async def delete_version(db: Database, sink: Sink, version_id: uuid.UUID) -> bool:
    """Delete a version: mark it `deleted`, delete its folder, then its row (ADR 03 §3).

    Its Source's latest pointer becomes NULL (by the foreign key) if it named it; a Source left
    without versions is deleted too. Whether there was such a version. A crash in between
    leaves it `deleted`, its folder perhaps half gone: calling this again completes it.
    """
    async with db.session() as session:
        marked = await session.exec(
            update(SourceVersion)
            .where(col(SourceVersion.id) == version_id)
            .values(state=VersionState.DELETED)
            .returning(col(SourceVersion.storage_key))
        )
        storage_key = marked.scalars().first()
    if storage_key is None:
        return False
    await sink.delete(storage_key)
    async with db.session() as session:
        removed = await session.exec(
            delete(SourceVersion)
            .where(col(SourceVersion.id) == version_id)
            .returning(col(SourceVersion.source_id))
        )
        for source_id in removed.scalars():  # none if a concurrent deletion came first
            others = exists().where(col(SourceVersion.source_id) == source_id)
            await session.exec(delete(Source).where(col(Source.id) == source_id, ~others))
    return True
