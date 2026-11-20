"""Admins read and change the AI connections and models (ADR 05)."""

from dataclasses import dataclass
from typing import Annotated, Any

import httpx2
from fastapi import APIRouter, Header, HTTPException, Request, Response

from infrasales.ai import service
from infrasales.ai.listing import (
    KeyRefusedError,
    ModelOption,
    ModelsUnavailableError,
    Purpose,
    available,
)
from infrasales.ai.providers import Provider
from infrasales.ai.schemas import (
    AiSettingsRead,
    ConnectionRead,
    ConnectionWrite,
    Models,
    ModelsRead,
)
from infrasales.auth.deps import AdminUser
from infrasales.config.router import if_match_revision
from infrasales.config.service import StaleRevisionError
from infrasales.core.db import Session
from infrasales.core.secrets import SecretBox
from infrasales.core.state import StateKey
from infrasales.settings import WorkerSettings


@dataclass(frozen=True, slots=True)
class AiContext:
    settings: WorkerSettings
    box: SecretBox | None
    transport: httpx2.AsyncBaseTransport | None = None


AI = StateKey[AiContext]("ai")
router = APIRouter(prefix="/api/ai", tags=["ai"])
_STALE = "The setting changed meanwhile: reload it, then edit again"
_IF_MATCH = Header(description='The revision edited, e.g. `"3"`')
_CHANGE: dict[int | str, dict[str, Any]] = {
    404: {"description": "No such setting"},
    412: {"description": "The setting changed since that revision"},
}


def _revision(if_match: str) -> int:
    if (revision := if_match_revision(if_match)) is None:
        raise HTTPException(412, _STALE)
    return revision


@router.get("")
async def read_ai_settings(_: AdminUser, session: Session, request: Request) -> AiSettingsRead:
    """The connections and models (admins only): whether each key is set, never the key."""
    ai = AI.get(request)
    return await service.read(session, ai.box, ai.settings)


@router.put(
    "/connections/{provider}",
    responses=_CHANGE | {409: {"description": "No SECRETS_KEY to encrypt the key with"}},
)
async def update_ai_connection(  # noqa: PLR0913
    provider: Provider,
    connection: ConnectionWrite,
    *,
    if_match: Annotated[str, _IF_MATCH],
    admin: AdminUser,
    session: Session,
    request: Request,
    response: Response,
) -> ConnectionRead:
    """Set a connection's key, or remove it with `null` (admins only); audited without it."""
    try:
        stored = await service.update_connection(
            session,
            provider,
            connection.api_key,
            revision=_revision(if_match),
            box=AI.get(request).box,
            actor=admin.subject,
            request=request,
        )
    except service.KeysNotStorableError:
        raise HTTPException(409, "Keys are stored encrypted: set SECRETS_KEY first") from None
    except StaleRevisionError:
        raise HTTPException(412, _STALE) from None
    except service.NotStoredError:
        raise HTTPException(404, "No such setting") from None
    response.headers["ETag"] = f'"{stored.revision}"'
    return stored


@router.put("/models", responses=_CHANGE)
async def update_ai_models(  # noqa: PLR0913
    models: Models,
    *,
    if_match: Annotated[str, _IF_MATCH],
    admin: AdminUser,
    session: Session,
    request: Request,
    response: Response,
) -> ModelsRead:
    """Choose the chat and embedding models (admins only); the next runs use them."""
    try:
        stored = await service.update_models(
            session, models, revision=_revision(if_match), actor=admin.subject, request=request
        )
    except StaleRevisionError:
        raise HTTPException(412, _STALE) from None
    except service.NotStoredError:
        raise HTTPException(404, "No such setting") from None
    response.headers["ETag"] = f'"{stored.revision}"'
    return stored


@router.get(
    "/connections/{provider}/models",
    responses={
        409: {"description": "The service lists its models for a valid key only"},
        502: {"description": "The service did not list its models"},
    },
)
async def list_ai_models(
    provider: Provider, purpose: Purpose, _: AdminUser, session: Session, request: Request
) -> list[ModelOption]:
    """The models a service offers for a purpose (admins only), listed with its stored key."""
    ai = AI.get(request)
    current = await service.current_in(session, ai.box, ai.settings)
    connection = current.connections.get(provider)
    key = connection.api_key if connection else None
    try:
        return await available(provider, purpose, key, ai.transport)
    except KeyRefusedError:
        raise HTTPException(409, f"{provider} lists its models for a valid key only") from None
    except ModelsUnavailableError:
        raise HTTPException(502, f"{provider} did not list its models") from None
