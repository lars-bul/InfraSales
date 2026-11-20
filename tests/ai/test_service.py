from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr
from sqlmodel import select
from starlette.requests import Request

from infrasales.ai import service
from infrasales.ai.providers import Provider
from infrasales.ai.schemas import ChatModel, EmbeddingModel, KeyState, Models
from infrasales.ai.settings import ConnectionSettings, LLMSettings
from infrasales.config.models import ConfigEntry
from infrasales.config.service import StaleRevisionError
from infrasales.core.db import Database
from infrasales.core.secrets import SecretBox, new_key
from infrasales.settings import WorkerSettings
from tests.helpers import audit_events

pytestmark = pytest.mark.anyio
KEY = SecretStr(new_key())
BOX = SecretBox(KEY)
REQUEST = Request({"type": "http", "client": ("203.0.113.9", 1)})
DEFAULT_MODELS = Models(
    chat=ChatModel(provider="mock"),
    embedding=EmbeddingModel(provider=Provider.OPENROUTER, model="qwen/qwen3-embedding-8b"),
)


def environment(**sections: object) -> WorkerSettings:
    return WorkerSettings(
        database_url=SecretStr("sqlite+aiosqlite://"),
        secrets_key=KEY,
        **sections,  # pyright: ignore[reportArgumentType]
    )


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    yield db
    await db.dispose()


async def set_key(
    db: Database, key: str | None, *, revision: int, box: SecretBox | None = BOX
) -> service.ConnectionRead:
    async with db.session() as session:
        return await service.update_connection(
            session,
            Provider.OPENROUTER,
            None if key is None else SecretStr(key),
            revision=revision,
            box=box,
            actor="basic:alice",
            request=REQUEST,
        )


async def test_the_environment_seeds_the_connections_and_models_once(db: Database) -> None:
    first = environment(
        openrouter=ConnectionSettings(api_key=SecretStr("sk-or-test")),
        llm=LLMSettings(provider=Provider.OPENROUTER, model="mistralai/mistral-small"),
    )
    await service.seed(db, first, BOX)
    await service.seed(
        db, environment(llm=LLMSettings(provider=Provider.OPENROUTER, model="x")), BOX
    )

    current = await service.current(db, BOX, environment())

    assert current.connections[Provider.OPENROUTER].api_key.get_secret_value() == "sk-or-test"
    assert current.models == Models(
        chat=ChatModel(provider=Provider.OPENROUTER, model="mistralai/mistral-small"),
        embedding=DEFAULT_MODELS.embedding,
    )


async def test_a_stored_key_is_encrypted_at_rest(db: Database) -> None:
    seeded = environment(openrouter=ConnectionSettings(api_key=SecretStr("sk-or-test")))
    await service.seed(db, seeded, BOX)

    async with db.session() as session:
        stored = [row.value for row in (await session.exec(select(ConfigEntry))).all()]

    assert "sk-or-test" not in str(stored)


async def test_before_anything_is_stored_the_environment_counts(db: Database) -> None:
    seeded = environment(openrouter=ConnectionSettings(api_key=SecretStr("sk-or-test")))

    current = await service.current(db, BOX, seeded)

    assert list(current.connections) == [Provider.OPENROUTER]
    assert current.models == DEFAULT_MODELS


async def test_a_key_that_no_longer_decrypts_is_unreadable_and_unused(db: Database) -> None:
    seeded = environment(openrouter=ConnectionSettings(api_key=SecretStr("sk-or-test")))
    await service.seed(db, seeded, BOX)
    other = SecretBox(SecretStr(new_key()))

    current = await service.current(db, other, environment())
    async with db.session() as session:
        read = await service.read(session, other)

    assert current.connections == {}
    assert [(c.provider, c.key) for c in read.connections] == [
        (Provider.OPENROUTER, KeyState.UNREADABLE),
    ]


async def test_admins_set_and_remove_a_key_audited_without_it(
    db: Database, database_url: str
) -> None:
    await service.seed(db, environment(), BOX)

    stored = await set_key(db, "sk-or-new", revision=1)
    removed = await set_key(db, None, revision=2)

    assert (stored.key, stored.revision, removed.key) == (KeyState.SET, 2, KeyState.UNSET)
    audited = [(e.action, e.target, e.details) for e in await audit_events(database_url)]
    assert audited == [
        ("ai.connection.updated", "openrouter", {"api_key": "set"}),
        ("ai.connection.updated", "openrouter", {"api_key": "removed"}),
    ]


async def test_an_edit_of_an_older_revision_changes_nothing(db: Database) -> None:
    await service.seed(db, environment(), BOX)
    await set_key(db, "sk-or-new", revision=1)

    with pytest.raises(StaleRevisionError):
        await set_key(db, "sk-or-other", revision=1)

    current = await service.current(db, BOX, environment())
    assert current.connections[Provider.OPENROUTER].api_key.get_secret_value() == "sk-or-new"


async def test_no_key_is_stored_without_a_secrets_key(db: Database) -> None:
    await service.seed(db, environment(), BOX)

    with pytest.raises(service.KeysNotStorableError):
        await set_key(db, "sk-or-new", revision=1, box=None)

    assert (await set_key(db, None, revision=1, box=None)).key == KeyState.UNSET


async def test_admins_choose_the_models_audited_before_and_after(
    db: Database, database_url: str
) -> None:
    await service.seed(db, environment(), BOX)
    embedding = EmbeddingModel(provider=Provider.OPENROUTER, model="baai/bge-m3")
    chosen = DEFAULT_MODELS.model_copy(update={"embedding": embedding})

    async with db.session() as session:
        read = await service.update_models(
            session, chosen, revision=1, actor="basic:alice", request=REQUEST
        )

    assert (read.embedding, read.revision) == (chosen.embedding, 2)
    assert (await service.current(db, BOX, environment())).models == chosen
    (event,) = await audit_events(database_url)
    assert (event.action, event.target) == ("ai.models.updated", "ai_models")
    assert event.details == {
        "before": DEFAULT_MODELS.model_dump(mode="json"),
        "after": chosen.model_dump(mode="json"),
    }


async def test_the_settings_say_whether_keys_can_be_stored(db: Database) -> None:
    await service.seed(db, environment(), BOX)

    async with db.session() as session:
        storable = await service.read(session, BOX)
        not_storable = await service.read(session, None)

    assert (storable.keys_storable, not_storable.keys_storable) == (True, False)
    assert storable.models.model_dump(include={"chat", "embedding"}) == (
        DEFAULT_MODELS.model_dump()
    )
