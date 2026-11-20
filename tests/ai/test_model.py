import json

import httpx2
import pytest
from pydantic import SecretStr
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from infrasales.ai.limits import QuotaExhaustedError
from infrasales.ai.model import chat_client, chat_model, mock_model
from infrasales.ai.providers import Connection, Provider
from infrasales.ai.settings import LLMSettings

pytestmark = pytest.mark.anyio
CONNECTION = Connection(Provider.OPENROUTER, SecretStr("sk-test"))
COMPLETION = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 0,
    "model": "a-model",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop"}
    ],
}


async def test_the_mock_gives_its_fixed_reply() -> None:
    model = mock_model(LLMSettings())

    result = await Agent(model, output_type=str).run("anything")

    assert isinstance(model, TestModel)
    assert result.output == "Hello world"


async def test_a_service_is_asked_for_its_model_with_the_key() -> None:
    sent: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=COMPLETION)

    async with chat_client(LLMSettings(), httpx2.MockTransport(answer)) as client:
        model = chat_model("a-model", CONNECTION, client)
        result = await Agent(model, output_type=str).run("anything")

    (request,) = sent
    assert result.output == "Hi"
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-test"
    assert json.loads(request.content)["model"] == "a-model"


async def test_a_quota_used_up_for_long_fails_the_run_without_retrying() -> None:
    sent: list[httpx2.Request] = []

    def refuse(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(429, headers={"Retry-After": "3600"})

    async with chat_client(LLMSettings(), httpx2.MockTransport(refuse)) as client:
        agent = Agent(chat_model("a-model", CONNECTION, client), output_type=str)
        with pytest.raises(QuotaExhaustedError):
            await agent.run("anything")

    assert len(sent) == 1
