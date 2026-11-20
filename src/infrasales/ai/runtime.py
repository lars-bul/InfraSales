"""A run's models and their clients, from the settings stored when it starts (ADR 05)."""

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

import httpx2
from pydantic_ai.models import Model

from infrasales.ai import service
from infrasales.ai.embeddings import Embedder, EmbeddingsClient, EmbeddingSettings
from infrasales.ai.model import chat_client, chat_model, mock_model
from infrasales.ai.providers import Provider
from infrasales.core.db import Database
from infrasales.core.failures import ExpectedError
from infrasales.core.secrets import SecretBox
from infrasales.settings import WorkerSettings


class ChatUnavailableError(ExpectedError):
    reason = "no key for the chat model"

    def __init__(self, provider: Provider) -> None:
        super().__init__(f"the chat model runs on {provider}, which has no key")


class Runtime:
    def __init__(
        self,
        current: service.Current,
        settings: WorkerSettings,
        stack: AsyncExitStack,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._current = current
        self._settings = settings
        self._stack = stack
        self._transport = transport

    def chat(self) -> Model:
        choice = self._current.models.chat
        if choice.provider == "mock":
            return mock_model(self._settings.llm)
        connection = self._current.connections.get(choice.provider)
        if connection is None:
            raise ChatUnavailableError(choice.provider)
        client = chat_client(self._settings.llm, self._transport)
        self._stack.push_async_callback(client.aclose)
        return chat_model(choice.model, connection, client)

    @property
    def embedding(self) -> EmbeddingSettings:
        """The environment's tuning, with the model the stored settings choose."""
        choice = self._current.models.embedding
        update = {"provider": choice.provider, "model": choice.model}
        return self._settings.embedding.model_copy(update=update)

    def embedder(self, instruction: str = "") -> Embedder | None:
        """The embedding model, asked with `instruction`; None while its service has no key."""
        settings = self.embedding
        if (connection := self._current.connections.get(settings.provider)) is None:
            return None
        client = EmbeddingsClient(settings, connection, self._transport, instruction=instruction)
        self._stack.push_async_callback(client.aclose)
        return client


@asynccontextmanager
async def opened(
    db: Database,
    settings: WorkerSettings,
    box: SecretBox | None,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> AsyncGenerator[Runtime]:
    current = await service.current(db, box, settings)
    async with AsyncExitStack() as stack:
        yield Runtime(current, settings, stack, transport)
