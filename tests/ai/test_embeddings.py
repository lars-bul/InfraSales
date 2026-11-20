import json
import math

import httpx2
import pytest
from pydantic import SecretStr

from infrasales.ai.embeddings import (
    DIMENSIONS,
    EmbeddingsClient,
    EmbeddingSettings,
    EmbeddingsUnavailableError,
)
from infrasales.ai.providers import Connection, Provider

pytestmark = pytest.mark.anyio
SETTINGS = EmbeddingSettings()
OPENROUTER = Connection(Provider.OPENROUTER, SecretStr("sk-or"))
ASKED = "Instruct: Identify the infrastructure project\nQuery: "


async def no_wait(_: float) -> None:
    pass


async def test_texts_are_embedded_in_order_shortened_to_unit_length() -> None:
    asked: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        asked.append(request)
        data = [
            {"index": 1, "embedding": [0.0, 2.0] + [0.0] * (2 * DIMENSIONS)},
            {"index": 0, "embedding": [3.0, 4.0] + [9.0] * (2 * DIMENSIONS)},
        ]
        return httpx2.Response(200, json={"data": data})

    client = EmbeddingsClient(
        SETTINGS, OPENROUTER, httpx2.MockTransport(answer), sleep=no_wait, instruction=ASKED
    )
    first, second = await client.embed(["Wärmenetz Weststadt", "Nahwärme Nord"])
    await client.aclose()

    body = json.loads(asked[0].content)
    assert body == {
        "model": "qwen/qwen3-embedding-8b",
        "input": [ASKED + "Wärmenetz Weststadt", ASKED + "Nahwärme Nord"],
        "dimensions": DIMENSIONS,
    }
    assert asked[0].headers["Authorization"] == "Bearer sk-or"
    assert len(first) == len(second) == DIMENSIONS
    assert math.isclose(sum(v * v for v in first), 1.0)
    assert second[:2] == [0.0, 1.0]


async def test_documents_are_embedded_as_they_are() -> None:
    asked: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        asked.append(request)
        return httpx2.Response(200, json={"data": [{"index": 0, "embedding": [1.0] * DIMENSIONS}]})

    client = EmbeddingsClient(SETTINGS, OPENROUTER, httpx2.MockTransport(answer), sleep=no_wait)
    await client.embed(["Wärmenetz Weststadt"])
    await client.aclose()

    assert json.loads(asked[0].content)["input"] == ["Wärmenetz Weststadt"]


@pytest.mark.parametrize(
    "answer",
    [
        httpx2.Response(401),
        httpx2.Response(200, json={"data": []}),
        httpx2.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]}),
        httpx2.Response(200, text="not json"),
    ],
)
async def test_a_refusal_or_an_odd_answer_is_unavailable(answer: httpx2.Response) -> None:
    client = EmbeddingsClient(
        SETTINGS, OPENROUTER, httpx2.MockTransport(lambda _: answer), sleep=no_wait
    )

    with pytest.raises(EmbeddingsUnavailableError):
        await client.embed(["Wärmenetz Weststadt"])
    await client.aclose()
