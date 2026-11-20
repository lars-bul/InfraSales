import re
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response

from infrasales.auth.deps import AdminUser, CurrentUser
from infrasales.config import service
from infrasales.config.schemas import ConfigEntryRead, ConfigKey, Schedule
from infrasales.core.db import Session

router = APIRouter(prefix="/api/config", tags=["config"])
_STALE = "The setting changed meanwhile: reload it, then edit again"


def if_match_revision(if_match: str) -> int | None:
    """The revision an `If-Match` header names: `"3"` is revision 3."""
    tag = re.fullmatch(r'"(\d{1,9})"', if_match.strip())
    return int(tag.group(1)) if tag else None


@router.get("")
async def list_config(_: CurrentUser, session: Session) -> list[ConfigEntryRead]:
    """The global configuration: every signed-in user may read it."""
    return await service.entries(session)


@router.put(
    "/{key}",
    responses={
        404: {"description": "No such setting"},
        412: {"description": "The setting changed since that revision"},
    },
)
async def update_config(  # noqa: PLR0913  # what changes, under which revision, by whom
    key: ConfigKey,
    value: Schedule,
    *,
    if_match: Annotated[str, Header(description='The revision edited, e.g. `"3"`')],
    admin: AdminUser,
    session: Session,
    request: Request,
    response: Response,
) -> ConfigEntryRead:
    """Change one setting (admins only) unless it changed since that revision (RFC 9110).

    The change is audited; the response's `ETag` names the new revision.
    """
    if (revision := if_match_revision(if_match)) is None:
        raise HTTPException(412, _STALE)
    try:
        entry = await service.update(
            session, key, value, revision=revision, actor=admin.subject, request=request
        )
    except service.StaleRevisionError:
        raise HTTPException(412, _STALE) from None
    if entry is None:
        raise HTTPException(404, "No such setting")
    response.headers["ETag"] = f'"{entry.revision}"'
    return entry
