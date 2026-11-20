"""The AI connections and models: seeded from the environment, then changed by admins (ADR 05)."""

from dataclasses import dataclass

import structlog
from fastapi import Request
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.ai.providers import Connection, Provider
from infrasales.ai.schemas import (
    AiSettingsRead,
    ChatModel,
    ConnectionRead,
    EmbeddingModel,
    KeyState,
    Models,
    ModelsRead,
)
from infrasales.audit import service as audit
from infrasales.config.models import ConfigEntry
from infrasales.config.service import replace
from infrasales.core.db import Database, insert_if_absent
from infrasales.core.models import JSONValue
from infrasales.core.secrets import SecretBox, UnreadableSecretError
from infrasales.settings import WorkerSettings

_log = structlog.stdlib.get_logger(__name__)

CONNECTION_KEYS = {provider: f"ai_connection_{provider}" for provider in Provider}
MODELS_KEY = "ai_models"
_KEYS = [*CONNECTION_KEYS.values(), MODELS_KEY]


class KeysNotStorableError(Exception):
    """No `SECRETS_KEY` to encrypt a key with."""


class NotStoredError(Exception):
    """The setting has no row to change."""


@dataclass(frozen=True, slots=True)
class Current:
    connections: dict[Provider, Connection]
    models: Models


def _environment_keys(settings: WorkerSettings) -> dict[Provider, SecretStr | None]:
    return {
        Provider.OPENROUTER: settings.openrouter.api_key,
    }


def _environment_models(settings: WorkerSettings) -> Models:
    return Models(
        chat=ChatModel(provider=settings.llm.provider, model=settings.llm.model),
        embedding=EmbeddingModel(
            provider=settings.embedding.provider, model=settings.embedding.model
        ),
    )


def _sealed(box: SecretBox | None, key: SecretStr | None) -> dict[str, JSONValue]:
    if key is None:
        return {"api_key": None}
    if box is None:
        raise KeysNotStorableError
    return {"api_key": box.seal(key.get_secret_value())}


def _opened(box: SecretBox | None, value: dict[str, JSONValue]) -> SecretStr | None:
    sealed = value.get("api_key")
    if not isinstance(sealed, str) or box is None:
        return None
    try:
        return SecretStr(box.open(sealed))
    except UnreadableSecretError:
        return None


def _state(box: SecretBox | None, value: dict[str, JSONValue]) -> KeyState:
    if value.get("api_key") is None:
        return KeyState.UNSET
    return KeyState.SET if _opened(box, value) else KeyState.UNREADABLE


async def _stored(session: AsyncSession) -> dict[str, ConfigEntry]:
    rows = await session.exec(select(ConfigEntry).where(col(ConfigEntry.key).in_(_KEYS)))
    return {row.key: row for row in rows.all()}


async def _store_missing(
    session: AsyncSession, settings: WorkerSettings, box: SecretBox | None
) -> list[str]:
    seeds = {
        CONNECTION_KEYS[provider]: _sealed(box, key)
        for provider, key in _environment_keys(settings).items()
    }
    seeds[MODELS_KEY] = _environment_models(settings).model_dump(mode="json")
    stored: list[str] = []
    for key, value in seeds.items():
        if await insert_if_absent(session, ConfigEntry, {"key": key, "value": value}, ["key"]):
            stored.append(key)
    return stored


async def seed(db: Database, settings: WorkerSettings, box: SecretBox | None) -> None:
    """Store what the environment says where nothing is stored yet; logged, not audited."""
    try:
        async with db.session() as session:
            stored = await _store_missing(session, settings, box)
    except SQLAlchemyError:
        _log.warning("ai.not_seeded", exc_info=True)
        return
    if stored:
        _log.info("ai.seeded", keys=stored)


async def current(db: Database, box: SecretBox | None, settings: WorkerSettings) -> Current:
    """What a run uses: the stored settings, or the environment's before any are stored."""
    async with db.session() as session:
        return await current_in(session, box, settings)


async def current_in(
    session: AsyncSession, box: SecretBox | None, settings: WorkerSettings
) -> Current:
    stored = await _stored(session)
    keys = _environment_keys(settings)
    for provider, key in CONNECTION_KEYS.items():
        if (row := stored.get(key)) is not None:
            keys[provider] = _opened(box, row.value)
            if keys[provider] is None and row.value.get("api_key") is not None:
                _log.warning("ai.key_unreadable", provider=provider)
    models = stored.get(MODELS_KEY)
    return Current(
        {provider: Connection(provider, key) for provider, key in keys.items() if key},
        _environment_models(settings) if models is None else Models.model_validate(models.value),
    )


def _connection_read(provider: Provider, row: ConfigEntry, box: SecretBox | None) -> ConnectionRead:
    return ConnectionRead(
        provider=provider,
        key=_state(box, row.value),
        revision=row.revision,
        updated_at=row.updated_at,
    )


def _models_read(row: ConfigEntry) -> ModelsRead:
    models = Models.model_validate(row.value)
    return ModelsRead(**dict(models), revision=row.revision, updated_at=row.updated_at)


async def read(
    session: AsyncSession, box: SecretBox | None, settings: WorkerSettings | None = None
) -> AiSettingsRead:
    """The settings as admins see them: whether each key is set, never the key."""
    if settings is not None:
        await _store_missing(session, settings, box)
    stored = await _stored(session)
    return AiSettingsRead(
        connections=[
            _connection_read(provider, stored[key], box)
            for provider, key in CONNECTION_KEYS.items()
        ],
        models=_models_read(stored[MODELS_KEY]),
        keys_storable=box is not None,
    )


async def update_connection(  # noqa: PLR0913
    session: AsyncSession,
    provider: Provider,
    api_key: SecretStr | None,
    *,
    revision: int,
    box: SecretBox | None,
    actor: str,
    request: Request,
) -> ConnectionRead:
    """Set or remove a connection's key if it is still at `revision`; audited without it."""
    value = _sealed(box, api_key)
    replaced = await replace(session, CONNECTION_KEYS[provider], value, revision=revision)
    if replaced is None:
        raise NotStoredError
    row, _ = replaced
    audit.record(
        session,
        actor=actor,
        action="ai.connection.updated",
        target=provider,
        details={"api_key": "removed" if api_key is None else "set"},
        request=request,
    )
    return _connection_read(provider, row, box)


async def update_models(
    session: AsyncSession, models: Models, *, revision: int, actor: str, request: Request
) -> ModelsRead:
    """Choose the models if they are still at `revision`; audited before and after."""
    replaced = await replace(session, MODELS_KEY, models.model_dump(mode="json"), revision=revision)
    if replaced is None:
        raise NotStoredError
    row, before = replaced
    audit.record(
        session,
        actor=actor,
        action="ai.models.updated",
        target=MODELS_KEY,
        details={"before": before, "after": row.value},
        request=request,
    )
    return _models_read(row)
