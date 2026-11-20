import json
from collections.abc import AsyncGenerator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager

import httpx2
import pytest
from pydantic import SecretStr
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from starlette.requests import Request

from infrasales.ai import service
from infrasales.ai.embeddings import DIMENSIONS, EmbeddingSettings
from infrasales.ai.providers import Connection, Provider
from infrasales.ai.runtime import ChatUnavailableError, Runtime, opened
from infrasales.ai.schemas import ChatModel, EmbeddingModel, Models
from infrasales.core.db import Database
from infrasales.core.secrets import SecretBox, new_key
from infrasales.settings import WorkerSettings

pytestmark = pytest.mark.anyio
KEY = SecretStr(new_key())
OPENROUTER = Connection(Provider.OPENROUTER, SecretStr("sk-or-test"))
CONNECTED = {Provider.OPENROUTER: OPENROUTER}
MODELS = Models(
    chat=ChatModel(provider=Provider.OPENROUTER, model="mistralai/mistral-small"),
    embedding=EmbeddingModel(provider=Provider.OPENROUTER, model="qwen/qwen3-embedding-8b"),
)
SETTINGS = WorkerSettings(
    database_url=SecretStr("sqlite+aiosqlite://"),
    secrets_key=KEY,
    embedding=EmbeddingSettings(timeout_seconds=5, max_retries=0),
)
COMPLETION = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 0,
    "model": "mistralai/mistral-small",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop"}
    ],
}


class Services:
    """The APIs, answering every request; what each was sent is kept."""

    def __init__(self) -> None:
        self.sent: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.sent.append(request)
        if request.url.path.endswith("/embeddings"):
            return httpx2.Response(
                200, json={"data": [{"index": 0, "embedding": [1.0] * DIMENSIONS}]}
            )
        return httpx2.Response(200, json=COMPLETION)


@asynccontextmanager
async def running(
    connections: Mapping[Provider, Connection], models: Models = MODELS
) -> AsyncGenerator[tuple[Runtime, Services]]:
    services = Services()
    async with AsyncExitStack() as stack:
        current = service.Current(dict(connections), models)
        yield Runtime(current, SETTINGS, stack, httpx2.MockTransport(services)), services


async def test_chat_runs_on_the_chosen_service_with_its_key() -> None:
    async with running(CONNECTED) as (ai, services):
        result = await Agent(ai.chat(), output_type=str).run("anything")

    (request,) = services.sent
    assert result.output == "Hi"
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-or-test"
    assert json.loads(request.content)["model"] == "mistralai/mistral-small"


async def test_the_mock_chats_without_any_connection() -> None:
    mock = MODELS.model_copy(update={"chat": ChatModel(provider="mock")})

    async with running({}, mock) as (ai, _):
        model = ai.chat()
        result = await Agent(model, output_type=str).run("anything")

    assert isinstance(model, TestModel)
    assert result.output == "Hello world"


async def test_chat_on_a_service_without_its_key_fails_the_run() -> None:
    async with running({}) as (ai, _):
        with pytest.raises(ChatUnavailableError, match="openrouter"):
            ai.chat()


async def test_texts_are_embedded_by_the_chosen_model_with_the_environments_tuning() -> None:
    chosen = EmbeddingModel(provider=Provider.OPENROUTER, model="baai/bge-m3")
    asked = "Instruct: Identify the infrastructure project\nQuery: "

    async with running(CONNECTED, MODELS.model_copy(update={"embedding": chosen})) as (
        ai,
        services,
    ):
        embedder = ai.embedder(asked)
        assert embedder is not None
        await embedder.embed(["Wärmenetz Weststadt"])

    (request,) = services.sent
    assert (ai.embedding.model, ai.embedding.timeout_seconds) == ("baai/bge-m3", 5)
    assert str(request.url) == "https://openrouter.ai/api/v1/embeddings"
    assert request.headers["authorization"] == "Bearer sk-or-test"
    body = json.loads(request.content)
    assert (body["input"], body["dimensions"]) == ([asked + "Wärmenetz Weststadt"], DIMENSIONS)


async def test_embeddings_are_off_without_their_key() -> None:
    async with running({}) as (ai, _):
        assert ai.embedder() is None


async def test_the_clients_of_a_run_close_with_it() -> None:
    async with running(CONNECTED) as (ai, _):
        embedder = ai.embedder()
        assert embedder is not None

    with pytest.raises(RuntimeError, match="closed"):
        await embedder.embed(["too late"])


async def test_every_run_reads_the_settings_stored_when_it_starts(database_url: str) -> None:
    db, box = Database(database_url), SecretBox(KEY)
    await service.seed(db, SETTINGS, box)
    request = Request({"type": "http", "client": ("203.0.113.9", 1)})

    async with opened(db, SETTINGS, box) as before:
        assert before.embedder() is None
    async with db.session() as session:
        await service.update_connection(
            session,
            Provider.OPENROUTER,
            SecretStr("sk-or-test"),
            revision=1,
            box=box,
            actor="basic:alice",
            request=request,
        )
        await service.update_models(
            session, MODELS, revision=1, actor="basic:alice", request=request
        )
    async with opened(db, SETTINGS, box) as after:
        assert after.embedder() is not None
        assert after.embedding.model == "qwen/qwen3-embedding-8b"
    await db.dispose()
