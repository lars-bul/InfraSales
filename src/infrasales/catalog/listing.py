"""Reading the catalog for people: Sources page by page, one Source's versions, their files.

Only committed versions are shown. The sink is read for a version's text and raw file only.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, ScalarSelect, func, or_
from sqlalchemy.orm import aliased
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.catalog.layout import EXTRACTED, raw_name
from infrasales.catalog.models import Source, SourceVersion, VersionState
from infrasales.catalog.schemas import FeedRef, SourceFilter, SourceQuery, VersionRead, VersionText
from infrasales.feeds.models import Feed
from infrasales.sink.store import Sink

_COMMITTED = col(SourceVersion.state) == VersionState.COMMITTED


@dataclass(frozen=True, slots=True)
class Listed:
    source: Source
    version: SourceVersion
    feed: Feed
    versions: int  # committed ones


def _number(version: SourceVersion) -> int:
    """A committed version's number: every version is numbered when it commits."""
    if version.version_no is None:
        msg = f"version {version.id} is not committed"
        raise ValueError(msg)
    return version.version_no


def version_read(version: SourceVersion, feed: Feed) -> VersionRead:
    return VersionRead(
        id=version.id,
        number=_number(version),
        fetched_at=version.fetched_at,
        run_id=version.run_id,
        feed=FeedRef(slug=feed.slug, name=feed.name),
        http_status=version.http_status,
        media_type=version.media_type,
        partial=version.partial,
        title=version.title,
        published_at=version.published_at,
        extractor=version.extractor,
        extractor_version=version.extractor_version,
        superseded_at=version.superseded_at,
    )


def _versions() -> ScalarSelect[int]:
    """How many committed versions the listed Source has (retention prunes old ones)."""
    counted = aliased(SourceVersion)
    return (
        select(func.count())
        .where(col(counted.source_id) == col(Source.id), counted.state == VersionState.COMMITTED)
        .scalar_subquery()
    )


def _listed_by(query: SourceFilter) -> ColumnElement[bool]:
    """Which version a Source is listed by: `run`'s, else its latest."""
    shown = (
        col(SourceVersion.run_id) == query.run
        if query.run
        else col(SourceVersion.id) == col(Source.latest_version_id)
    )
    return (col(SourceVersion.source_id) == col(Source.id)) & shown


def _matching(query: SourceFilter, versions: ScalarSelect[int]) -> list[ColumnElement[bool]]:
    """What the Source and the version it is listed by (with its Feed) must be."""
    conditions = [_COMMITTED]
    if query.feed:
        conditions.append(col(Feed.slug).in_(query.feed))
    if query.category:
        conditions.append(col(Feed.category).in_(query.category))
    if query.q:
        conditions.append(
            or_(
                col(SourceVersion.title).icontains(query.q, autoescape=True),
                col(Source.url).icontains(query.q, autoescape=True),
            )
        )
    if query.since:
        conditions.append(col(SourceVersion.fetched_at) >= query.since)
    if query.until:
        conditions.append(col(SourceVersion.fetched_at) < query.until)
    if query.changed is not None:
        conditions.append(versions > 1 if query.changed else versions == 1)
    if query.partial is not None:
        conditions.append(col(SourceVersion.partial) == query.partial)
    return conditions


async def sources(session: AsyncSession, query: SourceQuery) -> list[Listed]:
    """Sources, the newest listed version first: each by its latest version, or by `run`'s.

    `before` pages back from a listed version: IDs are UUIDv7, so ordered by time.
    """
    versions = _versions()
    statement = (
        select(Source, SourceVersion, Feed, versions)
        .join(SourceVersion, _listed_by(query))
        .join(Feed, col(Feed.id) == col(SourceVersion.feed_id))
        .where(*_matching(query, versions))
    )
    if query.before:
        statement = statement.where(col(SourceVersion.id) < query.before)
    newest = statement.order_by(col(SourceVersion.id).desc()).limit(query.limit)
    return [Listed(*row) for row in (await session.exec(newest)).all()]


async def count(session: AsyncSession, query: SourceFilter) -> int:
    """How many Sources `sources` lists for the same filters, every page together."""
    statement = (
        select(func.count())
        .select_from(Source)
        .join(SourceVersion, _listed_by(query))
        .join(Feed, col(Feed.id) == col(SourceVersion.feed_id))
        .where(*_matching(query, _versions()))
    )
    return (await session.exec(statement)).one()


async def source(
    session: AsyncSession, source_id: uuid.UUID
) -> tuple[Source, list[tuple[SourceVersion, Feed]]] | None:
    """The Source with its committed versions, newest first; None if there is none."""
    found = await session.get(Source, source_id)
    if found is None:
        return None
    statement = (
        select(SourceVersion, Feed)
        .join(Feed, col(Feed.id) == col(SourceVersion.feed_id))
        .where(col(SourceVersion.source_id) == source_id, _COMMITTED)
        .order_by(col(SourceVersion.version_no).desc())
    )
    return found, [(version, feed) for version, feed in (await session.exec(statement)).all()]


async def version(session: AsyncSession, source_id: uuid.UUID, number: int) -> SourceVersion | None:
    """The Source's committed version `number`; None if there is none (or no longer)."""
    statement = select(SourceVersion).where(
        col(SourceVersion.source_id) == source_id,
        col(SourceVersion.version_no) == number,
        _COMMITTED,
    )
    return (await session.exec(statement)).first()


async def text(sink: Sink, version: SourceVersion) -> VersionText:
    """The version's extracted text; raises `FileNotFoundError` if its files are gone."""
    extracted = json.loads(await sink.read(f"{version.storage_key}/{EXTRACTED}"))
    published = extracted.get("published_at")
    return VersionText(
        number=_number(version),
        title=extracted.get("title"),
        author=extracted.get("author"),
        published_at=datetime.fromisoformat(published) if published else None,
        text=extracted["text"],
    )


async def raw(sink: Sink, version: SourceVersion) -> bytes:
    """The version's bytes as fetched; raises `FileNotFoundError` if its files are gone."""
    return await sink.read(f"{version.storage_key}/{raw_name(version.media_type)}")
