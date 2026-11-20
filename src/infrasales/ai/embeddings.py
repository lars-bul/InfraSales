"""Embeddings from an OpenAI-compatible embeddings API: what matching projects compares (ADR 06).

`EMBEDDING__*` tunes the client; which model answers is a runtime setting (ADR 05).
"""

import asyncio
from collections.abc import Sequence
from typing import Protocol

import httpx2
from pydantic import BaseModel, Field

from infrasales.ai.providers import Connection, Provider
from infrasales.core.api import Sleep, post
from infrasales.core.failures import ExpectedError
from infrasales.core.vectors import unit

DIMENSIONS = 1024  # every vector is cut to this length and normalised: one size for every model


class EmbeddingSettings(BaseModel):
    """The embedding model the environment seeds, and how its service is asked (`EMBEDDING__*`)."""

    provider: Provider = Provider.OPENROUTER
    model: str = Field(default="qwen/qwen3-embedding-8b", min_length=1)
    timeout_seconds: float = Field(default=30, gt=0)
    max_retries: int = Field(default=4, ge=0)


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class EmbeddingsUnavailableError(ExpectedError):
    reason = "embeddings unavailable"


class _Item(BaseModel):
    index: int
    embedding: list[float]


class _Embeddings(BaseModel):
    data: list[_Item]


class EmbeddingsClient:
    def __init__(
        self,
        settings: EmbeddingSettings,
        connection: Connection,
        transport: httpx2.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        *,
        instruction: str = "",
    ) -> None:
        """`instruction` goes before each text: what the model is asked; "" embeds documents."""
        self._url = f"{connection.base_url}/embeddings"
        self._model = settings.model
        self._instruction = instruction
        self._retries = settings.max_retries
        self._sleep = sleep
        self._client = httpx2.AsyncClient(
            transport=transport,
            timeout=settings.timeout_seconds,
            headers={"Authorization": f"Bearer {connection.api_key.get_secret_value()}"},
        )

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        inputs = [self._instruction + text for text in texts]
        body = {"model": self._model, "input": inputs, "dimensions": DIMENSIONS}
        try:
            response = await post(
                self._client, self._url, body, retries=self._retries, sleep=self._sleep
            )
            items = _Embeddings.model_validate_json(response.content).data
        except (httpx2.HTTPError, ValueError) as error:
            raise EmbeddingsUnavailableError(type(error).__name__) from error
        if len(items) != len(texts) or any(len(item.embedding) < DIMENSIONS for item in items):
            raise EmbeddingsUnavailableError
        return [unit(item.embedding, DIMENSIONS) for item in sorted(items, key=lambda i: i.index)]

    async def aclose(self) -> None:
        await self._client.aclose()
