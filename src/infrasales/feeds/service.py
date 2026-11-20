"""Listing, adding and deleting Feeds, and noting how reading one went."""

import re
import unicodedata
import uuid

from sqlalchemy import ColumnElement, exists, func, or_
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped
from sqlmodel import col, delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.catalog.models import Source, SourceVersion, VersionState
from infrasales.core.db import Database
from infrasales.core.models import utcnow
from infrasales.feeds.models import Feed, FeedState
from infrasales.feeds.schemas import FeedCreate

MAX_SLUG_LENGTH = 64  # `feed.slug`


class HasSourcesError(Exception):
    """The Feed has collected Sources: the catalog keeps the Feed each one came from."""


def _has_sources(feed_id: Mapped[uuid.UUID] | uuid.UUID) -> ColumnElement[bool]:
    """Whether a Source or a Source Version names the Feed (its foreign keys do)."""
    return or_(
        exists().where(col(Source.first_feed_id) == feed_id),
        exists().where(col(SourceVersion.feed_id) == feed_id),
    )


async def listing(session: AsyncSession) -> list[tuple[Feed, bool, int]]:
    """Every Feed by name, whether it has collected Sources, and how many are listed under it.

    The count is of the Sources whose latest committed version came from the Feed, as the
    Sources page lists them (`?feed=<slug>`); all Feeds are counted in one query.
    """
    counted = (
        select(col(SourceVersion.feed_id), func.count().label("sources"))
        .select_from(Source)
        .join(SourceVersion, col(SourceVersion.id) == col(Source.latest_version_id))
        .where(col(SourceVersion.state) == VersionState.COMMITTED)
        .group_by(col(SourceVersion.feed_id))
        .subquery()
    )
    query = (
        select(Feed, _has_sources(col(Feed.id)), func.coalesce(counted.c.sources, 0))
        .outerjoin(counted, counted.c.feed_id == col(Feed.id))
        .order_by(col(Feed.name), col(Feed.id))
    )
    return [
        (feed, bool(has_sources), sources)
        for feed, has_sources, sources in (await session.exec(query)).all()
    ]


async def add(session: AsyncSession, new: FeedCreate) -> Feed | None:
    """Add `new` under a free slug derived from its name; None if a Feed has its URL already."""
    base = slugify(new.name)
    while True:  # again only if a concurrent request took the URL or the slug meanwhile
        if await _with_url(session, new.url):
            return None
        feed = Feed(
            name=new.name,
            slug=await free_slug(session, base),
            kind=new.kind,
            category=new.category,
            url=new.url,
            settings=new.settings,
            extractor=new.extractor,
        )
        if await _inserted(session, feed):
            return feed


async def remove(session: AsyncSession, feed_id: uuid.UUID) -> Feed | None:
    """Delete the Feed `feed_id`, which has collected no Sources; None if there is none.

    Raises `HasSourcesError` otherwise: its Sources keep where they came from, and its files
    in the sink stay. A Source stored while it is deleted is refused by the foreign keys.
    """
    feed = await session.get(Feed, feed_id)
    if feed is None:
        return None
    if (await session.exec(select(_has_sources(feed_id)))).one():
        raise HasSourcesError
    try:
        async with session.begin_nested():  # a refused delete leaves the request's transaction
            await session.exec(delete(Feed).where(col(Feed.id) == feed_id))
    except IntegrityError:
        raise HasSourcesError from None
    return feed


async def note_read(
    db: Database, feed_id: uuid.UUID, state: FeedState, error: str | None = None
) -> None:
    """Record that the Feed was read just now: how it went, and why not (a reason, no details)."""
    async with db.session() as session:
        await session.exec(
            update(Feed)
            .where(col(Feed.id) == feed_id)
            .values(last_scraped_at=utcnow(), state=state, last_error=error)
        )


def slugify(name: str) -> str:
    """`name` as lower-case ASCII words joined by `-` ("Heizwerk Journal" → "heizwerk-journal")."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return words[: MAX_SLUG_LENGTH - 4].rstrip("-") or "feed"  # room for a "-999" suffix


async def _with_url(session: AsyncSession, url: str) -> bool:
    return (await session.exec(select(Feed.id).where(col(Feed.url) == url))).first() is not None


async def free_slug(session: AsyncSession, base: str) -> str:
    """`base`, else the first of `base-2`, `base-3`, … that no Feed has."""
    query = select(Feed.slug).where(col(Feed.slug).startswith(base, autoescape=True))
    taken = set((await session.exec(query)).all())
    slug, n = base, 1
    while slug in taken:
        n += 1
        slug = f"{base}-{n}"
    return slug


async def _inserted(session: AsyncSession, feed: Feed) -> bool:
    """Insert `feed` unless it conflicts with a Feed added meanwhile (same URL or slug)."""
    insert = postgresql.insert if session.get_bind().dialect.name == "postgresql" else sqlite.insert
    statement = insert(Feed).values(feed.model_dump()).on_conflict_do_nothing()
    return (await session.exec(statement.returning(col(Feed.id)))).first() is not None
