"""The Source API: what InfraSales collected, each Source's versions, their text and raw files."""

import re
import uuid
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Request, Response

from infrasales.auth.deps import AdminUser
from infrasales.catalog import listing
from infrasales.catalog.layout import raw_name
from infrasales.catalog.models import Source
from infrasales.catalog.schemas import (
    SourceCount,
    SourceFilter,
    SourceListed,
    SourceQuery,
    SourceRead,
    VersionText,
)
from infrasales.core.db import Session
from infrasales.sink.store import SINK

router = APIRouter(prefix="/api/sources", tags=["sources"])

type Responses = dict[int | str, dict[str, Any]]

_NOT_FOUND: Responses = {404: {"description": "No such Source, or no such version of it"}}
_GONE: Responses = {410: {"description": "The version's files are no longer in the sink"}}
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9.-]+")
# A raw file is a stranger's page: downloaded, never shown, and sandboxed if a browser does.
_RAW_HEADERS = {"Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff"}


@router.get("")
async def list_sources(
    query: Annotated[SourceQuery, Query()], _: AdminUser, session: Session
) -> list[SourceListed]:
    """The collected Sources, newest change first (admins only), filtered.

    Each is listed by its latest version, or by the one `run` wrote. `feed` and `category` may
    be given several times; `q` matches the title or the address; `since` and `until` bound when
    the listed version was fetched (its last change). A full page means older ones may follow:
    ask again with `before` the last one's `version.id`.
    """
    return [
        SourceListed(
            id=listed.source.id,
            url=listed.source.url,
            first_seen_at=listed.source.first_seen_at,
            last_checked_at=listed.source.last_checked_at,
            versions=listed.versions,
            version=listing.version_read(listed.version, listed.feed),
        )
        for listed in await listing.sources(session, query)
    ]


@router.get("/count")
async def count_sources(
    query: Annotated[SourceFilter, Query()], _: AdminUser, session: Session
) -> SourceCount:
    """How many Sources `GET /api/sources` lists with the same filters, every page (admins only)."""
    return SourceCount(count=await listing.count(session, query))


@router.get("/{source_id}", responses=_NOT_FOUND)
async def read_source(source_id: uuid.UUID, _: AdminUser, session: Session) -> SourceRead:
    """A Source and its versions, newest first (admins only)."""
    found = await listing.source(session, source_id)
    if found is None:
        raise HTTPException(404, "No Source has that ID")
    source, versions = found
    return SourceRead(
        id=source.id,
        url=source.url,
        first_seen_at=source.first_seen_at,
        last_checked_at=source.last_checked_at,
        versions=[listing.version_read(version, feed) for version, feed in versions],
    )


@router.get("/{source_id}/versions/{number}", responses=_NOT_FOUND | _GONE)
async def read_version_text(
    source_id: uuid.UUID, number: int, _: AdminUser, session: Session, request: Request
) -> VersionText:
    """What version `number` of the Source said, as its extractor read it (admins only)."""
    version = await listing.version(session, source_id, number)
    if version is None:
        raise HTTPException(404, "The Source has no such version")
    try:
        return await listing.text(SINK.get(request), version)
    except FileNotFoundError:
        raise HTTPException(410, "The version's files are gone") from None


@router.get(
    "/{source_id}/versions/{number}/raw",
    response_class=Response,
    responses=_NOT_FOUND | _GONE | {200: {"content": {"application/octet-stream": {}}}},
)
async def download_raw_version(
    source_id: uuid.UUID, number: int, _: AdminUser, session: Session, request: Request
) -> Response:
    """Version `number` of the Source as fetched (HTML, PDF, …), as a download (admins only)."""
    version = await listing.version(session, source_id, number)
    if version is None:
        raise HTTPException(404, "The Source has no such version")
    try:
        raw = await listing.raw(SINK.get(request), version)
    except FileNotFoundError:
        raise HTTPException(410, "The version's files are gone") from None
    source = await session.get_one(Source, source_id)
    disposition = f'attachment; filename="{download_name(source.url, number, version.media_type)}"'
    return Response(
        raw,
        media_type=version.media_type,
        headers=_RAW_HEADERS | {"Content-Disposition": disposition},
    )


def download_name(url: str, number: int, media_type: str) -> str:
    """`tiefbau-aktuell.test-v3.html`: the Source's host, the version, the file's extension."""
    host = _UNSAFE_NAME.sub("-", urlsplit(url).hostname or "source")
    return f"{host}-v{number}.{raw_name(media_type).removeprefix('raw.')}"
